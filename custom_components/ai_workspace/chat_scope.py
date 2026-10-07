from __future__ import annotations

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


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text or "") if word.casefold() not in _STOP}


def matching_chats(message: str, chats: list[dict], current_id: str) -> list[dict]:
    """Other chats whose title the user actually referred to."""
    if not _CUES.search(message or ""):
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


def other_chat_note(store, user_id: str, session_id: str, message: str) -> str:
    sessions = store.list_sessions(user_id)
    catalog = [{"id": item.id, "title": item.title} for item in sessions]
    picked = matching_chats(message, catalog, session_id)
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
