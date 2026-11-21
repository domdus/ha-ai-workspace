"""An excerpt from another chat reaches every engine the same way, in every token mode,
is kept with the user message and comes back in the handoff after a resume or an engine switch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

http = pytest.importorskip("custom_components.ai_workspace.http")
from custom_components.ai_workspace.chat_scope import CROSS_MARK, PRIOR_EXCERPT_LEAD  # noqa: E402
from custom_components.ai_workspace.const import (  # noqa: E402
    DOMAIN,
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_LIGHT,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
)
from custom_components.ai_workspace.store import Store  # noqa: E402
from test_claude_auth_error import _Stream  # noqa: E402

TABLE = "| Zone | Dauer |\n| --- | --- |\n| Zone 1 | 3 min |\n| Zone 2 | 6 min |"


class _Runtime:
    """A Cursor, Claude or Codex agent on the Runtime."""

    def __init__(self, kind: str, mode: str = TOKEN_MODE_OFF):
        self.kind = kind
        self.token_mode = mode
        self.model = ""
        self.effort = ""
        self.api_key = ""
        self.allow_internet = False
        self.info = SimpleNamespace(available=True, label=kind, id=kind)


class _Cloud:
    kind = "api"
    allow_internet = False
    model = "m"
    info = SimpleNamespace(available=True, label="Cloud", id="cloud")

    def __init__(self):
        self.seen: list[str] = []

    async def send(self, session, message, on_agent_id, **_kw):
        self.seen.append(message)
        yield {"type": "text", "delta": "ok"}


class _Request(dict):
    headers: dict = {}
    host = "ha:8123"
    scheme = "http"
    transport = None


async def _executor(func, *args):
    return func(*args)


def _setup(tmp_path: Path, monkeypatch, providers: dict, assist: set | None = None):
    store = Store(tmp_path / "db.sqlite")
    water = store.create_session("u1", "cursor")
    store.rename_session("u1", water.id, "Bewässerung")
    store.add_message(water.id, "user", "Wie lange laufen die Zonen?")
    store.add_message(water.id, "assistant", TABLE)
    # A newer, pinned chat with a common word must not win.
    newer = store.create_session("u1", "cursor")
    store.rename_session("u1", newer.id, "Börse Tabelle")
    store.set_pinned("u1", newer.id, True)
    store.add_message(newer.id, "assistant", "| Aktie | Kurs |")
    current = store.create_session("u1", next(iter(providers)) if providers else "assist.x")
    data = {"providers": providers, "chat_jobs": set(), "locks": {}, "store": store}
    hass = SimpleNamespace(
        data={DOMAIN: data},
        async_add_executor_job=_executor,
        auth=SimpleNamespace(async_get_user=lambda uid: asyncio.sleep(0, None)),
    )
    seen: list[dict] = []

    async def fake_runtime_chat(hass_, user_id, session, message, *args, **kwargs):
        seen.append({"message": message, "handoff": kwargs.get("handoff", ""), "kind": kwargs.get("runtime_provider")})
        yield {"type": "text", "delta": "Zone 1 läuft 3 Minuten."}

    async def fake_assist(hass_, user_id, agent_id, conversation_id, text, language="", extra=""):
        seen.append({"message": text, "extra": extra, "kind": "assist"})
        yield {"type": "text", "delta": "ok"}

    async def no_activity(*_a, **_k):
        return {}

    async def no_bind(*_a, **_k):
        return None

    class _Response:
        async def prepare(self, request):
            return None

        async def write(self, chunk):
            return None

    monkeypatch.setattr(http, "_runtime_chat", fake_runtime_chat)
    monkeypatch.setattr(http, "async_assist_events", fake_assist)
    monkeypatch.setattr(http, "assist_agent_ids", lambda hass_: set(assist or ()))
    monkeypatch.setattr(http, "_activity_kwargs", no_activity)
    monkeypatch.setattr(http, "async_bind_runtime", no_bind)
    monkeypatch.setattr(http, "_runtime_headers", lambda request_: {})
    monkeypatch.setattr(http, "house_zone", lambda hass_: None)
    monkeypatch.setattr(http.web, "StreamResponse", lambda **_kw: _Response())
    settings = SimpleNamespace(change_history=False, model_switcher=False, cross_chat=False, context_window=0)
    return store, current, data, hass, settings, seen


async def _turn(hass, data, settings, store, session_id, message, body=None):
    session = store.get_session("u1", session_id)
    lock = asyncio.Lock()
    await lock.acquire()
    view = object.__new__(http.ChatView)
    task = await view._start(
        _Request(hass_user=SimpleNamespace(id="u1")),
        hass,
        data,
        settings,
        store,
        "u1",
        True,
        session,
        body or {},
        [],
        [],
        message,
        lock,
    )
    await task


@pytest.mark.parametrize("kind", ["claude", "cursor", "codex"])
@pytest.mark.parametrize("mode", [TOKEN_MODE_OFF, TOKEN_MODE_LIGHT, TOKEN_MODE_MEDIUM, TOKEN_MODE_EXTREME])
def test_every_runtime_engine_gets_the_excerpt(tmp_path, monkeypatch, kind, mode) -> None:
    store, current, data, hass, settings, seen = _setup(tmp_path, monkeypatch, {kind: _Runtime(kind, mode)})

    async def run():
        await _turn(hass, data, settings, store, current.id, "Schau in den Bewässerungschat und mach eine neue Tabelle daraus")
        # Resume: the next turn names no chat, the handoff still has the excerpt.
        await _turn(hass, data, settings, store, current.id, "Und Zone 2?")

    asyncio.run(run())
    first, second = seen
    assert first["kind"] == kind
    assert CROSS_MARK in first["message"] and "| Zone 1 | 3 min |\n" in first["message"]
    assert "| Aktie | Kurs |" not in first["message"]
    assert first["message"].index("Schau in den") < first["message"].index(CROSS_MARK)
    assert CROSS_MARK not in second["message"]
    assert PRIOR_EXCERPT_LEAD in second["handoff"] and "| Zone 2 | 6 min |" in second["handoff"]
    rows = store.list_messages(current.id)
    stored = json.loads(rows[0].events)
    assert stored[-1]["type"] == "cross_chat" and stored[-1]["chats"][0]["title"] == "Bewässerung"
    # The browser never gets the excerpt text.
    assert "text" not in http._message_dict(rows[0])["events"][-1]
    store.close()


def test_engine_switch_keeps_the_excerpt_in_the_handoff(tmp_path, monkeypatch) -> None:
    providers = {"cursor": _Runtime("cursor"), "claude": _Runtime("claude")}
    store, current, data, hass, settings, seen = _setup(tmp_path, monkeypatch, providers)

    async def run():
        await _turn(hass, data, settings, store, current.id, "Was war im Bewässerung chat?", {"agent": "cursor"})
        await _turn(hass, data, settings, store, current.id, "Mach weiter", {"agent": "claude"})

    asyncio.run(run())
    assert seen[0]["kind"] == "cursor" and CROSS_MARK in seen[0]["message"]
    assert seen[1]["kind"] == "claude"
    assert "| Zone 1 | 3 min |" in seen[1]["handoff"]
    store.close()


def test_cloud_agents_get_the_excerpt_too(tmp_path, monkeypatch) -> None:
    cloud = _Cloud()
    store, current, data, hass, settings, _seen = _setup(tmp_path, monkeypatch, {"cloud": cloud})
    asyncio.run(_turn(hass, data, settings, store, current.id, "Was war im Bewäserung chat?"))
    assert CROSS_MARK in cloud.seen[0] and "| Zone 2 | 6 min |" in cloud.seen[0]
    store.close()


def test_assist_agents_get_the_excerpt_as_extra_prompt(tmp_path, monkeypatch) -> None:
    store, current, data, hass, settings, seen = _setup(tmp_path, monkeypatch, {}, assist={"assist.x"})
    asyncio.run(_turn(hass, data, settings, store, current.id, "Was war im Bewässerung chat?"))
    assert seen[0]["kind"] == "assist"
    assert seen[0]["message"] == "Was war im Bewässerung chat?"
    assert CROSS_MARK in seen[0]["extra"] and "| Zone 1 | 3 min |" in seen[0]["extra"]
    store.close()


@pytest.mark.parametrize("kind", ["claude", "cursor", "codex"])
def test_runtime_clipping_keeps_the_excerpt_and_offers_the_chat_tools(monkeypatch, kind) -> None:
    sent = {}

    class Session:
        async def post(self, url, json=None, headers=None, timeout=None):
            sent.update(json or {})
            return _Stream([{"type": "done", "answer": "ok"}])

    async def ensure(*args, **kwargs):
        return True

    settings = SimpleNamespace(mcp_servers={}, mcp_kind="", model="", shorten_mcp_results=True, change_history=True)
    hass = SimpleNamespace(
        data={http.DOMAIN: {"runtime_url": "http://rt:8090", "settings": settings, "providers": {}}},
        config=SimpleNamespace(components=set(), internal_url="http://ha:8123", external_url=None, api=None),
    )
    monkeypatch.setattr(http, "async_get_clientsession", lambda hass_: Session())
    monkeypatch.setattr(http, "_ensure_runtime_session", ensure)
    monkeypatch.setattr(http, "_runtime_headers_for", lambda *a, **k: {})
    monkeypatch.setattr(http, "standing_chat_prompt", lambda *a, **k: "")
    monkeypatch.setattr(http, "house_zone", lambda hass_: None)
    monkeypatch.setattr(http, "issue_callback_key", lambda *a, **k: "key")
    monkeypatch.setattr(http, "for_runtime", lambda servers, *a, **k: servers)
    monkeypatch.setattr(http, "ha_hosts", lambda hass_: frozenset({"ha"}))
    import custom_components.ai_workspace.discovery as discovery
    import custom_components.ai_workspace.notes as notes

    monkeypatch.setattr(discovery, "_runtime_hass_url", lambda hass_: "http://ha:8123")
    monkeypatch.setattr(notes, "notes_update", lambda *a, **k: "")
    monkeypatch.setattr(notes, "notes_mcp_url", lambda hass_: "http://ha:8123/api/ai_workspace/notes/mcp")
    chat = SimpleNamespace(id="s1", agent_id="", provider=kind)
    note = f"{CROSS_MARK}\nRead-only excerpt from the chat \"Bewässerung\".\n\n{TABLE}"
    long_message = "y" * 3000

    async def collect():
        return [
            e
            async for e in http._runtime_chat(
                hass,
                "u1",
                chat,
                f"{long_message}\n\n{note}",
                access_token="tok",
                token_mode=TOKEN_MODE_MEDIUM,
                runtime_provider=kind,
            )
        ]

    asyncio.run(collect())
    assert note in sent["message"] and "y" * 1201 not in sent["message"]
    chats = sent["mcp"]["servers"]["chats"]
    assert chats["url"].endswith("/api/ai_workspace/chats/mcp")
    assert chats["headers"]["Authorization"] == "Bearer tok"
