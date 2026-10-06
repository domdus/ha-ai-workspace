from __future__ import annotations

import re

_PROMPT = """Write a short sidebar title for this chat.

Rules:
- 3 to 6 words
- Same language as the user
- Name the topic; do not quote the user
- No quotation marks, no trailing punctuation, no prefix

User:
{user}
"""


def title_prompt(user: str, assistant: str = "") -> str:
    text = _PROMPT.format(user=(user or "").strip()[:800])
    extra = (assistant or "").strip()[:400]
    if extra:
        text += f"\nAssistant:\n{extra}\n"
    return text


def clean_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = re.sub(r"^(title|chat title)\s*:\s*", "", text, flags=re.I)
    text = text.strip(" \t\"'`“”‘’")
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:60]


def is_placeholder_title(title: str, first_user: str) -> bool:
    current = (title or "").strip()
    if current in {"", "New Chat", "New chat", "Neuer Chat"}:
        return True
    snippet = (first_user or "").replace("\n", " ").strip()[:80]
    return bool(snippet) and current == snippet
