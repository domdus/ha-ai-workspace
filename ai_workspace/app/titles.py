from __future__ import annotations

import re

_PROMPT = """Write a short sidebar title for this chat from the user's first message only.

Rules:
- 3 to 8 words
- Same language as the user
- Summarize the topic; do not copy or truncate the message
- If the message is already a short label, return that label cleaned
- Do not use the words Home Assistant, MCP, assistance, assistant, chat, or help
- Plain text only: no quotes, markdown, asterisks, or trailing punctuation

User:
{user}
"""

_GENERIC = re.compile(
    r"\b(home assistant|mcp|assistance|assistent|assistant|new chat|chat title|hilfe beim)\b",
    re.I,
)
_PLACEHOLDERS = {"", "New Chat", "New chat", "Neuer Chat"}


def title_prompt(user: str, assistant: str = "") -> str:
    del assistant
    return _PROMPT.format(user=(user or "").strip()[:800])


def clean_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = re.sub(r"^(title|chat title)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"[*_`#]+", "", text)
    text = text.strip(" \t\"'`“”‘’")
    text = re.sub(r"\s+", " ", text).strip(" .-")
    text = text.rstrip("?!.,;:")
    return text[:80]


def title_from_prompt(user: str) -> str:
    text = clean_title((user or "").replace("\n", " "))
    if text:
        return text
    return (user or "").replace("\n", " ").strip()[:80]


def needs_title_summary(user: str) -> bool:
    text = title_from_prompt(user)
    if not text:
        return False
    return len(text) > 50 or len(text.split()) > 8


def accept_generated_title(user: str, title: str) -> str:
    label = clean_title(title)
    if not label or _GENERIC.search(label):
        return ""
    source = title_from_prompt(user)
    if source.startswith(label) and len(source) > len(label) + 6:
        return ""
    return label


def is_placeholder_title(title: str, first_user: str = "") -> bool:
    current = (title or "").strip()
    if current in _PLACEHOLDERS:
        return True
    snippet = title_from_prompt(first_user)
    cleaned = title_from_prompt(current)
    if not snippet:
        return False
    if current == snippet or (cleaned and cleaned == snippet):
        return True
    if current and snippet.startswith(current):
        return True
    return bool(cleaned) and snippet.startswith(cleaned)
