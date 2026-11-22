"""MCP servers hear Home Assistant's language (Accept-Language), so server-made texts can be translated.

Approval prompts ("Agent job … wants to run … Allow it?") and elicitation field titles come from the
MCP server; the chat card cannot translate them. Both paths send the header: the integration's own MCP
client (API agents) and the Runtime's MCP proxy (Cursor, Claude, Codex).
"""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai_workspace"))

from app import mcp_config as runtime_config  # noqa: E402
from app.mcp_proxy import McpProxy, proxy_mcp  # noqa: E402


# ---- Runtime --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "header"),
    [("de", "de, en;q=0.5"), ("zh-Hans", "zh-Hans, en;q=0.5"), ("de_CH", "de-CH, en;q=0.5"), ("en", "en"), ("", ""), ("x;y", "")],
)
def test_runtime_accept_language_value(language, header) -> None:
    assert runtime_config.accept_language(language) == header


def test_runtime_adds_the_header_to_http_servers_only() -> None:
    servers = runtime_config.servers_from_chat_mcp(
        {
            "servers": {
                "worker": {"type": "http", "url": "http://w/mcp", "headers": {"Authorization": "Bearer x"}},
                "own": {"type": "http", "url": "http://o/mcp", "headers": {"accept-language": "fr"}},
            },
            "language": "de",
        }
    )
    servers["tool"] = {"type": "stdio", "command": "x"}
    out = runtime_config.servers_with_language(servers, "de")
    assert out["worker"]["headers"] == {"Authorization": "Bearer x", "Accept-Language": "de, en;q=0.5"}
    # A connection that sets its own language keeps it.
    assert out["own"]["headers"] == {"accept-language": "fr"}
    assert "headers" not in out["tool"]
    # The caller's dicts stay as they were.
    assert "Accept-Language" not in servers["worker"]["headers"]
    assert runtime_config.servers_with_language(servers, "") is servers


def test_every_runtime_engine_sends_the_language() -> None:
    for engine in ("claude", "cursor", "codex"):
        source = (ROOT / "ai_workspace" / "app" / "providers" / f"{engine}.py").read_text(encoding="utf-8")
        assert 'servers_with_language(mcp_servers, str((mcp or {}).get("language") or ""))' in source, engine


def test_chat_request_carries_the_language() -> None:
    from app.main import ChatRequest

    body = ChatRequest(message="hi", mcp={"servers": {}, "language": "de"})
    assert body.mcp.model_dump()["language"] == "de"


class _Recorder(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(dict(self.headers.items()))
        data = json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": {}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_runtime_proxy_sends_accept_language_upstream() -> None:
    handler = type("Recorder", (_Recorder,), {"seen": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/mcp"
        servers = runtime_config.servers_with_language(
            runtime_config.servers_from_chat_mcp({"servers": {"worker": {"type": "http", "url": url}}}), "de"
        )
        proxy = McpProxy()
        wrapped = proxy.wrap(servers, "http://rt", "chat-1")
        # The engine never sees the header: it only knows the proxy route.
        assert "headers" not in wrapped["worker"]
        secret, digest, actor = wrapped["worker"]["url"].rsplit("/", 3)[-3:]
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode()

        async def read_body():
            return body

        request = SimpleNamespace(
            method="POST",
            # An engine's own Accept-Language does not replace Home Assistant's.
            headers={"content-type": "application/json", "accept-language": "*"},
            body=read_body,
            app=SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(proxy=proxy))),
        )
        response = asyncio.run(proxy_mcp(request, secret, digest, actor))
        assert response.status_code == 200
        sent = {key.lower(): value for key, value in handler.seen[-1].items()}
        assert sent["accept-language"] == "de, en;q=0.5"
    finally:
        server.shutdown()


# ---- Integration ----------------------------------------------------------------------------------

mcp_client = pytest.importorskip("custom_components.ai_workspace.mcp_client")


@pytest.mark.parametrize(
    ("language", "header"),
    [("de", "de, en;q=0.5"), ("fr", "fr, en;q=0.5"), ("zh-Hant", "zh-Hant, en;q=0.5"), ("en", "en"), ("", "")],
)
def test_integration_accept_language_value(language, header) -> None:
    assert mcp_client.accept_language(language) == header
    # Integration and Runtime build the same header.
    assert runtime_config.accept_language(language) == header


def test_integration_client_sends_accept_language() -> None:
    headers = mcp_client.with_accept_language({"Authorization": "Bearer x"}, "de")
    client = mcp_client.McpHttpClient(None, "http://mcp.invalid/api/mcp", headers)
    sent = client._request_headers()
    assert sent["Accept-Language"] == "de, en;q=0.5"
    assert sent["Authorization"] == "Bearer x"
    assert mcp_client.with_accept_language({"Accept-Language": "fr"}, "de") == {"Accept-Language": "fr"}


def test_integration_mcp_connections_get_ha_language(monkeypatch) -> None:
    api_provider = pytest.importorskip("custom_components.ai_workspace.api_provider")
    opened = []

    async def fake_open(self):
        opened.append(dict(self._headers))

    monkeypatch.setattr(api_provider.McpServer, "open", fake_open)
    hass = SimpleNamespace(config=SimpleNamespace(language="de"), data={})
    server = asyncio.run(api_provider.async_mcp_server(hass, None, "custom", "http://mcp.invalid/mcp", {"Authorization": "Bearer x"}))
    assert opened == [{"Authorization": "Bearer x", "Accept-Language": "de, en;q=0.5"}]
    assert server._headers["Accept-Language"] == "de, en;q=0.5"


def test_integration_sends_its_language_to_the_runtime(monkeypatch) -> None:
    http = pytest.importorskip("custom_components.ai_workspace.http")
    settings = SimpleNamespace(mcp_servers={}, mcp_kind="", model="", shorten_mcp_results=True, change_history=True)
    monkeypatch.setattr(http, "_runtime", lambda hass: {"settings": settings, "runtime_url": "http://rt"})
    monkeypatch.setattr(http, "with_mcp_auth", lambda servers, **kwargs: servers)
    monkeypatch.setattr(http, "for_runtime", lambda servers, *args: servers)
    monkeypatch.setattr(http, "ha_hosts", lambda hass: set())
    from custom_components.ai_workspace import chat_tools, discovery

    monkeypatch.setattr(chat_tools, "mcp_server_config", lambda hass: {"type": "http", "url": "http://ha/chats"})
    monkeypatch.setattr(discovery, "_runtime_hass_url", lambda hass: "http://ha")
    hass = SimpleNamespace(config=SimpleNamespace(language="de", components=set()), data={})
    extra = http._runtime_agent_overrides(hass, access_token="t", admin=True)
    assert extra["mcp"]["language"] == "de"
