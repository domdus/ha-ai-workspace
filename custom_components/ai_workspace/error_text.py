"""One readable sentence for any agent error, instead of a response body or a trace."""

from __future__ import annotations

import json
import re
from typing import Any

_LIMIT = 400
_TIMEOUT = "The provider did not answer in time. Try again, or pick a faster model."
# Library wording for a provider that stopped answering.
_TIMED_OUT = re.compile(r"timeout on reading data from socket|read timed out", re.I)


def _message(data: Any) -> str:
    if isinstance(data, list):
        return next((text for text in (_message(item) for item in data) if text), "")
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        return _message(err) or str(err.get("status") or err.get("code") or "")
    if isinstance(err, str) and err.strip():
        return err.strip()
    for key in ("message", "detail", "error_description", "msg"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (dict, list)):
            found = _message(value)
            if found:
                return found
    return ""


def _embedded_json(text: str) -> tuple[str, Any]:
    """The text before a JSON body and the parsed body, e.g. ``Gemini error 503: {...}``."""
    for index, char in enumerate(text):
        if char in "[{":
            try:
                return text[:index].strip(" :-"), json.loads(text[index:])
            except ValueError:
                continue
    return text, None


def public_error(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "The agent failed."
    if raw.startswith("Traceback (most recent call last)"):
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        raw = lines[-1] if lines else raw
    lead, data = _embedded_json(raw)
    if data is not None:
        found = _message(data)
        if found:
            raw = found
        elif lead:
            raw = lead
        else:
            return "The model provider returned an error without a message."
    elif raw.startswith("<"):
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", raw)).strip()
        raw = plain or "The model provider returned an error page."
    if _TIMED_OUT.search(raw) and len(raw) < 120:
        return _TIMEOUT
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw if len(raw) <= _LIMIT else raw[: _LIMIT - 1].rstrip() + "…"
