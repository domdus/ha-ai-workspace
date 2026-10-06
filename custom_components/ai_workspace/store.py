from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    id: str
    user_id: str
    provider: str
    title: str
    agent_id: str | None
    created_at: str
    updated_at: str
    pinned: bool = False


@dataclass
class ChatMessage:
    id: int
    session_id: str
    role: str
    content: str
    events: str
    created_at: str


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                title TEXT NOT NULL,
                agent_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                events TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            """
        )
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        if "pinned" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_session(self, user_id: str, provider: str, session_id: str | None = None) -> Session:
        user_id = _text(user_id)
        session_id = _text(session_id) or None
        if session_id:
            existing = self.get_session(user_id, session_id)
            if existing is not None:
                return existing
        now = _now()
        session = Session(
            id=session_id or uuid.uuid4().hex,
            user_id=user_id,
            provider=provider,
            title="New Chat",
            agent_id=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (id, user_id, provider, title, agent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.user_id,
                    session.provider,
                    session.title,
                    session.agent_id,
                    session.created_at,
                    session.updated_at,
                ),
            )
            self._conn.commit()
        return session

    def list_sessions(self, user_id: str) -> list[Session]:
        user_id = _text(user_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY pinned DESC, updated_at DESC",
                (user_id,),
            ).fetchall()
        return [_session(row) for row in rows]

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        user_id = _text(user_id)
        session_id = _text(session_id)
        if not user_id or not session_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        return _session(row) if row else None

    def set_agent_id(self, session_id: str, agent_id: str) -> None:
        session_id = _text(session_id)
        if not session_id:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET agent_id = ?, updated_at = ? WHERE id = ?",
                (_text(agent_id) or None, _now(), session_id),
            )
            self._conn.commit()

    def rename_session(self, user_id: str, session_id: str, title: str) -> Session | None:
        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        label = (title or "").strip().replace("\n", " ")[:80] or session.title
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ? AND user_id = ?",
                (label, _text(session_id), _text(user_id)),
            )
            self._conn.commit()
        return self.get_session(user_id, session_id)

    def set_pinned(self, user_id: str, session_id: str, pinned: bool) -> Session | None:
        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET pinned = ? WHERE id = ? AND user_id = ?",
                (1 if pinned else 0, _text(session_id), _text(user_id)),
            )
            self._conn.commit()
        return self.get_session(user_id, session_id)

    def import_session(
        self,
        user_id: str,
        session_id: str,
        provider: str,
        title: str,
        agent_id: str | None,
        created_at: str,
        updated_at: str,
    ) -> bool:
        user_id = _text(user_id)
        session_id = _text(session_id)
        if not user_id or not session_id:
            return False
        if self.get_session(user_id, session_id) is not None:
            return False
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (id, user_id, provider, title, agent_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    provider or "cursor",
                    title or "New Chat",
                    _text(agent_id) or None,
                    created_at or _now(),
                    updated_at or _now(),
                ),
            )
            self._conn.commit()
        return True

    def rename_if_default(self, session_id: str, title: str) -> None:
        session_id = _text(session_id)
        if not session_id:
            return
        with self._lock:
            self._conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE id = ? AND title IN ('New Chat', 'New chat', 'Neuer Chat')
                """,
                (title[:80], _now(), session_id),
            )
            self._conn.commit()

    def apply_generated_title(self, user_id: str, session_id: str, first_user: str, title: str) -> str | None:
        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        snippet = (first_user or "").replace("\n", " ").strip()[:80]
        if session.title not in {"New Chat", "New chat", "Neuer Chat", snippet}:
            return None
        label = (title or "").strip().replace("\n", " ")[:80]
        if not label:
            return None
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (label, _now(), _text(session_id), _text(user_id)),
            )
            self._conn.commit()
        return label

    def touch(self, session_id: str) -> None:
        session_id = _text(session_id)
        if not session_id:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )
            self._conn.commit()

    def add_message(self, session_id: str, role: str, content: str, events: str = "[]") -> ChatMessage:
        session_id = _text(session_id)
        now = _now()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO messages (session_id, role, content, events, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, events, now),
            )
            self._conn.commit()
            row_id = int(cursor.lastrowid)
        self.touch(session_id)
        return ChatMessage(
            id=row_id,
            session_id=session_id,
            role=role,
            content=content,
            events=events,
            created_at=now,
        )

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        session_id = _text(session_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [
            ChatMessage(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                events=row["events"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def delete_session(self, user_id: str, session_id: str) -> bool:
        if self.get_session(user_id, session_id) is None:
            return False
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (_text(session_id),))
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (_text(session_id),))
            self._conn.commit()
        return True


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        provider=row["provider"],
        title=row["title"],
        agent_id=row["agent_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        pinned=bool(row["pinned"]) if "pinned" in row.keys() else False,
    )
