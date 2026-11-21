"""The agent fallback inside a real chat turn (ChatView): handoff, capability skip, pause, promotion."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

http = pytest.importorskip("custom_components.ai_workspace.http")
from custom_components.ai_workspace import fallback  # noqa: E402
from custom_components.ai_workspace import fallback_ha  # noqa: E402
from custom_components.ai_workspace.const import DOMAIN, TOKEN_MODE_OFF  # noqa: E402
from custom_components.ai_workspace.fallback import ChatFallback, Failure, FallbackBook  # noqa: E402
from custom_components.ai_workspace.store import Store  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.now = 2_000_000_000.0

    def __call__(self) -> float:
        return self.now


def _info(agent_id: str, title: str):
    return SimpleNamespace(available=True, label=title, id=agent_id, title=title, model="")


class _Runtime:
    def __init__(self, agent_id: str, kind: str, title: str) -> None:
        self.kind = kind
        self.token_mode = TOKEN_MODE_OFF
        self.model = ""
        self.effort = ""
        self.api_key = ""
        self.allow_internet = False
        self.info = _info(agent_id, title)


class _Cloud:
    kind = "api"
    allow_internet = False
    model = "m"

    def __init__(self, agent_id: str, title: str, script) -> None:
        self.info = _info(agent_id, title)
        self.script = script
        self.seen: list[str] = []

    async def send(self, session, message, on_agent_id, **_kw):
        self.seen.append(message)
        for event in self.script:
            yield event


class _Request(dict):
    headers: dict = {}
    host = "ha:8123"
    scheme = "http"
    transport = SimpleNamespace(is_closing=lambda: False)


async def _executor(func, *args):
    return func(*args)


def _setup(tmp_path: Path, monkeypatch, providers: dict, scripts: dict, *, chain, back="new_message", enabled=True):
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("u1", chain[0])
    clock = Clock()
    book = FallbackBook(clock)
    settings = SimpleNamespace(
        change_history=False,
        model_switcher=False,
        cross_chat=False,
        context_window=0,
        fallback_enabled=enabled,
        fallback_agents=tuple(chain),
        fallback_return=back,
        cursor_api_key="",
        api_key="",
        mcp_token="",
    )
    data = {
        "providers": providers,
        "chat_jobs": set(),
        "locks": {},
        "store": store,
        "settings": settings,
        "fallback_book": book,
        "fallback_loaded": True,
    }
    hass = SimpleNamespace(
        data={DOMAIN: data},
        async_add_executor_job=_executor,
        auth=SimpleNamespace(async_get_user=lambda uid: asyncio.sleep(0, None)),
    )
    runtime_seen: list[dict] = []
    sent: list[dict] = []

    async def fake_runtime_chat(hass_, user_id, session_, message, *args, **kwargs):
        kind = kwargs.get("runtime_provider")
        runtime_seen.append({"kind": kind, "message": message, "handoff": kwargs.get("handoff", "")})
        steps = scripts[kind]
        script = steps.pop(0) if steps and isinstance(steps[0], list) else steps
        for event in script:
            yield dict(event)

    async def no_activity(*_a, **_k):
        return {}

    async def no_bind(*_a, **_k):
        return None

    class _Response:
        async def prepare(self, request):
            return None

        async def write(self, chunk):
            return None

    def capture(name, payload):
        sent.append(dict(payload))
        return b""

    monkeypatch.setattr(http, "_runtime_chat", fake_runtime_chat)
    monkeypatch.setattr(http, "assist_agent_ids", lambda hass_: set())
    monkeypatch.setattr(http, "_activity_kwargs", no_activity)
    monkeypatch.setattr(http, "async_bind_runtime", no_bind)
    monkeypatch.setattr(http, "_runtime_headers", lambda request_: {})
    monkeypatch.setattr(http, "house_zone", lambda hass_: None)
    monkeypatch.setattr(http, "_format_plan_reset", lambda hass_, epoch: "18:30")
    monkeypatch.setattr(http, "_sse", capture)
    monkeypatch.setattr(http.web, "StreamResponse", lambda **_kw: _Response())
    return SimpleNamespace(
        store=store, session=session, data=data, hass=hass, settings=settings, book=book, clock=clock,
        runtime_seen=runtime_seen, sent=sent,
    )


async def _turn(env, message, body=None):
    session = env.store.get_session("u1", env.session.id)
    lock = asyncio.Lock()
    await lock.acquire()
    view = object.__new__(http.ChatView)
    task = await view._start(
        _Request(hass_user=SimpleNamespace(id="u1")),
        env.hass,
        env.data,
        env.settings,
        env.store,
        "u1",
        True,
        session,
        {"language": "de", **(body or {})},
        [],
        [],
        message,
        lock,
    )
    await task


LIMIT = {"type": "error", "code": "claude_plan_rejected", "engine": "claude", "reset_at": 2_000_003_600, "message": ""}
TOOL_START = {"type": "tool", "name": "HassTurnOn", "phase": "start", "text": "Calling HassTurnOn...", "id": "t1",
              "detail": "{\"name\": \"Küche\"}"}
TOOL_END = {"type": "tool", "name": "tool", "phase": "end", "text": "Finished", "id": "t1", "detail": "ok"}


def _runtime_pair():
    return {"a-claude": _Runtime("a-claude", "claude", "Claude"), "a-cursor": _Runtime("a-cursor", "cursor", "Cursor")}


def test_limit_mid_turn_hands_over_with_journal(tmp_path, monkeypatch) -> None:
    scripts = {
        "claude": [TOOL_START, TOOL_END, {"type": "text", "delta": "Licht ist an. "}, LIMIT],
        "cursor": [{"type": "text", "delta": "Und fertig."}],
    }
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"])
    asyncio.run(_turn(env, "Mach das Küchenlicht an und sag Bescheid"))

    assert [item["kind"] for item in env.runtime_seen] == ["claude", "cursor"]
    handed = env.runtime_seen[1]["message"]
    assert "[Agent handoff]" in handed and "Mach das Küchenlicht an" in handed
    assert "HassTurnOn [changes something] — done" in handed and "Do NOT repeat" in handed
    assert "Licht ist an." in handed
    notices = [item for item in env.sent if item.get("type") == "fallback"]
    assert notices and notices[0]["message"] == "Claude am Limit (Reset 18:30). Cursor macht weiter."
    assert notices[0]["to"] == "a-cursor" and notices[0]["from"] == "a-claude"
    assert not any(item.get("type") == "error" for item in env.sent)
    # The browser never sees the journal details.
    assert not any("detail" in item for item in env.sent if item.get("type") == "tool")
    # The chat remembers the agent it runs on now.
    assert env.store.get_session("u1", env.session.id).provider == "a-cursor"
    assert env.book.chat(env.session.id).active == "a-cursor"
    assert env.book.health["a-claude"].until == 2_000_003_600
    reply = env.store.list_messages(env.session.id)[-1]
    assert reply.role == "assistant" and "Licht ist an." in reply.content and "Und fertig." in reply.content
    assert not any(item.get("type") == "error" for item in json.loads(reply.events))
    env.store.close()


def test_no_fallback_for_a_tool_error_or_when_off(tmp_path, monkeypatch) -> None:
    scripts = {"claude": [{"type": "error", "message": "Tool failed"}], "cursor": [{"type": "text", "delta": "x"}]}
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"])
    asyncio.run(_turn(env, "Hi"))
    assert [item["kind"] for item in env.runtime_seen] == ["claude"]
    assert any(item.get("type") == "error" for item in env.sent)
    env.store.close()

    scripts = {"claude": [LIMIT], "cursor": [{"type": "text", "delta": "x"}]}
    env = _setup(tmp_path / "off", monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"], enabled=False)
    asyncio.run(_turn(env, "Hi"))
    assert [item["kind"] for item in env.runtime_seen] == ["claude"]
    env.store.close()


def test_workspace_work_skips_chat_only_agents(tmp_path, monkeypatch) -> None:
    bash = {"type": "tool", "name": "Bash", "phase": "start", "text": "Calling Bash...", "id": "b1"}
    scripts = {"claude": [bash, {"type": "error", "message": "API Error: 529 Overloaded"}],
               "cursor": [{"type": "text", "delta": "weiter"}]}
    cloud = _Cloud("a-cloud", "OpenAI", [{"type": "text", "delta": "nope"}])
    providers = {**_runtime_pair(), "a-cloud": cloud}
    env = _setup(tmp_path, monkeypatch, providers, scripts, chain=["a-claude", "a-cloud", "a-cursor"])
    asyncio.run(_turn(env, "Räum das Repo auf"))
    assert cloud.seen == []
    assert [item["kind"] for item in env.runtime_seen] == ["claude", "cursor"]
    assert "Bash [changes something] — STARTED, RESULT UNKNOWN" in env.runtime_seen[1]["message"]
    env.store.close()


def test_chat_turn_falls_back_to_a_cloud_agent(tmp_path, monkeypatch) -> None:
    scripts = {"claude": [{"type": "error", "message": "unreachable", "connection": True}]}
    cloud = _Cloud("a-cloud", "OpenAI", [{"type": "text", "delta": "Hallo!"}])
    providers = {"a-claude": _Runtime("a-claude", "claude", "Claude"), "a-cloud": cloud}
    env = _setup(tmp_path, monkeypatch, providers, scripts, chain=["a-claude", "a-cloud"])
    asyncio.run(_turn(env, "Hallo"))
    assert len(cloud.seen) == 1 and "[Agent handoff]" in cloud.seen[0]
    notice = next(item for item in env.sent if item.get("type") == "fallback")
    assert notice["message"] == "Claude nicht erreichbar. OpenAI macht weiter."
    env.store.close()


def test_nobody_left_pauses_and_resumes(tmp_path, monkeypatch) -> None:
    scripts = {
        "claude": [LIMIT],
        "cursor": [[{"type": "error", "message": "Connection reset by peer"}], [{"type": "text", "delta": "Weiter."}]],
    }
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"])
    probes: list[str] = []

    async def probe(hass_, data_, agent):
        probes.append(agent)
        return None

    async def nap(seconds):
        env.clock.now += seconds

    monkeypatch.setattr(fallback_ha, "async_probe", probe)
    monkeypatch.setattr(http, "_pause_sleep", nap)
    asyncio.run(_turn(env, "Lange Aufgabe"))

    phases = [item.get("phase") for item in env.sent if item.get("type") == "fallback"]
    assert phases == ["switch", "paused", "resumed"]
    paused = next(item for item in env.sent if item.get("phase") == "paused")
    assert "pausiert" in paused["message"]
    # Cursor's 5 minute wait ends first: it is checked first, then goes on.
    assert probes == ["a-cursor"]
    assert [item["kind"] for item in env.runtime_seen] == ["claude", "cursor", "cursor"]
    assert "[Agent handoff]" in env.runtime_seen[2]["message"]
    assert not any(item.get("type") == "error" for item in env.sent)
    env.store.close()


def test_turn_start_skips_a_waiting_agent_and_promotes_later(tmp_path, monkeypatch) -> None:
    scripts = {"claude": [{"type": "text", "delta": "Claude hier"}], "cursor": [{"type": "text", "delta": "Cursor hier"}]}
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"])
    env.book.mark_failed("a-claude", Failure("limit", int(env.clock.now) + 600))

    async def probe(hass_, data_, agent):
        return None

    monkeypatch.setattr(fallback_ha, "async_probe", probe)
    asyncio.run(_turn(env, "Erste"))
    assert env.runtime_seen[-1]["kind"] == "cursor"
    first = [item for item in env.sent if item.get("type") == "fallback"]
    assert first[0]["phase"] == "switch" and "Reset 18:30" in first[0]["message"]

    # Before the reset: stays on Cursor even on a new message.
    env.sent.clear()
    asyncio.run(_turn(env, "Zweite", {"agent": "a-cursor"}))
    assert env.runtime_seen[-1]["kind"] == "cursor"
    assert not [item for item in env.sent if item.get("type") == "fallback"]

    # After the reset the next message goes back to Claude.
    env.clock.now += 600
    asyncio.run(_turn(env, "Dritte", {"agent": "a-cursor"}))
    assert env.runtime_seen[-1]["kind"] == "claude"
    promoted = [item for item in env.sent if item.get("type") == "fallback"]
    assert promoted[0]["phase"] == "promoted" and promoted[0]["message"] == "Zurück zu Claude."
    assert env.store.get_session("u1", env.session.id).provider == "a-claude"
    env.store.close()


def test_a_chat_moved_by_hand_is_not_promoted(tmp_path, monkeypatch) -> None:
    scripts = {"claude": [{"type": "text", "delta": "c"}], "cursor": [{"type": "text", "delta": "u"}]}
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), scripts, chain=["a-claude", "a-cursor"])
    env.book.set_chat(env.session.id, ChatFallback(active="a-claude", preferred="a-claude", fell_back=True))

    async def probe(hass_, data_, agent):
        raise AssertionError("no promotion for a hand-picked agent")

    monkeypatch.setattr(fallback_ha, "async_probe", probe)
    asyncio.run(_turn(env, "Hi", {"agent": "a-cursor"}))
    assert env.runtime_seen[-1]["kind"] == "cursor"
    assert env.book.chat(env.session.id) is None
    env.store.close()


def test_new_chats_start_on_the_first_ready_agent(tmp_path, monkeypatch) -> None:
    env = _setup(tmp_path, monkeypatch, _runtime_pair(), {}, chain=["a-claude", "a-cursor"])
    assert http._default_agent(env.hass, env.data) == "a-claude"
    env.book.mark_failed("a-claude", Failure("limit", int(env.clock.now) + 60))
    assert http._default_agent(env.hass, env.data) == "a-cursor"
    env.settings.fallback_enabled = False
    env.settings.default_agent = "a-claude"
    assert http._default_agent(env.hass, env.data) == "a-claude"
    env.store.close()


def test_fallback_texts_exist_in_every_language() -> None:
    from custom_components.ai_workspace.fallback_text import REASONS, SENTENCES
    from custom_components.ai_workspace.local_text import LANGUAGES

    assert set(REASONS) == set(LANGUAGES) == set(SENTENCES)
    for lang in LANGUAGES:
        assert set(REASONS[lang]) == set(REASONS["en"])
        assert set(SENTENCES[lang]) == set(SENTENCES["en"])
    assert fallback.KINDS == ("limit", "auth", "timeout", "connection", "overloaded")
