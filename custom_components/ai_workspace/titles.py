from __future__ import annotations

import re

_PROMPT = """Write a short sidebar title from the user's question only.

Rules:
- 3 to 6 words
- Same language as the user
- Name the topic; do not quote the user
- Plain text only
- No quotation marks, markdown, asterisks, bold, trailing punctuation, or prefix

User question:
{user}
"""


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
    return text[:80]


def title_from_prompt(user: str) -> str:
    text = clean_title((user or "").replace("\n", " "))
    if text:
        return text
    return (user or "").replace("\n", " ").strip()[:80]


def is_placeholder_title(title: str, first_user: str = "") -> bool:
    del first_user
    return (title or "").strip() in {"", "New Chat", "New chat", "Neuer Chat"}
