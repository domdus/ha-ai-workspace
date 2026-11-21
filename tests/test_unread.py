"""Unread agent replies: kept per user on the server, so the dot is the same on every device."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.ai_workspace.store import Store

http = pytest.importorskip("custom_components.ai_workspace.http")


def test_a_reply_is_unread_until_the_chat_is_read(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    chat = store.create_session("u1", "cursor")
    assert store.get_session("u1", chat.id).unread is False
    store.add_message(chat.id, "user", "Hallo")
    # The user's own message is never unread.
    assert store.get_session("u1", chat.id).unread is False
    reply = store.add_message(chat.id, "assistant", "Hi")
    assert store.get_session("u1", chat.id).unread is True
    assert [item.unread for item in store.list_sessions("u1")] == [True]
    assert [item.unread for item in store.list_sessions("u1", "hallo")] == [True]
    assert store.unread_ids("u1") == [chat.id]
    store.mark_read("u1", chat.id, reply.id)
    assert store.get_session("u1", chat.id).unread is False
    later = store.add_message(chat.id, "assistant", "Noch was")
    assert store.get_session("u1", chat.id).unread is True
    # Read up to an older message does not move the mark back or clear the newer reply.
    store.mark_read("u1", chat.id, reply.id)
    assert store.get_session("u1", chat.id).unread is True
    store.mark_read("u1", chat.id)
    assert store.get_session("u1", chat.id).read_id == later.id
    assert store.get_session("u1", chat.id).unread is False
    store.close()


def test_read_marks_belong_to_the_user(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    chat = store.create_session("u1", "cursor")
    store.add_message(chat.id, "assistant", "Hi")
    assert store.mark_read("u2", chat.id) is None
    assert store.get_session("u1", chat.id).unread is True
    store.close()


def test_chats_from_before_the_update_count_as_read(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, provider TEXT NOT NULL,
            title TEXT NOT NULL, agent_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, events TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL);
        INSERT INTO sessions VALUES ('old', 'u1', 'cursor', 'Alt', NULL, '2026-01-01', '2026-01-01');
        INSERT INTO messages (session_id, role, content, created_at) VALUES ('old', 'user', 'Frage', '2026-01-01');
        INSERT INTO messages (session_id, role, content, created_at) VALUES ('old', 'assistant', 'Antwort', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.get_session("u1", "old").unread is False
    store.add_message("old", "assistant", "Neu")
    assert store.get_session("u1", "old").unread is True
    store.close()
    # Opening the database again does not reset the marks.
    store = Store(path)
    assert store.get_session("u1", "old").unread is True
    store.close()


def _view_env(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "db.sqlite")

    async def executor(func, *args):
        return func(*args)

    hass = SimpleNamespace(data={http.DOMAIN: {"store": store, "locks": {}}}, async_add_executor_job=executor)
    monkeypatch.setattr(http, "_hass", lambda request: hass)
    monkeypatch.setattr(http, "_user_id", lambda request: "u1")
    return store, hass


def test_sessions_list_has_unread_and_pending(tmp_path: Path, monkeypatch) -> None:
    store, hass = _view_env(tmp_path, monkeypatch)
    chat = store.create_session("u1", "cursor")
    store.add_message(chat.id, "assistant", "Hi")
    busy = asyncio.Lock()

    async def run():
        await busy.acquire()
        hass.data[http.DOMAIN]["locks"][chat.id] = busy
        view = object.__new__(http.SessionsView)
        response = await view.get(SimpleNamespace(query={}))
        return json.loads(response.body)

    rows = asyncio.run(run())
    assert rows[0]["unread"] is True and rows[0]["pending"] is True
    store.close()


def test_patch_read_marks_the_chat_read(tmp_path: Path, monkeypatch) -> None:
    store, _hass = _view_env(tmp_path, monkeypatch)
    chat = store.create_session("u1", "cursor")
    reply = store.add_message(chat.id, "assistant", "Hi")

    async def body(request):
        return {"read": reply.id}

    monkeypatch.setattr(http, "_json_body", body)

    async def run():
        view = object.__new__(http.SessionView)
        response = await view.patch(SimpleNamespace(), chat.id)
        return json.loads(response.body)

    assert asyncio.run(run())["unread"] is False
    assert store.get_session("u1", chat.id).unread is False
    store.close()


def test_api_while_starting_answers_503_with_retry_after() -> None:
    hass = SimpleNamespace(data={})
    with pytest.raises(http.web.HTTPServiceUnavailable) as caught:
        http._runtime(hass)
    assert caught.value.headers["Retry-After"] == "5"
