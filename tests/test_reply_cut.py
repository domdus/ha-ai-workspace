"""A saved setting waits for running chat replies; a reply that is still cut off is marked as such."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

aiw = pytest.importorskip("custom_components.ai_workspace")
from custom_components.ai_workspace import http  # noqa: E402
from custom_components.ai_workspace.const import DOMAIN  # noqa: E402
from custom_components.ai_workspace.store import Store  # noqa: E402


# --- the reload waits ---------------------------------------------------------------------------


def _hass_with(data: dict, reloads: list):
    async def reload(entry_id):
        reloads.append(entry_id)

    return SimpleNamespace(data={DOMAIN: data}, config_entries=SimpleNamespace(async_reload=reload))


def test_reload_waits_for_a_running_reply() -> None:
    async def run():
        reply_done = asyncio.Event()
        job = asyncio.create_task(reply_done.wait())
        data = {"chat_jobs": {job}}
        reloads: list = []
        hass = _hass_with(data, reloads)
        entry = SimpleNamespace(entry_id="e1")
        first = asyncio.create_task(aiw._reload(hass, entry))
        # A second save while waiting does not add a second reload.
        second = asyncio.create_task(aiw._reload(hass, entry))
        await asyncio.sleep(0.05)
        assert reloads == [] and second.done()
        reply_done.set()
        await first
        assert reloads == ["e1"]

    asyncio.run(run())


def test_reload_runs_at_once_without_replies_and_after_the_limit() -> None:
    async def run():
        reloads: list = []
        await aiw._reload(_hass_with({"chat_jobs": set()}, reloads), SimpleNamespace(entry_id="e1"))
        assert reloads == ["e1"]
        stuck = asyncio.create_task(asyncio.Event().wait())
        await asyncio.wait_for(aiw.wait_for_replies({"chat_jobs": {stuck}}, limit=0.05), timeout=2)
        assert not stuck.done()
        stuck.cancel()

    asyncio.run(run())


def test_reload_is_skipped_when_the_entry_was_reloaded_meanwhile() -> None:
    async def run():
        reply_done = asyncio.Event()
        job = asyncio.create_task(reply_done.wait())
        data = {"chat_jobs": {job}}
        reloads: list = []
        hass = _hass_with(data, reloads)
        waiting = asyncio.create_task(aiw._reload(hass, SimpleNamespace(entry_id="e1")))
        await asyncio.sleep(0.02)
        hass.data[DOMAIN] = {"chat_jobs": set()}
        reply_done.set()
        await waiting
        assert reloads == []

    asyncio.run(run())


# --- a reply cut off in the middle --------------------------------------------------------------


class _Provider:
    kind = "api"
    allow_internet = False
    check_house = True
    model = "m"
    info = SimpleNamespace(available=True, label="Test")

    def __init__(self, started: asyncio.Event):
        self.started = started

    async def send(self, session, message, on_agent_id, **_kw):
        yield {"type": "tool", "name": "GetLiveContext", "phase": "end", "text": "Done"}
        yield {"type": "text", "delta": "Half an answer"}
        self.started.set()
        await asyncio.Event().wait()


class _Request(dict):
    headers: dict = {}
    host = "ha:8123"
    scheme = "http"
    transport = None


async def _executor(func, *args):
    return func(*args)


def test_a_cut_off_reply_is_saved_with_a_marker(tmp_path: Path, monkeypatch) -> None:
    async def run():
        store = Store(tmp_path / "db.sqlite")
        session = store.create_session("u1", "agent1")
        started = asyncio.Event()
        provider = _Provider(started)
        data = {"providers": {"agent1": provider}, "chat_jobs": set()}
        hass = SimpleNamespace(
            data={DOMAIN: data},
            async_add_executor_job=_executor,
            auth=SimpleNamespace(async_get_user=lambda uid: asyncio.sleep(0, None)),
        )
        settings = SimpleNamespace(change_history=False, model_switcher=False, cross_chat=False, context_window=0)
        monkeypatch.setattr(http, "assist_agent_ids", lambda hass_: set())

        async def no_activity(*_a, **_k):
            return {}

        monkeypatch.setattr(http, "_activity_kwargs", no_activity)
        monkeypatch.setattr(http, "_runtime_headers", lambda request_: {})

        class _Response:
            async def prepare(self, request):
                return None

            async def write(self, chunk):
                return None

        monkeypatch.setattr(http.web, "StreamResponse", lambda **_kw: _Response())
        request = _Request(hass_user=SimpleNamespace(id="u1"))
        lock = asyncio.Lock()
        await lock.acquire()
        view = object.__new__(http.ChatView)
        task = await view._start(
            request, hass, data, settings, store, "u1", True, session, {}, [], [], "How is the house?", lock
        )
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.sleep(0.05)
        # What a reload does to running replies.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        rows = store.list_messages(session.id)
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[-1].content == "Half an answer"
        events = json.loads(rows[-1].events)
        assert events[-1] == {"type": "interrupted"}
        assert [item.get("name") for item in events[:-1]] == ["GetLiveContext"]
        store.close()

    asyncio.run(run())


def test_the_chat_marks_saved_and_live_cut_off_replies() -> None:
    www = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "www"
    chat = (www / "chat.js").read_text(encoding="utf-8")
    assert 'event.type === "interrupted")) markReplyCut(bubble)' in chat
    assert 'event.type !== "interrupted"' in chat
    assert "markReplyCut(assistant);" in chat
    i18n = (www / "i18n.js").read_text(encoding="utf-8")
    assert i18n.count("reply_cut:") == i18n.count("reply_lost:") == 15
