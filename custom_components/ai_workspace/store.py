from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Claude reports uncached input separately. Count cache read/write on those rows
# so the Usage page matches the tokens Anthropic actually bills.
_COUNTED_TOKENS = """
CASE
  WHEN prompt_tokens >= cache_read_tokens + cache_write_tokens
    THEN CASE WHEN total_tokens > 0 THEN total_tokens ELSE prompt_tokens + completion_tokens END
  ELSE prompt_tokens + cache_read_tokens + cache_write_tokens + completion_tokens
END
"""


def _counted_tokens(
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    total_tokens: int = 0,
) -> int:
    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    read = int(cache_read_tokens or 0)
    write = int(cache_write_tokens or 0)
    stored = int(total_tokens or 0)
    if prompt >= read + write:
        return stored or (prompt + completion)
    return prompt + read + write + completion


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _usage_where(
    *,
    since: str | None = None,
    until: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    origin: str | None = None,
    model: str | None = None,
    exclude_tts: bool = False,
    user_id: str | None = None,
) -> tuple[str, list[object]]:
    clauses = ["1=1"]
    params: list[object] = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(_text(user_id))
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if until:
        clauses.append("created_at < ?")
        params.append(until)
    if agent_id:
        clauses.append("agent_id = ?")
        params.append(_text(agent_id))
    if session_id:
        clauses.append("session_id = ?")
        params.append(_text(session_id))
    if origin:
        clauses.append("origin = ?")
        params.append(_text(origin))
    elif exclude_tts:
        clauses.append("origin != 'tts'")
    if model:
        clauses.append("CASE WHEN TRIM(model) = '' THEN agent_id ELSE model END = ?")
        params.append(_text(model))
    return " AND ".join(clauses), params


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
    logical_commit: bool = False
    change_count: int = 0
    restore_targets: list = field(default_factory=list)


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
            CREATE TABLE IF NOT EXISTS usage_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                agent TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL,
                cost_source TEXT NOT NULL DEFAULT '',
                charged_cents INTEGER,
                run_id TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                characters INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS usage_turns_created ON usage_turns(created_at);
            CREATE INDEX IF NOT EXISTS usage_turns_agent ON usage_turns(agent_id, created_at);
            CREATE INDEX IF NOT EXISTS usage_turns_session ON usage_turns(session_id);
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
        usage_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(usage_turns)")}
        if "characters" not in usage_cols:
            self._conn.execute("ALTER TABLE usage_turns ADD COLUMN characters INTEGER NOT NULL DEFAULT 0")
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
        """Remove the chat and its messages. Usage turns stay: the provider already billed them."""
        if self.get_session(user_id, session_id) is None:
            return False
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (_text(session_id),))
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (_text(session_id),))
            self._conn.commit()
        return True

    def prune_sessions(self, user_id: str, keep: int) -> list[str]:
        """Drop oldest unpinned chats beyond keep. Pinned chats and usage turns stay."""
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

    def add_usage(
        self,
        *,
        user_id: str,
        session_id: str = "",
        agent_id: str = "",
        agent: str = "",
        provider: str = "",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        total_tokens: int = 0,
        cost_usd: float | None = None,
        cost_source: str = "",
        charged_cents: int | None = None,
        run_id: str = "",
        origin: str = "",
        characters: int = 0,
        created_at: str | None = None,
    ) -> int:
        now = _text(created_at) or _now()
        total = _counted_tokens(
            prompt_tokens,
            completion_tokens,
            cache_read_tokens,
            cache_write_tokens,
            total_tokens,
        )
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO usage_turns (
                    created_at, user_id, session_id, agent_id, agent, provider, model,
                    prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, total_tokens, cost_usd, cost_source, charged_cents,
                    run_id, origin, characters
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    _text(user_id),
                    _text(session_id),
                    _text(agent_id),
                    _text(agent),
                    _text(provider),
                    _text(model),
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    int(cache_read_tokens or 0),
                    int(cache_write_tokens or 0),
                    int(reasoning_tokens or 0),
                    total,
                    None if cost_usd is None else float(cost_usd),
                    _text(cost_source),
                    None if charged_cents is None else int(charged_cents),
                    _text(run_id),
                    _text(origin),
                    int(characters or 0),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def summarize_usage(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        origin: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        where, params = _usage_where(
            since=since,
            until=until,
            agent_id=agent_id,
            session_id=session_id,
            origin=origin,
            model=model,
            user_id=user_id,
        )
        with self._lock:
            row = self._conn.execute(
                f"""
                SELECT
                    COUNT(*) AS turns,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM({_COUNTED_TOKENS}), 0) AS total_tokens,
                    COALESCE(SUM(characters), 0) AS characters,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd,
                    SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS missing_cost
                FROM usage_turns
                WHERE {where}
                """,
                params,
            ).fetchone()
        return {
            "turns": int(row["turns"] or 0),
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
            "cache_read_tokens": int(row["cache_read_tokens"] or 0),
            "cache_write_tokens": int(row["cache_write_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "characters": int(row["characters"] or 0),
            "cost_usd": round(float(row["cost_usd"] or 0), 6),
            "missing_cost": bool(row["missing_cost"]),
        }

    def usage_by_agent(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        where, params = _usage_where(
            since=since,
            until=until,
            agent_id=agent_id,
            session_id=session_id,
            model=model,
            user_id=user_id,
        )
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    agent_id,
                    MAX(agent) AS agent,
                    MAX(provider) AS provider,
                    MAX(model) AS model,
                    COUNT(*) AS turns,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM({_COUNTED_TOKENS}), 0) AS total_tokens,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd,
                    SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS missing_cost
                FROM usage_turns
                WHERE {where}
                GROUP BY agent_id
                ORDER BY cost_usd DESC, total_tokens DESC
                """,
                params,
            ).fetchall()
        return [
            {
                "agent_id": _text(row["agent_id"]),
                "agent": _text(row["agent"]),
                "provider": _text(row["provider"]),
                "model": _text(row["model"]),
                "turns": int(row["turns"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_write_tokens": int(row["cache_write_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cost_usd": round(float(row["cost_usd"] or 0), 6),
                "missing_cost": bool(row["missing_cost"]),
            }
            for row in rows
        ]

    def last_usage(
        self, *, agent_id: str | None = None, session_id: str | None = None, user_id: str | None = None
    ) -> dict | None:
        where, params = _usage_where(agent_id=agent_id, session_id=session_id, user_id=user_id)
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM usage_turns WHERE {where} ORDER BY id DESC LIMIT 1",
                params,
            ).fetchone()
        if not row:
            return None
        prompt = int(row["prompt_tokens"] or 0)
        completion = int(row["completion_tokens"] or 0)
        cache_read = int(row["cache_read_tokens"] or 0) if "cache_read_tokens" in row.keys() else 0
        cache_write = int(row["cache_write_tokens"] or 0) if "cache_write_tokens" in row.keys() else 0
        return {
            "id": int(row["id"]),
            "created_at": row["created_at"],
            "agent_id": _text(row["agent_id"]),
            "agent": _text(row["agent"]),
            "provider": _text(row["provider"]),
            "model": _text(row["model"]),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_tokens": _counted_tokens(
                prompt, completion, cache_read, cache_write, int(row["total_tokens"] or 0)
            ),
            "characters": int(row["characters"] or 0) if "characters" in row.keys() else 0,
            "cost_usd": None if row["cost_usd"] is None else round(float(row["cost_usd"]), 6),
            "cost_source": _text(row["cost_source"]),
            "session_id": _text(row["session_id"]),
            "origin": _text(row["origin"]),
        }

    def usage_by_model(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        where, params = _usage_where(
            since=since,
            until=until,
            agent_id=agent_id,
            session_id=session_id,
            model=model,
            exclude_tts=True,
            user_id=user_id,
        )
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    CASE WHEN TRIM(model) = '' THEN agent_id ELSE model END AS model_key,
                    MAX(model) AS model,
                    MAX(agent) AS agent,
                    MAX(agent_id) AS agent_id,
                    MAX(provider) AS provider,
                    COUNT(*) AS turns,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM({_COUNTED_TOKENS}), 0) AS total_tokens,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd,
                    SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS missing_cost
                FROM usage_turns
                WHERE {where}
                GROUP BY model_key
                ORDER BY cost_usd DESC, total_tokens DESC
                """,
                params,
            ).fetchall()
        models = []
        for row in rows:
            turns = int(row["turns"] or 0)
            tokens = int(row["total_tokens"] or 0)
            missing = bool(row["missing_cost"])
            cost = None if missing and not row["cost_usd"] else round(float(row["cost_usd"] or 0), 6)
            models.append(
                {
                    "model": _text(row["model"]) or _text(row["agent"]) or _text(row["model_key"]) or "Unknown",
                    "agent": _text(row["agent"]),
                    "agent_id": _text(row["agent_id"]),
                    "provider": _text(row["provider"]),
                    "turns": turns,
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                    "cache_write_tokens": int(row["cache_write_tokens"] or 0),
                    "total_tokens": tokens,
                    "cost_usd": cost,
                    "missing_cost": missing,
                    "tokens_per_turn": round(tokens / turns, 1) if turns else 0.0,
                    "cost_per_turn": None if cost is None or not turns else round(cost / turns, 6),
                    "cost_per_1k": None if cost is None or not tokens else round(cost / tokens * 1000, 6),
                }
            )
        return models

    def usage_filter_choices(self, *, agent_id: str | None = None, user_id: str | None = None) -> dict:
        model_where, model_params = _usage_where(agent_id=agent_id, user_id=user_id)
        agent_where, agent_params = _usage_where(user_id=user_id)
        with self._lock:
            agents = self._conn.execute(
                f"""
                SELECT agent_id, MAX(agent) AS agent
                FROM usage_turns
                WHERE TRIM(COALESCE(agent_id, '')) != '' AND {agent_where}
                GROUP BY agent_id
                ORDER BY agent COLLATE NOCASE
                """,
                agent_params,
            ).fetchall()
            models = self._conn.execute(
                f"""
                SELECT DISTINCT CASE WHEN TRIM(model) = '' THEN agent_id ELSE model END AS model_key
                FROM usage_turns
                WHERE {model_where}
                ORDER BY model_key COLLATE NOCASE
                """,
                model_params,
            ).fetchall()
        return {
            "agents": [
                {"id": _text(row["agent_id"]), "title": _text(row["agent"]) or _text(row["agent_id"])}
                for row in agents
            ],
            "models": [_text(row["model_key"]) for row in models if _text(row["model_key"])],
        }

    def usage_chat_choices(
        self,
        *,
        agent_id: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Existing chats that still have a session row and at least one usage turn."""
        clauses = ["1=1"]
        params: list[object] = []
        if user_id:
            clauses.append("s.user_id = ?")
            params.append(_text(user_id))
        if agent_id:
            clauses.append("u.agent_id = ?")
            params.append(_text(agent_id))
        if model:
            clauses.append("CASE WHEN TRIM(u.model) = '' THEN u.agent_id ELSE u.model END = ?")
            params.append(_text(model))
        where = " AND ".join(clauses)
        cap = max(1, min(int(limit or 100), 200))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT s.id AS id, MAX(s.title) AS title
                FROM sessions s
                INNER JOIN usage_turns u ON u.session_id = s.id
                WHERE {where}
                GROUP BY s.id
                ORDER BY MAX(s.updated_at) DESC, s.id DESC
                LIMIT {cap}
                """,
                params,
            ).fetchall()
        return [
            {"id": _text(row["id"]), "title": _text(row["title"]) or _text(row["id"])}
            for row in rows
            if _text(row["id"])
        ]

    def usage_events(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        where, params = _usage_where(
            since=since,
            until=until,
            agent_id=agent_id,
            session_id=session_id,
            model=model,
            exclude_tts=True,
            user_id=user_id,
        )
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT created_at, {_COUNTED_TOKENS} AS total_tokens, cost_usd, origin
                FROM usage_turns
                WHERE {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "created_at": row["created_at"],
                "total_tokens": int(row["total_tokens"] or 0),
                "cost_usd": None if row["cost_usd"] is None else float(row["cost_usd"]),
                "origin": _text(row["origin"]),
            }
            for row in rows
        ]


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
    try:
        from .logical_commit import parse_logical_document, restore_targets

        logical = parse_logical_document(document)
        targets = restore_targets(document)
    except ImportError:
        logical = None
        targets = []
    if logical:
        restore_kind = ", ".join(item[0] for item in targets if item[0])[:120]
        restore_id = ", ".join(item[1] for item in targets if item[1])[:240]
        restore_label = "; ".join(item[2] for item in targets if item[2])[:240]
        change_count = int(logical.get("change_count") or len(targets) or 0)
    else:
        restore_kind, restore_id, restore_label = _restore_target(document)
        change_count = 1 if restore_kind or restore_id or restore_label else 0
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
        logical_commit=bool(logical),
        change_count=change_count,
        restore_targets=[{"kind": k, "id": i, "label": label} for k, i, label in targets],
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
