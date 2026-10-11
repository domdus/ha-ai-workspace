from __future__ import annotations

import json
import re

_CUES = re.compile(
    r"\b(chats?|conversations?|unterhaltung|gespr(?:ä|ae)ch|früher|frueher|vorher)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_STOP = frozenset(
    {
        "about",
        "another",
        "bitte",
        "chat",
        "chats",
        "conversation",
        "conversations",
        "dass",
        "diese",
        "dieser",
        "from",
        "gemacht",
        "gespräch",
        "gespraech",
        "haben",
        "have",
        "just",
        "kann",
        "kannst",
        "know",
        "like",
        "nicht",
        "noch",
        "other",
        "please",
        "that",
        "this",
        "unser",
        "unsere",
        "unserem",
        "unterhaltung",
        "what",
        "when",
        "where",
        "wissen",
        "with",
        "your",
    }
)
_PLACEHOLDERS = frozenset({"", "new chat", "neuer chat"})
_HANDOFF_MAX = 16
_HANDOFF_CLIP = 1600
_TABLE_LINE = re.compile(
    r"""
    ^\s*
    (
      \|.*\|
      | \|?[\s:|-]*---[\s:|-]*
      | [^\n|]+\s\|\s[^\n|]+(\s\|\s[^\n|]*)*
    )
    \s*$
    """,
    re.VERBOSE,
)
HANDOFF_LEAD = (
    "This is the same chat. The transcript below is the conversation so far, "
    "including replies from other agents. "
    "Continue from it. Do not greet as if this is a new chat, and do not say the chat was empty. "
    "If the user says to go ahead, do the last thing you offered."
)
_HANDOFF_LEAD = HANDOFF_LEAD


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text or "") if word.casefold() not in _STOP}


def matching_chats(message: str, chats: list[dict], current_id: str, cross: bool = False) -> list[dict]:
    """Other chats whose title overlaps this message.

    Without Cross chat, the message also has to mention a chat.
    """
    if not cross and not _CUES.search(message or ""):
        return []
    asked = _words(message)
    if not asked:
        return []
    found = []
    for chat in chats:
        if str(chat.get("id") or "") == current_id:
            continue
        title = str(chat.get("title") or "").strip()
        if title.casefold() in _PLACEHOLDERS:
            continue
        title_words = _words(title)
        if title.casefold() not in (message or "").casefold() and not (title_words & asked):
            continue
        found.append(chat)
        if len(found) == 2:
            break
    return found


def excerpt_for(chats: list[dict]) -> str:
    blocks = []
    for chat in chats:
        title = str(chat.get("title") or "").strip()
        lines = []
        for role, content in list(chat.get("messages") or [])[-8:]:
            body = " ".join(str(content or "").split())
            if role not in {"user", "assistant"} or not body:
                continue
            lines.append(f"{role}: {body[:400]}")
        if not lines:
            continue
        blocks.append(
            f'Read-only excerpt from the chat "{title}". '
            "Use it only to answer this question. Do not change that chat.\n" + "\n".join(lines)
        )
    return "\n\n".join(blocks)


def other_chat_note(store, user_id: str, session_id: str, message: str, cross: bool = False) -> str:
    sessions = store.list_sessions(user_id)
    catalog = [{"id": item.id, "title": item.title} for item in sessions]
    picked = matching_chats(message, catalog, session_id, cross=bool(cross))
    loaded = []
    for chat in picked:
        rows = store.list_messages(chat["id"])
        loaded.append(
            {
                "id": chat["id"],
                "title": chat["title"],
                "messages": [(row.role, row.content) for row in rows],
            }
        )
    return excerpt_for(loaded)


def _without_tables(text: str) -> str:
    kept: list[str] = []
    for line in str(text or "").splitlines():
        if _TABLE_LINE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _failed_reply(row) -> bool:
    if getattr(row, "role", "") != "assistant":
        return False
    try:
        events = json.loads(getattr(row, "events", None) or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(events, list):
        return False
    errors = [str(item.get("message") or "") for item in events if isinstance(item, dict) and item.get("type") == "error"]
    if not errors:
        return False
    content = str(getattr(row, "content", "") or "").strip()
    return not content or content in errors


def handoff_note(rows, title: str = "") -> str:
    """Prior turns from this HA chat, used only when Cursor may have lost the thread."""
    lines: list[str] = []
    for row in rows or []:
        role = str(getattr(row, "role", "") or "")
        if role not in {"user", "assistant"} or _failed_reply(row):
            continue
        body = " ".join(_without_tables(str(getattr(row, "content", "") or "")).split())
        if not body:
            continue
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {body[:_HANDOFF_CLIP]}")
    if lines and lines[-1].startswith("User:"):
        lines = lines[:-1]
    if not lines:
        return ""
    if len(lines) > _HANDOFF_MAX:
        lines = lines[-_HANDOFF_MAX:]
    name = " ".join(str(title or "").split())
    if name and name.casefold() not in _PLACEHOLDERS:
        lead = (
            f'This is the same chat titled "{name[:80]}". '
            "The transcript below is the conversation so far, including replies from other agents. "
            "Continue from it. Do not greet as if this is a new chat, and do not say the chat was empty. "
            "If the user says to go ahead, do the last thing you offered."
        )
    else:
        lead = _HANDOFF_LEAD
    return f"{lead}\n\n" + "\n".join(lines)


def attach_handoff(message: str, rows, needed: bool = True, title: str = "") -> str:
    if not needed:
        return message
    note = handoff_note(rows, title)
    if not note:
        return message
    return f"{note}\n\n{message}"
