"""Carry HA-MCP's best-practice key from the guide the agent read into its writes.

HA-MCP's strict mode checks a read-receipt key on every gated write. It rotates hourly and is
published only at the top of ``ha_get_skill_guide``. Models copy it wrong, lose it when a chat
gets long, or re-read the 20-50k character guide before every write. Once the agent has read
the guide through AI Workspace, its writes carry that key, and ``MandatoryBPS=false`` so HA-MCP
does not attach the same guide to every write again (its own guide asks for that).

The same file ships in the runtime (``ai_workspace/app/bps_key.py``) for Cursor agents.
Keep both copies identical; a test checks it.
"""

from __future__ import annotations

import re
import time
from typing import Any

KEY = re.compile(r"I-HAVE-READ-THE-BEST-PRACTICES-GUIDE-[0-9a-f]{6,16}")
_GUIDE = re.compile(r"ha_get_skill_guide$")
_GATED = re.compile(r"ha_config_set_(automation|script|scene|helper|dashboard|yaml)$")
# HA-MCP accepts the current and the previous hour's key, so a key is good for at least an hour.
_TTL = 55 * 60.0
_KEEP = 8
_seen: dict[str, float] = {}


def _now(now: float | None) -> float:
    return time.monotonic() if now is None else now


def note_guide(tool: str, text: Any, now: float | None = None) -> str:
    """Remember the key in a guide answer. Returns it, or an empty string."""
    if not _GUIDE.search(str(tool or "")):
        return ""
    found = KEY.search(str(text or ""))
    if not found:
        return ""
    _seen[found.group(0)] = _now(now)
    for old in sorted(_seen, key=_seen.get)[:-_KEEP]:
        del _seen[old]
    return found.group(0)


def current_key(now: float | None = None) -> str:
    moment = _now(now)
    fresh = [(at, key) for key, at in _seen.items() if moment - at < _TTL]
    return max(fresh)[1] if fresh else ""


def prepare_write(tool: str, arguments: Any, now: float | None = None) -> Any:
    """Arguments for a gated write, with the key from the last guide read and no inline guide."""
    if not _GATED.search(str(tool or "")) or not isinstance(arguments, dict):
        return arguments
    key = current_key(now)
    if not key:
        return arguments
    out = dict(arguments)
    if out.get("BestPracticeKey") not in _seen or _now(now) - _seen[out["BestPracticeKey"]] >= _TTL:
        out["BestPracticeKey"] = key
    out.setdefault("MandatoryBPS", False)
    return out


def forget() -> None:
    _seen.clear()
