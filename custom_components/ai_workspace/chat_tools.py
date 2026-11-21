"""Read-only tools for the agent: find and read the user's other chats.

Same user only. Cloud agents call them in process; Cursor, Claude and Codex on the Runtime
reach them over MCP at /api/ai_workspace/chats/mcp with the user's own token.
"""

from __future__ import annotations

from typing import Any

from .chat_scope import _PLACEHOLDERS, _weights, chat_excerpt, fold, score_title
from .const import CROSS_CHAT_BUDGET, CROSS_CHAT_MIN_SCORE

SERVER_NAME = "chats"
LIST_TOOL = "list_chats"
READ_TOOL = "read_chat"
TOOL_NAMES = frozenset({LIST_TOOL, READ_TOOL})
MCP_PATH = "/api/ai_workspace/chats/mcp"
_LIST_MAX = 30
_READ_MAX_CHARS = 40_000
_READ_MAX_N = 200


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": LIST_TOOL,
            "description": (
                "List the user's other AI Workspace chats (read-only), best title match first. "
                "Spelling, umlauts (ae/oe/ue) and small typos do not matter. Without a query: newest first."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words from the chat title, e.g. Bewässerung."},
                },
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": READ_TOOL,
            "description": (
                "Read the latest messages of one of the user's chats (read-only), newest kept first, "
                "line breaks, tables and code intact, with a short summary of older messages. "
                "Use it when the user refers to another chat. Never change that chat."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title_or_id": {"type": "string", "description": "Chat id from list_chats, or its title."},
                    "last_n": {"type": "integer", "description": "How many of the newest messages (default all that fit)."},
                    "max_chars": {"type": "integer", "description": f"Character budget (default {CROSS_CHAT_BUDGET})."},
                },
                "required": ["title_or_id"],
            },
            "annotations": {"readOnlyHint": True},
        },
    ]


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _rows(store, user_id: str, current: str = "") -> list[dict]:
    return [
        {
            "id": item.id,
            "title": item.title,
            "updated_at": item.updated_at,
            "pinned": bool(getattr(item, "pinned", False)),
            "current": item.id == current,
        }
        for item in store.list_sessions(user_id)
    ]


def list_chats(store, user_id: str, query: str = "", current: str = "") -> dict:
    chats = [chat for chat in _rows(store, user_id, current) if chat["title"].strip().casefold() not in _PLACEHOLDERS]
    query = str(query or "").strip()
    if query:
        weights = _weights(chats)
        scored = []
        for order, chat in enumerate(chats):
            value = score_title(query, chat["title"], weights)
            # A word that is only part of a title still lists it, below better matches.
            if value <= 0 and fold(query) in fold(chat["title"]):
                value = 1.0
            if value > 0:
                scored.append((value, order, chat))
        scored.sort(key=lambda item: (-item[0], item[1]))
        chats = [{**chat, "score": round(value, 1)} for value, _, chat in scored]
    return {"chats": chats[:_LIST_MAX], "count": len(chats)}


def find_chat(store, user_id: str, title_or_id: str, current: str = "") -> dict | None:
    wanted = str(title_or_id or "").strip()
    if not wanted:
        return None
    chats = _rows(store, user_id, current)
    for chat in chats:
        if chat["id"] == wanted:
            return chat
    named = [chat for chat in chats if chat["title"].strip().casefold() not in _PLACEHOLDERS]
    for chat in named:
        if fold(chat["title"]).strip() == fold(wanted):
            return chat
    weights = _weights(named)
    best = None
    for order, chat in enumerate(named):
        value = score_title(wanted, chat["title"], weights)
        if value >= CROSS_CHAT_MIN_SCORE and (best is None or value > best[0]):
            best = (value, order, chat)
    return best[2] if best else None


def read_chat(
    store, user_id: str, title_or_id: str, last_n: Any = 0, max_chars: Any = CROSS_CHAT_BUDGET, current: str = ""
) -> dict:
    chat = find_chat(store, user_id, title_or_id, current)
    if chat is None:
        return {"ok": False, "error": f"No chat matches {str(title_or_id)[:80]!r}. Call list_chats to see the titles."}
    rows = store.list_messages(chat["id"])
    budget = _int(max_chars, CROSS_CHAT_BUDGET, 1000, _READ_MAX_CHARS)
    text = chat_excerpt(
        chat["title"],
        rows,
        budget=budget,
        last_n=_int(last_n, 0, 0, _READ_MAX_N),
        reply_cap=budget,
        message_cap=budget,
        chat_id=chat["id"],
        updated_at=chat["updated_at"],
    )
    return {
        "ok": True,
        "id": chat["id"],
        "title": chat["title"],
        "updated_at": chat["updated_at"],
        "messages": len(rows),
        "text": text or "(This chat has no messages yet.)",
    }


class ChatsClient:
    """In-process tool client with the same shape as McpHttpClient for the API loop."""

    def __init__(self, hass, store, user_id: str, current: str = "") -> None:
        self.hass = hass
        self.store = store
        self.user_id = str(user_id or "")
        self.current = str(current or "")

    async def initialize(self) -> dict[str, Any]:
        return {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return tool_definitions()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        if not self.user_id:
            return {"ok": False, "error": "No signed-in user."}
        if name == LIST_TOOL:
            return await self.hass.async_add_executor_job(
                list_chats, self.store, self.user_id, str(args.get("query") or ""), self.current
            )
        if name == READ_TOOL:
            wanted = args.get("title_or_id") or args.get("id") or args.get("title") or ""
            return await self.hass.async_add_executor_job(
                read_chat,
                self.store,
                self.user_id,
                str(wanted),
                args.get("last_n", 0),
                args.get("max_chars", CROSS_CHAT_BUDGET),
                self.current,
            )
        from .mcp_client import McpError

        raise McpError(f"Unknown chats tool: {name}")


def chats_mcp_url(hass) -> str:
    from .notes import notes_mcp_url

    return notes_mcp_url(hass).replace("/api/ai_workspace/notes/mcp", MCP_PATH)


def mcp_server_config(hass) -> dict[str, Any]:
    return {"type": "http", "url": chats_mcp_url(hass)}
