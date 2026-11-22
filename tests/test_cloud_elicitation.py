"""MCP elicitation for cloud agents (the integration's own MCP client), tool annotations, isError."""

import asyncio
import json

import pytest
from aiohttp import ClientSession, web

from custom_components.ai_workspace import approvals
from custom_components.ai_workspace.api_provider import (
    McpBundle,
    read_only_hint,
    tool_end_event,
    tool_failed,
)
from custom_components.ai_workspace.mcp_client import ELICITATION_CAPABILITY, McpHttpClient
from custom_components.ai_workspace.task_guard import is_read_tool, task_refusal, task_tool_offered


def _sse(message: dict) -> bytes:
    return f"event: message\ndata: {json.dumps(message)}\n\n".encode()


class _Server:
    """MCP Streamable HTTP server whose tool "ask" elicits and answers with what the user said."""

    def __init__(self, *, mode: str = "form", withdraw: float = 0.0) -> None:
        self.seen: list[dict] = []
        self.headers: list[dict] = []
        self.mode = mode
        self.withdraw = withdraw
        self.answers: asyncio.Queue = asyncio.Queue()
        self.url = ""
        self._runner = None

    async def handle(self, request: web.Request) -> web.StreamResponse:
        message = await request.json()
        self.seen.append(message)
        self.headers.append(dict(request.headers))
        if "method" not in message:
            # A client answer to a server request (elicitation result).
            self.answers.put_nowait(message)
            return web.Response(status=202)
        if "id" not in message:
            return web.Response(status=202)
        method = message["method"]
        if method == "initialize":
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}},
                },
                headers={"Mcp-Session-Id": "s-1"},
            )
        if method != "tools/call":
            return web.json_response({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        params = {"message": "Run ls on host?", "requestedSchema": {"type": "object", "properties": {}}}
        if self.mode == "url":
            params = {"mode": "url", "message": "Sign in", "url": "https://example.com/x", "elicitationId": "e"}
        elif self.mode == "bogus":
            params = {"mode": "bogus", "message": "?"}
        try:
            await resp.write(_sse({"jsonrpc": "2.0", "id": "el-1", "method": "elicitation/create", "params": params}))
            if self.withdraw:
                await asyncio.sleep(self.withdraw)
                note = {"requestId": "el-1", "reason": "gave up"}
                await resp.write(_sse({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": note}))
                answer = None
            else:
                answer = await self.answers.get()
            result = {"content": [{"type": "text", "text": json.dumps(answer)}]}
            await resp.write(_sse({"jsonrpc": "2.0", "id": message["id"], "result": result}))
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


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0.05)


def _answer_of(result) -> dict | None:
    return json.loads(result["content"][0]["text"])


def test_initialize_declares_elicitation_and_sends_the_protocol_version() -> None:
    async def run():
        async with _Server() as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            await client.initialize()
            await client.call("tools/list")
            return server

    server = asyncio.run(run())
    init = next(m for m in server.seen if m.get("method") == "initialize")
    assert init["params"]["protocolVersion"] == "2025-11-25"
    assert init["params"]["capabilities"]["elicitation"] == ELICITATION_CAPABILITY == {"form": {}, "url": {}}
    # After initialize every request names the negotiated version (MCP Streamable HTTP).
    assert server.headers[-1].get("MCP-Protocol-Version") == "2025-11-25"


def test_answer_goes_back_and_waiting_does_not_count_against_the_timeout() -> None:
    async def run():
        async with _Server() as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            asked: list[dict] = []

            async def on_elicit(params):
                asked.append(params)
                await asyncio.sleep(0.8)  # longer than the tool timeout
                return {"action": "accept", "content": {"note": "ok"}}

            result = await client.call_tool("ask", {}, timeout=0.3, on_elicit=on_elicit)
            return asked, result

    asked, result = asyncio.run(run())
    assert asked[0]["message"] == "Run ls on host?"
    answer = _answer_of(result)
    assert answer["id"] == "el-1"
    assert answer["result"] == {"action": "accept", "content": {"note": "ok"}}


def test_url_mode_accept_carries_no_content() -> None:
    async def run():
        async with _Server(mode="url") as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)

            async def on_elicit(params):
                assert params["url"] == "https://example.com/x"
                return {"action": "accept", "content": {"x": 1}}

            return await client.call_tool("ask", {}, timeout=2, on_elicit=on_elicit)

    assert _answer_of(asyncio.run(run()))["result"] == {"action": "accept"}


def test_without_a_user_the_server_gets_cancel() -> None:
    async def run():
        async with _Server() as server, ClientSession() as http:
            return await McpHttpClient(http, server.url).call_tool("ask", {}, timeout=2)

    assert _answer_of(asyncio.run(run()))["result"] == {"action": "cancel"}


def test_unknown_mode_is_an_invalid_params_error() -> None:
    async def run():
        async with _Server(mode="bogus") as server, ClientSession() as http:

            async def on_elicit(params):
                raise AssertionError("not asked")

            return await McpHttpClient(http, server.url).call_tool("ask", {}, timeout=2, on_elicit=on_elicit)

    answer = _answer_of(asyncio.run(run()))
    assert answer["error"]["code"] == -32602


def test_stop_declines_the_open_question_and_cancels_the_call() -> None:
    async def run():
        async with _Server() as server, ClientSession() as http:
            client = McpHttpClient(http, server.url)
            stopped = asyncio.Event()

            async def on_elicit(params):
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    stopped.set()
                    raise
                return {"action": "accept"}

            task = asyncio.ensure_future(client.call_tool("ask", {}, timeout=0.2, on_elicit=on_elicit))
            await asyncio.sleep(0.5)
            assert not task.done()  # still waiting for the user, past the tool timeout
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await _settle()
            return server, stopped.is_set()

    server, stopped = asyncio.run(run())
    assert stopped
    answers = [m for m in server.seen if m.get("id") == "el-1"]
    assert answers and answers[0]["result"] == {"action": "decline"}
    assert any(m.get("method") == "notifications/cancelled" for m in server.seen)


def test_a_withdrawn_question_closes_without_an_answer() -> None:
    async def run():
        async with _Server(withdraw=0.2) as server, ClientSession() as http:
            closed = asyncio.Event()

            async def on_elicit(params):
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    closed.set()
                    raise

            result = await McpHttpClient(http, server.url).call_tool("ask", {}, timeout=2, on_elicit=on_elicit)
            await _settle()
            return server, result, closed.is_set()

    server, result, closed = asyncio.run(run())
    assert closed
    assert _answer_of(result) is None
    assert not [m for m in server.seen if m.get("id") == "el-1"]


# --- Chat cards for cloud agents ------------------------------------------------------------------


class _Store:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def save_approval(self, item_id, session_id, user_id, kind, card, answer_key, expires_at):
        self.rows[item_id] = {
            "id": item_id,
            "session_id": session_id,
            "user_id": user_id,
            "kind": kind,
            "card": card,
            "answer_key": answer_key,
            "status": "pending",
            "created_at": "now",
            "expires_at": expires_at,
        }
        return True

    def get_approval(self, item_id):
        return self.rows.get(item_id)

    def close_approval(self, item_id, status):
        row = self.rows.get(item_id)
        if row is None or row["status"] != "pending":
            return False
        row["status"] = status
        return True


class _Bus:
    def __init__(self) -> None:
        self.fired: list = []

    def async_fire(self, name, data):
        self.fired.append((name, data))


class _Hass:
    def __init__(self) -> None:
        self.store = _Store()
        self.data = {"ai_workspace": {"store": self.store}}
        self.bus = _Bus()

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)


def _ask(hass, params, timeout=5):
    return approvals.ask(hass, session_id="chat-1", user_id="u1", server="worker", params=params, timeout=timeout)


def _shown(monkeypatch) -> list:
    shown: list = []
    monkeypatch.setattr(approvals, "publish", lambda hass, session_id, card: shown.append(card))
    return shown


def test_cloud_question_is_a_chat_card_answered_by_the_click(monkeypatch) -> None:
    shown = _shown(monkeypatch)

    async def run():
        hass = _Hass()
        task = asyncio.ensure_future(_ask(hass, {"message": "Approve?", "requestedSchema": {"type": "object"}}))
        await asyncio.sleep(0.05)
        card = shown[0]
        row = hass.store.get_approval(card["id"])
        assert row["answer_key"].startswith(approvals.LOCAL_KEY)
        assert card["kind"] == "elicitation" and card["server"] == "worker" and card["confirmation"] is True
        assert "answer_key" not in card
        status = approvals.answer_local(hass, card["id"], card, {"action": "accept", "content": {"a": 1}})
        result = await task
        return hass, status, result, card

    hass, status, result, card = asyncio.run(run())
    assert status == "answered"
    assert result == {"action": "accept", "content": {"a": 1}}
    assert hass.bus.fired[0][0] == "ai_workspace_approval"
    # The answer view closes the card; nothing else did.
    assert hass.store.get_approval(card["id"])["status"] == "pending"
    # Nobody waits any more: a second click finds the request gone.
    assert approvals.answer_local(hass, card["id"], card, {"action": "decline"}) == "gone"


def test_cloud_question_times_out_with_cancel(monkeypatch) -> None:
    shown = _shown(monkeypatch)

    async def run():
        hass = _Hass()
        result = await _ask(hass, {"message": "?"}, timeout=1)
        return hass, result

    hass, result = asyncio.run(run())
    assert result == {"action": "cancel"}
    assert shown[-1]["status"] == "timeout"
    assert hass.store.get_approval(shown[0]["id"])["status"] == "timeout"


def test_stopped_turn_ends_the_card(monkeypatch) -> None:
    shown = _shown(monkeypatch)

    async def run():
        hass = _Hass()
        task = asyncio.ensure_future(_ask(hass, {"message": "?"}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return hass

    hass = asyncio.run(run())
    assert shown[-1]["status"] == "ended"
    assert hass.store.get_approval(shown[0]["id"])["status"] == "ended"


def test_url_mode_card_shows_only_http_links(monkeypatch) -> None:
    shown = _shown(monkeypatch)
    card = approvals.local_card({"mode": "url", "message": "Sign in", "url": "https://x.example/a?b=1"}, "s", 60)
    assert card["url"] == "https://x.example/a?b=1" and card["mode"] == "url" and card["confirmation"] is True
    assert approvals.local_card({"mode": "url", "url": "javascript:alert(1)"}, "s", 60) is None
    assert approvals.link_of("https://a b") == ""

    async def run():
        return await _ask(_Hass(), {"mode": "url", "url": "file:///etc/passwd"})

    assert asyncio.run(run()) == {"action": "decline"}
    assert not shown


def test_cloud_question_without_a_chat_is_cancelled() -> None:
    async def run():
        hass = _Hass()
        return await approvals.ask(hass, session_id="", user_id="u", server="s", params={}, timeout=5)

    assert asyncio.run(run()) == {"action": "cancel"}


# --- Tool annotations and isError -----------------------------------------------------------------


def test_annotations_decide_read_only_task_tools() -> None:
    policy = {"read_only": True}
    assert is_read_tool("fancy_tool", {"readOnlyHint": True})
    assert not is_read_tool("get_state", {"readOnlyHint": False})
    assert not is_read_tool("get_state", {"readOnlyHint": True, "destructiveHint": True})
    assert is_read_tool("get_state", {}) and not is_read_tool("fancy_tool")
    assert task_refusal("fancy_tool", {}, policy, {"readOnlyHint": True}) == ""
    assert task_refusal("list_things", {}, policy, {"destructiveHint": True})
    assert task_tool_offered("fancy_tool", policy, {"readOnlyHint": True})
    # Loop protection stays, whatever the server says.
    assert not task_tool_offered("delete_automation", {"read_only": False}, {"readOnlyHint": True})


def test_read_only_hint_and_bundle_hints() -> None:
    assert read_only_hint({"readOnlyHint": True})
    assert not read_only_hint({"readOnlyHint": True, "destructiveHint": True})
    assert not read_only_hint(None) and not read_only_hint({})
    bundle = McpBundle()
    bundle.add("srv", object(), [{"name": "look", "annotations": {"readOnlyHint": True}}, {"name": "do"}])
    bundle.finish()
    assert bundle.hints("look") == {"readOnlyHint": True}
    assert bundle.hints("do") == {}


def test_is_error_marks_the_tool_step_failed() -> None:
    assert tool_failed({"isError": True, "content": []})
    assert not tool_failed({"content": []}) and not tool_failed("text")
    assert tool_end_event("t", "T", "", True)["failed"] is True
    assert "failed" not in tool_end_event("t", "T", "", False)


def test_change_history_skips_read_only_tools(monkeypatch) -> None:
    from custom_components.ai_workspace.api_provider import ApiProvider

    calls: list[str] = []

    class _Fake(McpBundle):
        async def call_tool(self, name, arguments=None, **extra):
            calls.append(name)
            return {"content": []}

    bundle = _Fake()
    bundle.add("srv", object(), [{"name": "look", "annotations": {"readOnlyHint": True}}, {"name": "write"}])
    bundle.finish()
    tracked: list[str] = []

    async def on_tool(tool, args, call):
        tracked.append(tool)
        return await call(tool, args)

    provider = ApiProvider.__new__(ApiProvider)
    provider.hass = None

    async def run():
        await provider._invoke_tool(bundle, "look", {}, on_tool)
        await provider._invoke_tool(bundle, "write", {}, on_tool)

    monkeypatch.setattr("custom_components.ai_workspace.api_provider.house_zone", lambda hass: None)
    asyncio.run(run())
    assert calls == ["look", "write"]
    assert tracked == ["write"]



def test_click_on_a_cloud_card_answers_in_home_assistant(monkeypatch) -> None:
    from homeassistant.components.http import KEY_HASS

    shown = _shown(monkeypatch)

    async def no_runtime(*args, **kwargs):
        raise AssertionError("a cloud card never goes to the Runtime")

    monkeypatch.setattr(approvals, "answer_runtime", no_runtime)

    class _User:
        id = "u1"

    class _Request(dict):
        def __init__(self, hass, body):
            super().__init__(hass_user=_User())
            self.app = {KEY_HASS: hass}
            self._body = body

        async def json(self):
            return self._body

    async def run():
        hass = _Hass()
        hass.store.get_session = lambda user_id, session_id: type("S", (), {"id": session_id})()
        task = asyncio.ensure_future(_ask(hass, {"message": "Name?", "requestedSchema": {
            "type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}))
        await asyncio.sleep(0.05)
        item = shown[0]["id"]
        view = approvals.ApprovalAnswerView()
        bad = await view.post(_Request(hass, {"action": "accept", "content": {}}), item)
        good = await view.post(_Request(hass, {"action": "accept", "content": {"name": "Ada"}}), item)
        return hass, item, bad, good, await task

    hass, item, bad, good, result = asyncio.run(run())
    assert bad.status == 400
    assert json.loads(good.text)["status"] == "answered"
    assert result == {"action": "accept", "content": {"name": "Ada"}}
    assert hass.store.get_approval(item)["status"] == "accept"
