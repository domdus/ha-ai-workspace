"""The house's time zone, for agents that pass times to Home Assistant tools.

HA-MCP reads a time without a UTC offset as UTC. "History from 08:00" then starts at
08:00 UTC, an hour or two late in Europe, and misses what happened in between.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Arguments that hold a point in time. Only these are touched.
TIME_KEYS = frozenset({"start_time", "end_time", "start", "end", "since", "until", "start_date_time", "end_date_time"})
_NAIVE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")


def house_zone(hass) -> ZoneInfo | None:
    name = str(getattr(getattr(hass, "config", None), "time_zone", "") or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _offset(zone: ZoneInfo, when: datetime) -> str:
    delta = when.replace(tzinfo=zone).utcoffset()
    minutes = int(delta.total_seconds() // 60) if delta is not None else 0
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def time_rule(zone: ZoneInfo | None, now: datetime | None = None) -> str:
    """One prompt line. It only changes when daylight saving time starts or ends."""
    if zone is None:
        return ""
    stamp = (now or datetime.now(zone)).astimezone(zone).replace(tzinfo=None)
    offset = _offset(zone, stamp)
    return (
        f"Home Assistant's time zone is {zone.key} (UTC{offset} right now). Tools read a time without an "
        f"offset as UTC, so give times in tool calls with the offset, for example 2026-11-05T08:00:00{offset}, "
        "or as a relative time such as 24h. Say times to the user in local time.\n"
        "Each user message starts with the local date and time it was sent, like [Thu 05 Nov 2026, 09:21]. "
        "The newest one is now. Never write such a mark yourself. "
        "States, weather, and values in earlier messages were true when they were written. If they differ now, "
        "the house changed since then, which is not a mistake in your earlier answer. Say so only if it matters."
    )


def with_local_offset(args: Any, zone: ZoneInfo | None) -> Any:
    """Add the house's offset to times without one. Returns the same dict when nothing changes."""
    if zone is None or not isinstance(args, dict):
        return args
    changed: dict[str, Any] = {}
    for key, value in args.items():
        if key not in TIME_KEYS or not isinstance(value, str) or not _NAIVE.match(value.strip()):
            continue
        text = value.strip().replace(" ", "T")
        if "T" not in text:
            text = f"{text}T00:00:00"
        try:
            local = datetime.fromisoformat(text)
        except ValueError:
            continue
        changed[key] = f"{text}{_offset(zone, local)}"
    return {**args, **changed} if changed else args


def stamped_now(message: str, zone: ZoneInfo | None, now: datetime | None = None) -> str:
    """The new user message with the local time it is sent, in the same form as history turns."""
    if zone is None:
        return message
    from .context import stamped

    return stamped(message, (now or datetime.now(zone)).astimezone(zone))
