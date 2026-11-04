"""Which earlier turns of a chat an agent sees, for cloud agents and cold Cursor agents alike.

History is sized by a token budget taken from the model's context window and the token
mode, not by a fixed number of messages. When a chat outgrows the budget, the oldest
turns are left out in whole blocks and replaced by a short digest, so the start of the
history only moves now and then and the provider's prompt cache keeps hitting.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .const import (
    API_OLLAMA,
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_LIGHT,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
)

CHARS_PER_TOKEN = 4
FALLBACK_WINDOW = 128_000
# First match wins, so more specific ids come first.
_WINDOWS: tuple[tuple[str, int], ...] = (
    ("gpt-4.1", 1_000_000),
    ("gemini", 1_000_000),
    ("gpt-5", 400_000),
    ("gpt-4o", 128_000),
    ("o3", 200_000),
    ("o4", 200_000),
    ("claude", 200_000),
    ("opus", 200_000),
    ("sonnet", 200_000),
    ("haiku", 200_000),
    ("grok-4", 256_000),
    ("grok", 128_000),
    ("composer", 200_000),
    ("deepseek", 128_000),
    ("qwen", 128_000),
    ("mistral", 128_000),
    ("llama", 128_000),
)
_PROVIDER_WINDOWS = {API_OLLAMA: 32_000}
# Share of the window and hard cap (tokens) per token mode.
_BUDGETS = {
    TOKEN_MODE_OFF: (0.15, 24_000),
    TOKEN_MODE_LIGHT: (0.08, 8_000),
    TOKEN_MODE_MEDIUM: (0.03, 2_000),
    TOKEN_MODE_EXTREME: (0.0, 0),
}
# Turns are left out in blocks of this size so the history start stays put between turns.
BLOCK = 6
_DIGEST_SHARE = 0.15
_TURN_SHARE = 0.35
_TURN_MIN_CHARS = 2_000
_NOTES_MAX = 600
_DIGEST_USER = 200
_DIGEST_ASSISTANT = 300
DIGEST_LEAD = "Summary of earlier turns in this chat (older messages are left out to save space):"


@dataclass(frozen=True)
class Turn:
    role: str
    text: str
    notes: str = ""


def context_window(model: str = "", provider: str = "", manual: int = 0) -> int:
    """Manual setting, then the model id, then the provider, then 128k."""
    if manual and manual > 0:
        return int(manual)
    ident = str(model or "").casefold()
    for needle, size in _WINDOWS:
        if needle in ident:
            return size
    return _PROVIDER_WINDOWS.get(str(provider or ""), FALLBACK_WINDOW)


def history_budget(mode: str, window: int) -> int:
    share, cap = _BUDGETS.get(mode, _BUDGETS[TOKEN_MODE_OFF])
    return max(0, min(int(window * share), cap))


def tokens(text: str) -> int:
    return math.ceil(len(text or "") / CHARS_PER_TOKEN)


def _failed_reply(role: str, content: str, events: list) -> bool:
    if role != "assistant":
        return False
    errors = [str(item.get("message") or "") for item in events if isinstance(item, dict) and item.get("type") == "error"]
    if not errors:
        return False
    content = content.strip()
    return not content or content in errors


def _events(row) -> list:
    try:
        events = json.loads(getattr(row, "events", None) or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return events if isinstance(events, list) else []


def tool_notes(events: list) -> str:
    notes = []
    for item in events:
        if not isinstance(item, dict):
            continue
        note = " ".join(str(item.get("note") or "").split())
        if note:
            notes.append(note)
    text = "; ".join(notes)
    if len(text) > _NOTES_MAX:
        text = text[: _NOTES_MAX - 1].rstrip() + "…"
    return text


def chat_turns(rows) -> list[Turn]:
    """User and assistant turns before the message being answered now."""
    turns: list[Turn] = []
    for row in rows or []:
        role = str(getattr(row, "role", "") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(getattr(row, "content", "") or "").strip()
        events = _events(row)
        if _failed_reply(role, content, events):
            continue
        notes = tool_notes(events) if role == "assistant" else ""
        if not content and not notes:
            continue
        turns.append(Turn(role, content, notes))
    if turns and turns[-1].role == "user":
        turns = turns[:-1]
    return turns


def fit_text(text: str, limit: int) -> str:
    """Keep the start and end of a long message instead of cutting it off mid-way."""
    text = str(text or "")
    if limit <= 0 or len(text) <= limit:
        return text
    head = (limit * 2) // 3
    tail = limit - head
    left = len(text) - head - tail
    return f"{text[:head].rstrip()}\n[… {left} characters left out …]\n{text[-tail:].lstrip()}"


def _with_notes(turn: Turn) -> str:
    if not turn.notes:
        return turn.text
    note = f"[tools: {turn.notes}]"
    return f"{turn.text}\n\n{note}" if turn.text else note


def _cost(text: str) -> int:
    return tokens(text) + 4


def _line(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def digest(dropped: list[Turn], budget_chars: int) -> str:
    """A fixed short summary of left-out turns. It only changes when another block is left out."""
    if not dropped or budget_chars <= 0:
        return ""
    lines: list[str] = []
    used = len(DIGEST_LEAD)
    for turn in reversed(dropped):
        if turn.role == "user":
            line = f"- User: {_line(turn.text, _DIGEST_USER)}"
        else:
            body = _line(turn.text, _DIGEST_ASSISTANT)
            if turn.notes:
                body = f"{body} [tools: {_line(turn.notes, 160)}]".strip()
            line = f"- Assistant: {body}"
        if used + len(line) + 1 > budget_chars:
            break
        lines.append(line)
        used += len(line) + 1
    lines.reverse()
    skipped = len(dropped) - len(lines)
    if skipped:
        lines.insert(0, f"- ({skipped} older turn(s) not shown)")
    return "\n".join([DIGEST_LEAD, *lines])


@dataclass(frozen=True)
class History:
    turns: list[tuple[str, str]]
    digest: str = ""
    dropped: int = 0

    def __bool__(self) -> bool:
        return bool(self.turns or self.digest)


def select_history(turns: list[Turn], budget: int) -> History:
    """Fit turns into a token budget, leaving out the oldest in blocks of BLOCK turns."""
    if budget <= 0 or not turns:
        return History([])
    turn_chars = max(_TURN_MIN_CHARS, int(budget * CHARS_PER_TOKEN * _TURN_SHARE))
    sized = [(turn, fit_text(_with_notes(turn), turn_chars)) for turn in turns]
    costs = [_cost(text) for _, text in sized]
    if sum(costs) <= budget:
        return History([(turn.role, text) for turn, text in sized])
    room = int(budget * (1 - _DIGEST_SHARE))
    start = 0
    while start < len(sized) and sum(costs[start:]) > room:
        start += BLOCK
    start = min(start, len(sized))
    kept = sized[start:]
    note = digest(turns[:start], int(budget * _DIGEST_SHARE * CHARS_PER_TOKEN))
    return History([(turn.role, text) for turn, text in kept], note, start)


def history_for(rows, *, mode: str, model: str = "", provider: str = "", manual_window: int = 0) -> History:
    budget = history_budget(mode, context_window(model, provider, manual_window))
    return select_history(chat_turns(rows), budget)


def as_messages(history: History) -> list[dict[str, str]]:
    """Chat-completions style messages. The digest goes first as a user turn."""
    messages = [{"role": role, "content": text} for role, text in history.turns]
    if history.digest:
        if messages and messages[0]["role"] == "user":
            messages[0] = {"role": "user", "content": f"{history.digest}\n\n{messages[0]['content']}"}
        else:
            messages.insert(0, {"role": "user", "content": history.digest})
    return messages


def as_transcript(history: History) -> str:
    """Plain transcript for an agent that lost its thread. Line breaks stay, so YAML and code survive."""
    parts: list[str] = []
    if history.digest:
        parts.append(history.digest)
    for role, text in history.turns:
        label = "User" if role == "user" else "Assistant"
        parts.append(f"{label}: {text}")
    return "\n\n".join(parts)


_SKIP_ARGS = re.compile(r"(?i)^(bestpracticekey|mandatorybps|config|yaml|content|data|cards?|views?)$")


def tool_call_note(name: str, args: Any, result: str, *, limit: int = 200) -> str:
    """One short line about a tool call, kept with the reply for later turns."""
    shown = []
    if isinstance(args, dict):
        for key, value in args.items():
            if _SKIP_ARGS.match(str(key)) or not isinstance(value, (str, int, float, bool)):
                continue
            text = _line(str(value), 40)
            if text:
                shown.append(f"{key}={text}")
            if len(shown) == 4:
                break
    outcome = _line(result, limit)
    call = f"{name}({', '.join(shown)})"
    return f"{call} → {outcome}" if outcome else call
