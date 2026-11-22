"""MCP standard through the Runtime's MCP proxy (Cursor, Claude, Codex): progress, timeout, cancellation, _meta."""

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

from app.main import with_pings  # noqa: E402
from app.mcp_config import servers_from_chat_mcp  # noqa: E402
from app.mcp_proxy import (  # noqa: E402
    CONVERSATION_META,
    DEFAULT_TOOL_TIMEOUT,
    ENGINE_TOOL_CEILING,
    TOOL_TIMEOUT_KEY,
    Flight,
    McpProxy,
    _forward,
    clamp_tool_timeout,
    with_call_meta,
)
from app.providers.codex import mcp_config as codex_mcp_config  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    seen: list = []
    mode = "progress"
    steps = 5
    pause = 0.2

    def log_message(self, *args):
        pass

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(message)
        if "id" not in message or "method" not in message:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", "sess-1")
        self.end_headers()
        token = ((message.get("params") or {}).get("_meta") or {}).get("progressToken")
        try:
            if type(self).mode == "progress":
                for step in range(1, type(self).steps + 1):
                    time.sleep(type(self).pause)
                    note = {"progressToken": token, "progress": step, "total": type(self).steps, "message": f"Step {step}"}
                    data = json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": note})
                    self.wfile.write(f"event: message\ndata: {data}\n\n".encode())
                    self.wfile.flush()
            else:
                # Silent, with pings that are not progress.
                for _ in range(60):
                    time.sleep(0.1)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            answer = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "ok"}]}})
            self.wfile.write(f"event: message\ndata: {answer}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def _serve(mode: str, steps: int = 5, pause: float = 0.2):
    handler = type("Handler", (_Handler,), {"seen": [], "mode": mode, "steps": steps, "pause": pause})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, handler, f"http://127.0.0.1:{server.server_address[1]}/mcp"


def _call(request_id=9, meta=None) -> bytes:
    params = {"name": "agent_run", "arguments": {"task": "x"}}
    if meta is not None:
        params["_meta"] = meta
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": params}).encode()


def _wait_for(check, seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not check():
        time.sleep(0.05)


def test_call_meta_adds_progress_token_and_conversation_id() -> None:
    body, progress = with_call_meta(_call(), "chat-1")
    meta = json.loads(body)["params"]["_meta"]
    assert meta["progressToken"].startswith("aiw-")
    assert meta[CONVERSATION_META] == "chat-1"
    assert progress.tokens == {meta["progressToken"]: True}
    # The agent's own token and _meta stay; its progress is passed on to it.
    body, progress = with_call_meta(_call(meta={"progressToken": 5, CONVERSATION_META: "own"}), "chat-1")
    meta = json.loads(body)["params"]["_meta"]
    assert meta == {"progressToken": 5, CONVERSATION_META: "own"}
    assert progress.tokens == {"5": False}
    # Not a tools/call: untouched.
    other = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    assert with_call_meta(other, "chat-1") == (other, None)


def test_progress_restarts_the_timeout_and_reaches_the_chat() -> None:
    server, handler, url = _serve("progress", steps=5, pause=0.2)
    try:
        body, progress = with_call_meta(_call(), "chat-1")
        notes: list = []
        progress.notify = notes.append
        flight = Flight("chat-1", body)
        # 1 s in total, never more than 0.2 s silent; the timeout is 0.6 s.
        status, headers, raw = _forward(
            url, {"Content-Type": "application/json"}, body, "POST", 5, deadline=0.6, progress=progress, flight=flight
        )
    finally:
        server.shutdown()
    assert status == 200
    assert b'"text": "ok"' in raw
    assert [note["message"] for note in notes] == ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"]
    # The proxy asked for this progress; the agent did not, so it does not get it.
    assert b"notifications/progress" not in raw
    assert not [m for m in handler.seen if m.get("method") == "notifications/cancelled"]


def test_agent_progress_is_passed_on() -> None:
    server, _handler, url = _serve("progress", steps=2, pause=0.05)
    try:
        body, progress = with_call_meta(_call(meta={"progressToken": "agent-1"}), "chat-1")
        _status, _headers, raw = _forward(url, {"Content-Type": "application/json"}, body, "POST", 5, progress=progress)
    finally:
        server.shutdown()
    assert raw.count(b"notifications/progress") == 2


def test_silent_call_times_out_and_is_cancelled_upstream() -> None:
    server, handler, url = _serve("silent")
    try:
        body, progress = with_call_meta(_call(request_id=77), "chat-1")
        flight = Flight("chat-1", body)
        began = time.monotonic()
        status, _headers, raw = _forward(
            url, {"Content-Type": "application/json"}, body, "POST", 5, deadline=0.5, progress=progress, flight=flight
        )
        took = time.monotonic() - began
        _wait_for(lambda: any(m.get("method") == "notifications/cancelled" for m in handler.seen))
    finally:
        server.shutdown()
    assert status == 200 and took < 3
    error = json.loads(raw.decode().split("data: ")[-1].strip())
    assert error["id"] == 77 and error["error"]["code"] == -32001
    cancelled = [m for m in handler.seen if m.get("method") == "notifications/cancelled"]
    assert cancelled[0]["params"] == {"requestId": 77, "reason": "timeout"}


def test_stop_cancels_open_calls_upstream() -> None:
    server, handler, url = _serve("silent")
    proxy = McpProxy()
    try:
        body, progress = with_call_meta(_call(request_id=5), "chat-1")
        flight = Flight("chat-1", body)
        proxy.board(flight)
        result: dict = {}

        def run():
            result["out"] = _forward(
                url, {"Content-Type": "application/json"}, body, "POST", 30, deadline=30, progress=progress, flight=flight
            )

        worker = threading.Thread(target=run)
        began = time.monotonic()
        worker.start()
        time.sleep(0.4)
        assert proxy.cancel_session("chat-1") == 1
        worker.join(5)
        took = time.monotonic() - began
        _wait_for(lambda: any(m.get("method") == "notifications/cancelled" for m in handler.seen))
    finally:
        server.shutdown()
    assert not worker.is_alive() and took < 5
    cancelled = [m for m in handler.seen if m.get("method") == "notifications/cancelled"]
    assert cancelled[0]["params"]["requestId"] == 5
    assert "stopped" in cancelled[0]["params"]["reason"]
    assert b"-32001" in result["out"][2]
    # Nothing else is open for that chat.
    proxy.take_off(flight)
    assert proxy.cancel_session("chat-1") == 0


def test_initialize_is_never_cancelled() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()
    assert Flight("chat-1", body).cancellable is False
    assert Flight("chat-1", _call()).cancellable is True


def test_connection_timeout_reaches_the_proxy_not_the_engines() -> None:
    proxy = McpProxy()
    servers = servers_from_chat_mcp(
        {"servers": {"worker": {"type": "http", "url": "http://w/mcp", TOOL_TIMEOUT_KEY: 1800}}}
    )
    assert servers["worker"][TOOL_TIMEOUT_KEY] == 1800
    wrapped = proxy.wrap(servers, "http://127.0.0.1:8099", "chat-1")
    assert TOOL_TIMEOUT_KEY not in wrapped["worker"]
    digest = wrapped["worker"]["url"].rsplit("/", 2)[-2]
    assert proxy.tool_timeout(digest) == 1800
    assert clamp_tool_timeout(None) == DEFAULT_TOOL_TIMEOUT
    # Codex stops calls after 60 s by default: through the proxy it gets the ceiling.
    mapped, _skipped = codex_mcp_config(wrapped)
    assert mapped["worker"]["tool_timeout_sec"] == ENGINE_TOOL_CEILING


def test_progress_listener_feeds_the_chat_stream() -> None:
    proxy = McpProxy()

    async def run():
        side: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        proxy.watch_progress("chat-1", lambda event: loop.call_soon_threadsafe(side.put_nowait, f"progress:{event['text']}"))

        async def turn():
            yield "start"
            await asyncio.sleep(0.2)
            yield "end"

        async def from_thread():
            await asyncio.sleep(0.05)
            await asyncio.to_thread(proxy.note_progress, "chat-1", {"type": "tool_progress", "text": "Step 1"})

        helper = asyncio.ensure_future(from_thread())
        out = [chunk async for chunk in with_pings(turn(), every=5, queue=side)]
        await helper
        return out

    assert asyncio.run(run()) == ["start", "progress:Step 1", "end"]
    proxy.unwatch_progress("chat-1")
    proxy.note_progress("chat-1", {"text": "nobody listens"})
