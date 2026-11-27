"""MCP standard on tools/call from Home Assistant (API agents): progress, timeout, cancellation, _meta."""

import asyncio
import json
import time

from aiohttp import ClientSession, web

from custom_components.ai_workspace import api_provider
from custom_components.ai_workspace.api_provider import McpBundle, McpServer, progress_text
from custom_components.ai_workspace.const import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_MAX_SECONDS,
    TOOL_TIMEOUT_MIN_SECONDS,
    tool_timeout_seconds,
)
from custom_components.ai_workspace.live_turn import LiveTurn
from custom_components.ai_workspace.mcp_client import CONVERSATION_META, McpHttpClient, McpTimeout
from custom_components.ai_workspace.mcp_config import mcp_servers_from_saved


def _sse(message: dict) -> bytes:
    return f"event: message\ndata: {json.dumps(message)}\n\n".encode()


class _Server:
    """A small MCP Streamable HTTP server. Tools: work (progress, then answer), silent, quick."""

    def __init__(self, *, steps: int = 4, pause: float = 0.2, silent: float = 3.0) -> None:
        self.seen: list[dict] = []
        self.steps = steps
        self.pause = pause
        self.silent = silent
        self.url = ""
        self._runner = None

    async def handle(self, request: web.Request) -> web.StreamResponse:
        message = await request.json()
        self.seen.append(message)
        if "id" not in message or "method" not in message:
            return web.Response(status=202)
        method = message["method"]
        if method == "tools/list":
            cursor = (message.get("params") or {}).get("cursor")
            if not cursor:
                return web.json_response(
                    {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [{"name": "a"}], "nextCursor": "p2"}}
                )
            return web.json_response({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [{"name": "b"}]}})
        if method != "tools/call":
            return web.json_response({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        params = message.get("params") or {}
        token = (params.get("_meta") or {}).get("progressToken")
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        try:
            if params.get("name") == "silent":
                await asyncio.sleep(self.silent)
            elif params.get("name") == "work":
                # A server request in the stream: the client answers ping itself.
                await resp.write(_sse({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"}))
                for step in range(1, self.steps + 1):
                    await asyncio.sleep(self.pause)
                    note = {"progressToken": token, "progress": step, "total": self.steps, "message": f"Step {step}"}
                    await resp.write(_sse({"jsonrpc": "2.0", "method": "notifications/progress", "params": note}))
            answer = {"content": [{"type": "text", "text": "done"}]}
            await resp.write(_sse({"jsonrpc": "2.0", "id": message["id"], "result": answer}))
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        return resp

    async def __aenter__(self) -> "_Server":
        app = web.Application()
        app.router.add_post("/mcp", self.handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/mcp"
        return self

    async def __aexit__(self, *exc) -> None:
        await self._runner.cleanup()

    def cancelled(self) -> list[dict]:
        return [m for m in self.seen if m.get("method") == "notifications/cancelled"]


async def _settle() -> None:
    # Background sends (cancel notification, ping answer) get a moment.
    for _ in range(20):
        await asyncio.sleep(0.05)


def test_tools_call_sends_progress_token_and_conversation_id() -> None:
    async def run():
        async with _Server(steps=3, pause=0.05) as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            seen: list[dict] = []
            result = await client.call_tool(
                "work", {"x": 1}, timeout=5, on_progress=seen.append, conversation_id="chat-42"
            )
            await _settle()
            return server, result, seen

    server, result, seen = asyncio.run(run())
    call = next(m for m in server.seen if m.get("method") == "tools/call")
    meta = call["params"]["_meta"]
    assert meta["progressToken"].startswith("aiw-")
    assert meta[CONVERSATION_META] == "chat-42"
    assert call["params"]["arguments"] == {"x": 1}
    assert result["content"][0]["text"] == "done"
    assert [item["message"] for item in seen] == ["Step 1", "Step 2", "Step 3"]
    # The server's ping got its answer.
    assert any(m.get("id") == "srv-1" and m.get("result") == {} for m in server.seen)


def test_progress_restarts_the_timeout() -> None:
    async def run():
        # 5 steps of 0.25 s: 1.25 s in total, never more than 0.25 s silent.
        async with _Server(steps=5, pause=0.25) as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            return await client.call_tool("work", {}, timeout=0.6)

    assert asyncio.run(run())["content"][0]["text"] == "done"


def test_silent_call_times_out_and_is_cancelled() -> None:
    async def run():
        async with _Server(silent=3.0) as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            began = time.monotonic()
            try:
                await client.call_tool("silent", {}, timeout=0.5)
            except McpTimeout as exc:
                error = exc
            took = time.monotonic() - began
            await _settle()
            return server, error, took

    server, error, took = asyncio.run(run())
    assert "did not answer within" in str(error)
    assert took < 2
    call = next(m for m in server.seen if m.get("method") == "tools/call")
    cancelled = server.cancelled()
    assert cancelled and cancelled[0]["params"]["requestId"] == call["id"]
    assert cancelled[0]["params"]["reason"] == "timeout"


def test_stopping_the_chat_cancels_the_call() -> None:
    async def run():
        async with _Server(silent=3.0) as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            task = asyncio.ensure_future(client.call_tool("silent", {}, timeout=30))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await _settle()
            return server

    server = asyncio.run(run())
    call = next(m for m in server.seen if m.get("method") == "tools/call")
    cancelled = server.cancelled()
    assert cancelled and cancelled[0]["params"]["requestId"] == call["id"]
    assert "stopped" in cancelled[0]["params"]["reason"]


def test_tools_list_follows_next_cursor() -> None:
    async def run():
        async with _Server() as server, ClientSession() as http:
            return await McpHttpClient(http, server.url).list_tools()

    assert [tool["name"] for tool in asyncio.run(run())] == ["a", "b"]


def test_tool_timeout_setting() -> None:
    assert tool_timeout_seconds(None) == DEFAULT_TOOL_TIMEOUT_SECONDS
    assert tool_timeout_seconds("") == DEFAULT_TOOL_TIMEOUT_SECONDS
    assert tool_timeout_seconds(1) == TOOL_TIMEOUT_MIN_SECONDS
    assert tool_timeout_seconds(99999) == TOOL_TIMEOUT_MAX_SECONDS
    assert tool_timeout_seconds(900.0) == 900
    servers = mcp_servers_from_saved(
        "http://ha.local/mcp", "", [{"name": "worker", "url": "http://w/mcp", "timeout": 1800}], 300
    )
    assert servers["mcp"]["tool_timeout_sec"] == 300
    assert servers["worker"]["tool_timeout_sec"] == 1800
    # No setting saved yet: nothing in the server config, the default applies.
    assert "tool_timeout_sec" not in mcp_servers_from_saved("http://ha.local/mcp", "", [])["mcp"]


def test_bundle_passes_progress_only_to_mcp_connections() -> None:
    calls: list[tuple] = []

    class Local:
        async def call_tool(self, name, args):
            calls.append(("local", name))
            return "ok"

    server = McpServer(None, "custom", "http://x/mcp", {})
    server.tool_timeout = 900

    class Client(McpHttpClient):
        def __init__(self):
            self.tools_changed = False

        async def call_tool(self, name, arguments=None, **options):
            calls.append(("mcp", name, options))
            return "ok"

    server._client = Client()
    bundle = McpBundle()
    bundle.add("local", Local(), [{"name": "list_chats"}])
    bundle.add("worker", server, [{"name": "agent_run"}])
    bundle.finish()

    async def run():
        await bundle.call_tool("list_chats", {}, on_progress=print, conversation_id="c")
        await bundle.call_tool("agent_run", {}, on_progress=print, conversation_id="c")

    asyncio.run(run())
    assert calls[0] == ("local", "list_chats")
    assert calls[1][0] == "mcp"
    assert calls[1][2]["timeout"] == 900
    assert calls[1][2]["conversation_id"] == "c"


def test_api_agent_shows_progress_live() -> None:
    class Bundle(McpBundle):
        async def call_tool(self, name, arguments=None, **extra):
            assert extra["conversation_id"] == "chat-7"
            for step in (1, 2):
                extra["on_progress"]({"progressToken": "t", "progress": step, "total": 2, "message": f"Building {step}"})
                await asyncio.sleep(0.01)
            return {"content": [{"type": "text", "text": "built"}]}

    bundle = Bundle()

    async def run():
        provider = api_provider.ApiProvider.__new__(api_provider.ApiProvider)
        provider.hass = None
        api_provider._CONVERSATION.set("chat-7")
        outcome: dict = {}
        steps = [step async for step in provider._tool_steps(bundle, "agent_run", {}, None, outcome)]
        return steps, outcome

    steps, outcome = asyncio.run(run())
    assert [step["text"] for step in steps] == ["Building 1", "Building 2"]
    assert all(step["type"] == "tool_progress" and step["name"] == "agent_run" for step in steps)
    assert outcome["result"]["content"][0]["text"] == "built"


def test_progress_text() -> None:
    assert progress_text({"message": "Cloning repo"}) == "Cloning repo"
    assert progress_text({"progress": 3, "total": 10}) == "3/10"
    assert progress_text({"progress": 3}) == ""


def test_live_turn_keeps_only_the_newest_progress() -> None:
    turn = LiveTurn()
    turn.publish({"type": "tool", "name": "agent_run", "phase": "start", "text": "Calling agent_run..."})
    for step in range(5):
        turn.publish({"type": "tool_progress", "name": "agent_run", "text": f"Step {step}"})
    assert [event.get("text") for event in turn.events] == ["Calling agent_run...", "Step 4"]
