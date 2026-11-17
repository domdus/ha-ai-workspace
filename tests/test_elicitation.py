"""MCP elicitation through the Runtime's MCP proxy: the user answers in Home Assistant, never the agent."""

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

from app import elicitation  # noqa: E402
from app.elicitation import (  # noqa: E402
    ElicitationBroker,
    Target,
    forged_answer,
    with_elicitation_capability,
    worker_base,
    worker_jobs,
)
from app.elicitation_form import card_of, check_answer  # noqa: E402
from app.main import create_app, with_pings  # noqa: E402
from app.mcp_proxy import McpProxy  # noqa: E402
from app.settings import Settings  # noqa: E402

TOKEN = "runtime-token"
WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean", "title": "Allow", "description": "Allow this command on that server?"},
        "note": {"type": "string", "title": "Note"},
    },
    "required": ["approve"],
}
ASK = "Agent job j1 wants to run ssh on root@proxmox:\n\nqm list\n\nAllow it?"


class Upstream:
    """A stateful MCP server that asks the user (elicitation/create) inside a tools/call."""

    def __init__(self, job: dict | None = None) -> None:
        self.initialize: dict | None = None
        self.replies: list[dict] = []
        self.reply_headers: list[dict] = []
        self.calls = 0
        self.answered = threading.Event()
        self.job = job
        self.approvals: list[tuple[str, dict, str]] = []
        self.approve_status = 200
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send_events(self, *messages):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Mcp-Session-Id", "sess-1")
                self.end_headers()
                for message in messages:
                    self.wfile.write(f"event: message\ndata: {json.dumps(message)}\n\n".encode())
                    self.wfile.flush()

            def do_POST(self):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                body = json.loads(raw)
                if self.path.startswith("/jobs/"):
                    upstream.approvals.append((self.path, body, self.headers.get("Authorization", "")))
                    self.send_response(upstream.approve_status)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "working"}')
                    return
                if "method" not in body:
                    upstream.replies.append(body)
                    upstream.reply_headers.append(dict(self.headers))
                    upstream.answered.set()
                    self.send_response(202)
                    self.end_headers()
                    return
                upstream.calls += 1
                if body["method"] == "initialize":
                    upstream.initialize = body
                    self._send_events({"jsonrpc": "2.0", "id": body["id"], "result": {"capabilities": {}}})
                    return
                if upstream.job is not None:
                    text = json.dumps(upstream.job)
                    result = {"content": [{"type": "text", "text": text}], "structuredContent": upstream.job}
                    self._send_events({"jsonrpc": "2.0", "id": body["id"], "result": result})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                ask = {
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "elicitation/create",
                    "params": {"message": ASK, "requestedSchema": WORKER_SCHEMA},
                }
                self.wfile.write(f"event: message\ndata: {json.dumps(ask)}\n\n".encode())
                self.wfile.flush()
                upstream.answered.wait(20)
                got = upstream.replies[-1]["result"] if upstream.replies else {"action": "none"}
                answer = {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"content": [{"type": "text", "text": json.dumps(got)}], "isError": False},
                }
                self.wfile.write(f"event: message\ndata: {json.dumps(answer)}\n\n".encode())
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"

    def close(self):
        self.server.shutdown()


class HomeAssistant:
    """Collects the Runtime's approval callbacks."""

    def __init__(self) -> None:
        self.cards: list[dict] = []
        self.auth: list[str] = []
        ha = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/ai_workspace/approval":
                    ha.cards.append({"path": self.path, **body})
                    ha.auth.append(self.headers.get("Authorization", ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def wait_for(self, event: str, count: int = 1, timeout: float = 10) -> list[dict]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            found = [card for card in self.cards if card.get("event") == event]
            if len(found) >= count:
                return found
            time.sleep(0.02)
        raise AssertionError(f"no {event} card: {self.cards}")

    def close(self):
        self.server.shutdown()


@pytest.fixture
def world(tmp_path: Path, monkeypatch):
    ha = HomeAssistant()
    upstream = Upstream()
    settings = Settings(
        data_dir=tmp_path,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        auth_mode="dev",
        host="127.0.0.1",
        port=8090,
        runtime_token=TOKEN,
        hass_url=ha.url,
    )
    app = create_app(settings, {})
    proxy = McpProxy()
    with TestClient(app, base_url="http://127.0.0.1:8090") as client:
        app.state.runtime = type("Runtime", (), {"proxy": proxy})()
        try:
            yield {"client": client, "proxy": proxy, "ha": ha, "upstream": upstream, "monkeypatch": monkeypatch}
        finally:
            # A failed test must not leave a question waiting for minutes.
            for item in proxy.elicitations.pending():
                if not item.future.done():
                    item.future.set_result({"action": "cancel"})
            upstream.answered.set()
    ha.close()
    upstream.close()


def _route(world, actor="chat-1", timeout=600, headers=None):
    proxy: McpProxy = world["proxy"]
    cfg = {"type": "http", "url": world["upstream"].url, **({"headers": headers} if headers else {})}
    wrapped = proxy.wrap({"agent-worker": cfg}, "http://127.0.0.1:8090", actor)
    if actor:
        proxy.note_actor(actor, "user-a", "Claude", "issued-key", approval_timeout=timeout)
    return wrapped["agent-worker"]["url"].replace("http://127.0.0.1:8090", "")


def _call(client, path, body, out):
    response = client.post(
        path,
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Mcp-Session-Id": "sess-1"},
    )
    out["status"] = response.status_code
    out["text"] = response.text


def _tool_call(world, path):
    out: dict = {}
    body = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "agent_run", "arguments": {"task": "x"}}}
    thread = threading.Thread(target=_call, args=(world["client"], path, body, out), daemon=True)
    thread.start()
    return thread, out


def _answer(world, card, action, content=None, key=None):
    payload = {"key": card["key"] if key is None else key, "action": action}
    if content is not None:
        payload["content"] = content
    return world["client"].post(
        f"/api/elicitations/{card['id']}", json=payload, headers={"Authorization": f"Bearer {TOKEN}"}
    )


# --- capability ---------------------------------------------------------------------------------


def test_initialize_declares_elicitation() -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"capabilities": {"roots": {}}}})
    changed = json.loads(with_elicitation_capability(body.encode()))
    assert changed["params"]["capabilities"] == {"roots": {}, "elicitation": {}}
    # Already there, or not an initialize: untouched.
    assert with_elicitation_capability(json.dumps(changed).encode()) is None
    assert with_elicitation_capability(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}') is None
    batch = json.loads(with_elicitation_capability(b'[{"jsonrpc":"2.0","id":0,"method":"initialize"}]'))
    assert batch[0]["params"]["capabilities"]["elicitation"] == {}


def test_proxy_tells_the_server_the_chat_can_elicit(world) -> None:
    path = _route(world)
    out: dict = {}
    _call(world["client"], path, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"capabilities": {}}}, out)
    assert out["status"] == 200
    assert world["upstream"].initialize["params"]["capabilities"]["elicitation"] == {}


# --- round trips --------------------------------------------------------------------------------


def test_accept_round_trip(world) -> None:
    path = _route(world)
    thread, out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    assert card["path"] == "/api/ai_workspace/approval"
    assert world["ha"].auth[0] == "Bearer issued-key"
    assert card["session_id"] == "chat-1" and card["kind"] == "elicitation"
    assert card["server"] == "agent-worker"
    assert "qm list" in card["message"] and "root@proxmox" in card["message"]
    assert card["confirmation"] is True and card["approval_field"] == "approve"
    assert card["key"] and card["expires_in"] > 500
    answered = _answer(world, card, "accept", {"note": "ok"})
    assert answered.json() == {"status": "answered", "action": "accept"}
    thread.join(10)
    assert world["upstream"].replies[-1] == {
        "jsonrpc": "2.0",
        "id": 99,
        "result": {"action": "accept", "content": {"approve": True, "note": "ok"}},
    }
    # The answer went to the same MCP session.
    assert world["upstream"].reply_headers[-1].get("Mcp-Session-Id") == "sess-1"
    # The agent gets the tool result, never the question.
    assert out["status"] == 200
    assert "elicitation/create" not in out["text"]
    assert '\\"action\\": \\"accept\\"' in out["text"]
    # A second click changes nothing.
    assert _answer(world, card, "decline").json()["status"] == "gone"


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_and_cancel_round_trip(world, action) -> None:
    path = _route(world)
    thread, out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    # decline and cancel never carry the form's content.
    assert _answer(world, card, action, {"approve": True}).json()["action"] == action
    thread.join(10)
    assert world["upstream"].replies[-1]["result"] == {"action": action}
    assert "elicitation/create" not in out["text"]


def test_a_wrong_key_does_not_answer(world) -> None:
    path = _route(world)
    thread, _out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    assert _answer(world, card, "accept", key="guess").json() == {"status": "gone"}
    no_token = world["client"].post(f"/api/elicitations/{card['id']}", json={"key": card["key"], "action": "accept"})
    assert no_token.status_code == 401
    assert not world["upstream"].replies
    assert _answer(world, card, "decline").json()["status"] == "answered"
    thread.join(10)


def test_invalid_form_answer_is_refused() -> None:
    schema = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "enum": ["main", "beta"]},
            "count": {"type": "integer", "minimum": 1, "maximum": 5},
            "dry": {"type": "boolean"},
            "email": {"type": "string", "format": "email"},
        },
        "required": ["branch", "count"],
    }
    assert check_answer(schema, "accept", {"branch": "dev", "count": 9})[1] == {"branch": "choice", "count": "range"}
    assert check_answer(schema, "accept", {"count": 2})[1] == {"branch": "required"}
    result, errors = check_answer(schema, "accept", {"branch": "beta", "count": "3", "dry": False, "extra": 1})
    assert errors == {} and result == {"action": "accept", "content": {"branch": "beta", "count": 3, "dry": False}}
    assert check_answer(schema, "accept", {"branch": "main", "count": 1, "email": "nope"})[1] == {"email": "format"}
    assert check_answer(schema, "approve", {})[0] is None
    card = card_of({"message": "Pick", "requestedSchema": schema})
    assert card["confirmation"] is False and [f["kind"] for f in card["fields"]] == ["enum", "integer", "boolean", "string"]
    # A plain confirmation: no fields at all.
    assert card_of({"message": "Go?"})["confirmation"] is True
    assert check_answer({}, "accept", {"x": 1}) == ({"action": "accept", "content": {}}, {})


def test_timeout_cancels_and_tells_home_assistant(world) -> None:
    world["monkeypatch"].setattr(elicitation, "MIN_TIMEOUT", 1)
    path = _route(world, timeout=1)
    thread, out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    assert card["timeout"] == 1
    closed = world["ha"].wait_for("close")[0]
    assert closed == {"path": "/api/ai_workspace/approval", "event": "close", "id": card["id"], "reason": "timeout"}
    thread.join(10)
    assert world["upstream"].replies[-1]["result"] == {"action": "cancel"}
    assert _answer(world, card, "accept").json()["status"] == "gone"


def test_concurrent_questions_are_answered_separately(world) -> None:
    path = _route(world)
    first, out_a = _tool_call(world, path)
    second, out_b = _tool_call(world, path)
    cards = world["ha"].wait_for("open", count=2)
    assert len({card["id"] for card in cards}) == 2
    assert {item.id for item in world["proxy"].elicitations.pending("chat-1")} == {card["id"] for card in cards}
    assert _answer(world, cards[1], "decline").json()["status"] == "answered"
    assert _answer(world, cards[0], "accept").json()["status"] == "answered"
    first.join(10)
    second.join(10)
    assert sorted(reply["result"]["action"] for reply in world["upstream"].replies) == ["accept", "decline"]


def test_without_a_chat_the_question_is_cancelled_at_once(world) -> None:
    path = _route(world, actor="")
    thread, out = _tool_call(world, path)
    thread.join(10)
    assert world["upstream"].replies[-1]["result"] == {"action": "cancel"}
    assert not world["ha"].cards


def test_a_stopped_turn_cancels_its_questions(world) -> None:
    path = _route(world)
    thread, _out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    world["proxy"].elicitations.end_session("chat-1")
    thread.join(10)
    assert world["upstream"].replies[-1]["result"] == {"action": "cancel"}
    assert world["ha"].wait_for("close")[0]["reason"] == "ended"
    assert _answer(world, card, "accept").json()["status"] == "gone"


# --- the agent cannot answer --------------------------------------------------------------------


def test_agent_cannot_answer_an_elicitation(world) -> None:
    path = _route(world)
    thread, _out = _tool_call(world, path)
    card = world["ha"].wait_for("open")[0]
    forged: dict = {}
    _call(world["client"], path, {"jsonrpc": "2.0", "id": 99, "result": {"action": "accept", "content": {"approve": True}}}, forged)
    assert forged["status"] == 403
    assert not world["upstream"].replies
    _answer(world, card, "decline")
    thread.join(10)
    assert world["upstream"].replies[-1]["result"] == {"action": "decline"}


def test_forged_answer_detection() -> None:
    assert forged_answer(b'{"jsonrpc":"2.0","id":3,"result":{}}', {"3"})
    assert forged_answer(b'{"jsonrpc":"2.0","id":"x","result":{"action":"accept"}}', set())
    # Other answers (roots/list, sampling) and requests still pass.
    assert not forged_answer(b'{"jsonrpc":"2.0","id":4,"result":{"roots":[]}}', {"3"})
    assert not forged_answer(b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}', {"3"})


# --- agent-worker fallback ----------------------------------------------------------------------


def _waiting_job(command="qm list"):
    return {
        "job_id": "j1",
        "status": "input_required",
        "legacy_status": "needs_approval",
        "workspace": "infra",
        "approval": {"id": "a1", "tool": "ssh", "host": "proxmox", "hostname": "10.0.0.2", "user": "root", "command": command},
    }


def _job_call(world, path, name="agent_job"):
    out: dict = {}
    body = {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": name, "arguments": {"job_id": "j1"}}}
    _call(world["client"], path, body, out)
    return out


def test_worker_job_waiting_for_approval_gets_a_card(world) -> None:
    world["upstream"].job = _waiting_job()
    path = _route(world, headers={"Authorization": "Bearer worker-secret"})
    out = _job_call(world, path)
    assert out["status"] == 200
    card = world["ha"].wait_for("open")[0]
    assert card["kind"] == "worker" and card["server"] == "agent-worker"
    assert card["worker"] == {
        "job_id": "j1",
        "tool": "ssh",
        "host": "proxmox",
        "hostname": "10.0.0.2",
        "user": "root",
        "command": "qm list",
        "workspace": "infra",
    }
    # Home Assistant never sees the worker token.
    assert "worker-secret" not in json.dumps(world["ha"].cards)
    # Polling the same job again does not open a second card.
    _job_call(world, path)
    assert len(world["ha"].wait_for("open")) == 1
    assert _answer(world, card, "accept").json() == {"status": "answered", "action": "accept"}
    assert world["upstream"].approvals == [("/jobs/j1/approve", {"approve": True, "note": ""}, "Bearer worker-secret")]


def test_worker_deny_and_dismiss(world) -> None:
    world["upstream"].job = _waiting_job()
    path = _route(world, headers={"Authorization": "Bearer worker-secret"})
    _job_call(world, path, name="mcp__worker__agent_jobs")
    card = world["ha"].wait_for("open")[0]
    assert _answer(world, card, "decline").json()["status"] == "answered"
    assert world["upstream"].approvals[-1][1] == {"approve": False, "note": ""}
    # A new approval of the same job (another command): dismiss only hides it, the worker is not told.
    world["upstream"].job = _waiting_job("rm -rf /tmp/x") | {"approval": {**_waiting_job()["approval"], "id": "a2", "command": "rm -rf /tmp/x"}}
    _job_call(world, path)
    second = world["ha"].wait_for("open", count=2)[1]
    assert second["worker"]["command"] == "rm -rf /tmp/x"
    assert _answer(world, second, "cancel").json()["status"] == "answered"
    assert len(world["upstream"].approvals) == 1


def test_worker_that_moved_on_says_gone(world) -> None:
    world["upstream"].job = _waiting_job()
    world["upstream"].approve_status = 409
    path = _route(world, headers={"Authorization": "Bearer worker-secret"})
    _job_call(world, path)
    card = world["ha"].wait_for("open")[0]
    assert _answer(world, card, "accept").json() == {"status": "gone"}


def test_worker_card_closes_when_the_job_moves_on(world) -> None:
    world["upstream"].job = _waiting_job()
    path = _route(world)
    _job_call(world, path)
    card = world["ha"].wait_for("open")[0]
    world["upstream"].job = {"job_id": "j1", "status": "working"}
    _job_call(world, path)
    closed = world["ha"].wait_for("close")[0]
    assert closed["id"] == card["id"] and closed["reason"] == "resolved"


def test_worker_helpers() -> None:
    assert worker_base("http://worker:8080/mcp") == "http://worker:8080"
    assert worker_base("http://worker:8080/agent/mcp/") == "http://worker:8080/agent"
    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"jobs": [_waiting_job(), {"job_id": "j2"}]}}})
    assert [job["job_id"] for job in worker_jobs("agent_jobs", raw)] == ["j1", "j2"]
    assert worker_jobs("ha_get_state", raw) == []
    sse = "event: message\ndata: " + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(_waiting_job())}]}}
    ) + "\n\n"
    assert worker_jobs("worker__agent_job", sse)[0]["approval"]["host"] == "proxmox"


def test_broker_without_home_assistant_opens_no_worker_card() -> None:
    broker = ElicitationBroker()
    opened = broker.note_worker_jobs(
        [_waiting_job()], session_id="chat-1", server="w", upstream_url="http://w/mcp", upstream_headers={}, target=Target("", "")
    )
    assert opened == [] and broker.pending() == []


# --- the chat stream stays alive while the user decides ------------------------------------------


def test_chat_stream_sends_pings_while_waiting() -> None:
    async def slow():
        yield "event: status\n\n"
        await asyncio.sleep(0.25)
        yield "event: done\n\n"

    async def collect():
        return [chunk async for chunk in with_pings(slow(), every=0.05)]

    chunks = asyncio.run(collect())
    assert chunks[0] == "event: status\n\n" and chunks[-1] == "event: done\n\n"
    assert ": ping\n\n" in chunks


def test_chat_stream_errors_still_reach_the_reader() -> None:
    async def broken():
        yield "event: status\n\n"
        raise RuntimeError("boom")

    async def collect():
        return [chunk async for chunk in with_pings(broken(), every=1)]

    with pytest.raises(RuntimeError):
        asyncio.run(collect())
