from __future__ import annotations

import json
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


ACTIVITY_CAP = 30


@dataclass
class Activity:
    id: int
    created_at: str
    user_id: str
    user_name: str
    agent: str
    summary: str
    tool: str
    can_rollback: bool
    undone_at: str
    session_id: str = ""
    chat: str = ""
    restore_kind: str = ""
    restore_id: str = ""
    restore_label: str = ""


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
        self._path = path
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
            CREATE TABLE IF NOT EXISTS house_map (
                kind TEXT NOT NULL,
                item_id TEXT NOT NULL,
                name TEXT NOT NULL,
                area_id TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT '',
                extra TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, item_id)
            );
            CREATE INDEX IF NOT EXISTS house_map_name ON house_map(name);
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                agent TEXT NOT NULL,
                summary TEXT NOT NULL,
                tool TEXT NOT NULL,
                document TEXT NOT NULL DEFAULT '',
                undone_at TEXT
            );
            CREATE INDEX IF NOT EXISTS activity_created ON activity(created_at);
            """
        )
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        if "pinned" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        activity_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(activity)")}
        if "session_id" not in activity_cols:
            self._conn.execute("ALTER TABLE activity ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        if "chat" not in activity_cols:
            self._conn.execute("ALTER TABLE activity ADD COLUMN chat TEXT NOT NULL DEFAULT ''")
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

    def session_title(self, session_id: str) -> str:
        session_id = _text(session_id)
        if not session_id:
            return ""
        with self._lock:
            row = self._conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _text(row["title"]) if row else ""

    def session_titles(self, session_ids: list[str]) -> dict[str, str]:
        ids = [item for item in {_text(value) for value in session_ids} if item]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._conn.execute(f"SELECT id, title FROM sessions WHERE id IN ({marks})", ids).fetchall()
        return {_text(row["id"]): _text(row["title"]) for row in rows}

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

    def set_provider(self, user_id: str, session_id: str, provider: str) -> None:
        user_id = _text(user_id)
        session_id = _text(session_id)
        if not user_id or not session_id:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET provider = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (_text(provider) or "api", _now(), session_id, user_id),
            )
            self._conn.commit()

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
        from .titles import is_placeholder_title

        session = self.get_session(user_id, session_id)
        if session is None:
            return None
        if not is_placeholder_title(session.title, first_user):
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

    def prune_sessions(self, user_id: str, keep: int) -> list[str]:
        """Drop oldest unpinned chats beyond keep. Pinned chats are never removed."""
        user_id = _text(user_id)
        try:
            keep = int(keep)
        except (TypeError, ValueError):
            keep = 30
        keep = max(1, min(keep, 500))
        if not user_id:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id FROM sessions
                WHERE user_id = ? AND COALESCE(pinned, 0) = 0
                ORDER BY updated_at DESC, created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
            if len(rows) <= keep:
                return []
            drop = [str(row["id"]) for row in rows[keep:]]
            for session_id in drop:
                self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                self._conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
            self._conn.commit()
        return drop

    def list_user_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT user_id FROM sessions").fetchall()
        return [str(row["user_id"]) for row in rows if row["user_id"]]

    def replace_house_map(self, rows: list[tuple[str, str, str, str, str, str]]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM house_map")
            if rows:
                self._conn.executemany(
                    """
                    INSERT OR REPLACE INTO house_map (kind, item_id, name, area_id, domain, extra)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            self._conn.commit()

    def search_house_map(self, query: str, kind: str = "any", limit: int = 24) -> list[dict]:
        tokens = [part.lower() for part in _text(query).replace(",", " ").split() if part.strip()]
        if not tokens:
            return []
        kind = _text(kind).lower() or "any"
        limit = max(1, min(int(limit or 24), 80))
        clauses = []
        params: list[object] = []
        if kind and kind != "any":
            clauses.append("kind = ?")
            params.append(kind)
        for token in tokens[:8]:
            like = f"%{token}%"
            clauses.append(
                "(lower(name) LIKE ? OR lower(item_id) LIKE ? OR lower(area_id) LIKE ? OR lower(domain) LIKE ? OR lower(extra) LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        sql = (
            "SELECT kind, item_id, name, area_id, domain, extra FROM house_map WHERE "
            + " AND ".join(clauses)
            + " ORDER BY kind, name LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            found = self._conn.execute(sql, params).fetchall()
        out: list[dict] = []
        for row in found:
            item = {
                "kind": row["kind"],
                "id": row["item_id"],
                "name": row["name"],
            }
            if row["area_id"]:
                item["area_id"] = row["area_id"]
            if row["domain"]:
                item["domain"] = row["domain"]
            extra = _text(row["extra"])
            if extra:
                try:
                    payload = json.loads(extra)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        if value not in (None, ""):
                            item[str(key)] = value
            out.append(item)
        return out

    def add_activity(
        self,
        user_id: str,
        user_name: str,
        agent: str,
        summary: str,
        tool: str,
        document: str = "",
        session_id: str = "",
        chat: str = "",
    ) -> Activity:
        now = _now()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO activity (
                    created_at, user_id, user_name, agent, summary, tool, document, session_id, chat
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    _text(user_id),
                    _text(user_name) or _text(user_id),
                    _text(agent) or "Agent",
                    _text(summary)[:240],
                    _text(tool)[:120],
                    document or "",
                    _text(session_id),
                    _text(chat)[:80],
                ),
            )
            row_id = int(cursor.lastrowid)
            extra = self._conn.execute(
                "SELECT id FROM activity ORDER BY id DESC LIMIT -1 OFFSET ?",
                (ACTIVITY_CAP,),
            ).fetchall()
            dropped = [int(row["id"]) for row in extra]
            if dropped:
                self._conn.executemany("DELETE FROM activity WHERE id = ?", [(item,) for item in dropped])
            self._conn.commit()
        if dropped:
            self.drop_change_files(dropped)
        row = self.get_activity(row_id)
        assert row is not None
        return row

    def change_dir(self) -> Path:
        return self._path.parent / "changes"

    def change_path(self, activity_id: int) -> Path:
        return self.change_dir() / f"{int(activity_id)}.yaml"

    def drop_change_files(self, activity_ids: list[int]) -> None:
        for activity_id in activity_ids:
            path = self.change_path(activity_id)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def list_activity(self, user_id: str, *, admin: bool) -> list[Activity]:
        with self._lock:
            if admin:
                rows = self._conn.execute(
                    "SELECT * FROM activity ORDER BY id DESC LIMIT ?",
                    (ACTIVITY_CAP,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                    (_text(user_id), ACTIVITY_CAP),
                ).fetchall()
        return [_activity(row) for row in rows]

    def get_activity(self, activity_id: int) -> Activity | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM activity WHERE id = ?", (int(activity_id),)).fetchone()
        return _activity(row) if row else None

    def activity_document(self, activity_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT document FROM activity WHERE id = ?",
                (int(activity_id),),
            ).fetchone()
        return _text(row["document"]) if row else ""

    def mark_activity_undone(self, activity_id: int) -> Activity | None:
        with self._lock:
            self._conn.execute(
                "UPDATE activity SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
                (_now(), int(activity_id)),
            )
            self._conn.commit()
        return self.get_activity(activity_id)


def _restore_target(document: str) -> tuple[str, str, str]:
    if not document:
        return "", "", ""
    try:
        doc = json.loads(document)
    except json.JSONDecodeError:
        return "", "", ""
    if not isinstance(doc, dict):
        return "", "", ""
    kind = str(doc.get("kind") or "").strip()
    item_id = str(doc.get("entity_id") or doc.get("id") or "").strip()
    label = str(doc.get("label") or doc.get("name") or "").strip()
    return kind, item_id, label


def _activity(row: sqlite3.Row) -> Activity:
    undone = _text(row["undone_at"])
    document = _text(row["document"])
    restore_kind, restore_id, restore_label = _restore_target(document)
    return Activity(
        id=int(row["id"]),
        created_at=row["created_at"],
        user_id=row["user_id"],
        user_name=row["user_name"],
        agent=row["agent"],
        summary=row["summary"],
        tool=row["tool"],
        can_rollback=bool(document) and not undone,
        undone_at=undone,
        session_id=_text(row["session_id"]) if "session_id" in row.keys() else "",
        chat=_text(row["chat"]) if "chat" in row.keys() else "",
        restore_kind=restore_kind,
        restore_id=restore_id,
        restore_label=restore_label,
    )


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
