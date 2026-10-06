from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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
        self._conn = sqlite3.connect(path, check_same_thread=False)
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
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_session(self, user_id: str, provider: str, session_id: str | None = None) -> Session:
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
        rows = self._conn.execute(
            """
            SELECT * FROM sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [_session(row) for row in rows]

    def get_session(self, user_id: str, session_id: str) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        return _session(row) if row else None

    def set_agent_id(self, session_id: str, agent_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET agent_id = ?, updated_at = ? WHERE id = ?",
            (agent_id, _now(), session_id),
        )
        self._conn.commit()

    def rename_session(self, user_id: str, session_id: str, title: str) -> Session | None:
        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        label = (title or "").strip().replace("\n", " ")[:80] or session.title
        self._conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ? AND user_id = ?",
            (label, session_id, user_id),
        )
        self._conn.commit()
        return self.get_session(user_id, session_id)

    def rename_if_default(self, session_id: str, title: str) -> None:
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
        self._conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (label, _now(), session_id, user_id),
        )
        self._conn.commit()
        return label

    def touch(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        self._conn.commit()

    def add_message(self, session_id: str, role: str, content: str, events: str = "[]") -> ChatMessage:
        now = _now()
        cursor = self._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, events, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, events, now),
        )
        self._conn.commit()
        self.touch(session_id)
        return ChatMessage(
            id=int(cursor.lastrowid),
            session_id=session_id,
            role=role,
            content=content,
            events=events,
            created_at=now,
        )

    def list_messages(self, session_id: str) -> list[ChatMessage]:
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
        session = self.get_session(user_id, session_id)
        if session is None:
            return False
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
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
    )
