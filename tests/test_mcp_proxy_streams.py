"""An MCP server that keeps its event stream open must never tie up the Runtime's proxy."""

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

from app import mcp_proxy  # noqa: E402
from app.mcp_proxy import McpProxy, _forward, _request_ids, proxy_mcp  # noqa: E402


class _StreamingServer(BaseHTTPRequestHandler):
    """Answers a POST as server-sent events, then keeps pinging like a long-lived stream."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n')
        answer = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}})
        self.wfile.write(f"event: message\ndata: {answer}\n\n".encode())
        self.wfile.flush()
        try:
            for _ in range(200):
                time.sleep(0.05)
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StreamingServer)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/mcp"


def test_answer_in_an_open_stream_returns_at_once() -> None:
    server, url = _serve()
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}).encode()
        began = time.monotonic()
        status, headers, raw = _forward(url, {"Content-Type": "application/json"}, body, "POST", timeout=5)
        took = time.monotonic() - began
    finally:
        server.shutdown()
    assert status == 200
    assert b'"id": 7' in raw and b'"tools": []' in raw
    # The server would keep the stream open for 10 seconds.
    assert took < 3


def test_stream_without_an_answer_stops_at_the_deadline() -> None:
    server, url = _serve()
    try:
        # A request id the server never answers.
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        original = _StreamingServer.do_POST

        def wrong_id(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for _ in range(200):
                    time.sleep(0.05)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        _StreamingServer.do_POST = wrong_id
        try:
            began = time.monotonic()
            _forward(url, {"Content-Type": "application/json"}, body, "POST", timeout=5, deadline=0.5)
            took = time.monotonic() - began
        finally:
            _StreamingServer.do_POST = original
    finally:
        server.shutdown()
    assert took < 3


def test_request_ids_skip_notifications() -> None:
    assert _request_ids(b'{"jsonrpc":"2.0","id":3,"method":"initialize"}') == {"3"}
    assert _request_ids(b'{"jsonrpc":"2.0","method":"notifications/initialized"}') == set()
    batch = b'[{"jsonrpc":"2.0","id":"a","method":"x"},{"jsonrpc":"2.0","id":2,"method":"y"}]'
    assert _request_ids(batch) == {'"a"', "2"}
    assert _request_ids(b"") == set()


def test_get_stream_is_not_opened_upstream(monkeypatch) -> None:
    proxy = McpProxy()
    wrapped = proxy.wrap({"worker": {"type": "http", "url": "http://worker.invalid/mcp"}}, "http://rt", "chat-1")
    secret, digest, actor = wrapped["worker"]["url"].rsplit("/", 3)[-3:]

    def never(*args, **kwargs):
        raise AssertionError("GET must not reach the MCP server")

    monkeypatch.setattr(mcp_proxy, "_forward", never)
    request = SimpleNamespace(method="GET", app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(proxy=proxy))))
    response = asyncio.run(proxy_mcp(request, secret, digest, actor))
    assert response.status_code == 405
    # The agent did reach the proxy, so the connect watchdog stays quiet.
    assert proxy.hit_since("chat-1", 0)


def test_forwards_have_their_own_threads() -> None:
    assert mcp_proxy._FORWARD_POOL._max_workers >= 16
