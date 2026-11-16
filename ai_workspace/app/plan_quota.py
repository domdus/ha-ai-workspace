"""Plan subscription limits (not token cost) for Claude, Cursor and Codex.

Pure Python: the integration and the Runtime ship separate copies of this file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINES = ("claude", "cursor", "codex")

OFFICIAL_LINKS = {
    "claude": "https://claude.ai/settings/usage",
    "cursor": "https://cursor.com/dashboard?tab=usage",
    "codex": "https://chatgpt.com/settings/usage",
}

CLAUDE_PLAN_REJECTED_CODE = "claude_plan_rejected"

_STATUS_WARNING = "allowed_warning"
_STATUS_REJECTED = "rejected"

_SESSION_TYPES = frozenset({"five_hour", "5h", "session", "five-hour"})
_WEEK_TYPES = frozenset({"seven_day", "7d", "week", "seven-day"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mapping(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    data = getattr(obj, "__dict__", None)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if not k.startswith("_")}
    for key in ("rate_limit_info", "rateLimitInfo"):
        value = getattr(obj, key, None)
        if value is not None:
            return {"rate_limit_info": value, "type": getattr(obj, "type", "rate_limit_event")}
    return {}


def _pick(blob: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(blob, dict) and key in blob:
            return blob[key]
        value = getattr(blob, key, None)
        if value is not None:
            return value
    return None


def _epoch(value: object) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            ts = int(value)
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.isdigit():
                ts = int(text)
            else:
                when = datetime.fromisoformat(text.replace("Z", "+00:00"))
                ts = int(when.timestamp())
        if ts > 1_000_000_000_000:
            ts //= 1000
        return ts if ts > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _percent(value: object) -> int | None:
    if value is None:
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw <= 1.0 and raw > 0:
        raw *= 100
    pct = int(round(raw))
    return max(0, min(100, pct))


def _window_blob(info: dict[str, Any], key: str) -> dict[str, Any]:
    unified = info.get("unifiedWindows") or info.get("unified_windows") or {}
    if not isinstance(unified, dict):
        unified = {}
    row = unified.get(key)
    return row if isinstance(row, dict) else {}


def normalize_rate_limit_info(info: dict[str, Any]) -> dict[str, Any]:
    """One engine snapshot with session/week percent and reset timestamps (UTC epoch)."""
    status = str(info.get("status") or "").strip().lower()
    rate_type = str(info.get("rateLimitType") or info.get("rate_limit_type") or "").strip().lower()
    session_row = _window_blob(info, "five_hour")
    week_row = _window_blob(info, "seven_day")
    session_pct = _percent(session_row.get("utilization"))
    week_pct = _percent(week_row.get("utilization"))
    session_reset = _epoch(session_row.get("resetsAt") or session_row.get("resets_at"))
    week_reset = _epoch(week_row.get("resetsAt") or week_row.get("resets_at"))
    primary_util = _percent(info.get("utilization"))
    primary_reset = _epoch(info.get("resetsAt") or info.get("resets_at"))
    if rate_type in _WEEK_TYPES:
        if week_reset is None and primary_reset is not None:
            week_reset = primary_reset
    elif session_reset is None and primary_reset is not None:
        session_reset = primary_reset
    if primary_util is not None:
        if rate_type in _WEEK_TYPES:
            if week_pct is None:
                week_pct = primary_util
        else:
            if session_pct is None:
                session_pct = primary_util
    snapshot: dict[str, Any] = {
        "status": status,
        "session_percent": session_pct,
        "week_percent": week_pct,
        "session_reset_at": session_reset,
        "week_reset_at": week_reset,
        "rate_limit_type": rate_type,
        "updated_at": _utc_now(),
    }
    if info.get("isUsingOverage") is not None:
        snapshot["overage"] = bool(info.get("isUsingOverage"))
    return snapshot


def parse_rate_limit_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    info = payload.get("rate_limit_info") or payload.get("rateLimitInfo")
    if not isinstance(info, dict):
        return None
    return normalize_rate_limit_info(info)


def parse_claude_sdk_message(message: Any) -> dict[str, Any] | None:
    data = _mapping(message)
    kind = str(data.get("type") or getattr(message, "type", "") or "").strip().lower()
    if kind == "rate_limit_event" or data.get("rate_limit_info") or data.get("rateLimitInfo"):
        return parse_rate_limit_event(data)
    return None


def _dig_plan_fields(data: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("rate_limit_info", "rateLimitInfo", "plan_usage", "planUsage", "usage_limit"):
        blob = data.get(key)
        if isinstance(blob, dict) and (
            "utilization" in blob or "status" in blob or "unifiedWindows" in blob or "unified_windows" in blob
        ):
            return normalize_rate_limit_info(blob)
    for key in ("rate_limit", "rateLimit", "usage"):
        blob = data.get(key)
        if isinstance(blob, dict):
            found = _dig_plan_fields(blob)
            if found:
                return found
    return None


def parse_cursor_sdk_message(message: Any) -> dict[str, Any] | None:
    return _dig_plan_fields(_mapping(message))


def parse_codex_sdk_message(message: Any) -> dict[str, Any] | None:
    return _dig_plan_fields(_mapping(message))


def merge_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    base = dict(old or {})
    for key, value in new.items():
        if key == "updated_at":
            base[key] = value
            continue
        if value is None:
            continue
        if key in {"session_percent", "week_percent"} and value == 0 and base.get(key):
            continue
        base[key] = value
    if not base.get("updated_at"):
        base["updated_at"] = _utc_now()
    return base


def crossed_warning(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    previous = str((old or {}).get("status") or "")
    current = str(new.get("status") or "")
    return current == _STATUS_WARNING and previous != _STATUS_WARNING


def plan_notice_event(engine: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "plan_notice",
        "engine": engine,
        "status": snapshot.get("status"),
        "session_percent": snapshot.get("session_percent"),
        "week_percent": snapshot.get("week_percent"),
        "session_reset_at": snapshot.get("session_reset_at"),
        "week_reset_at": snapshot.get("week_reset_at"),
    }


def rejection_window(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return "session"
    rate_type = str(snapshot.get("rate_limit_type") or "").lower()
    if rate_type in _WEEK_TYPES:
        return "week"
    status = str(snapshot.get("status") or "")
    if status == _STATUS_REJECTED and snapshot.get("week_percent") is not None and snapshot.get("session_percent") is None:
        return "week"
    return "week" if rate_type in _WEEK_TYPES else "session"


def rejection_reset_epoch(snapshot: dict[str, Any] | None, window: str) -> int | None:
    if not snapshot:
        return None
    if window == "week":
        return snapshot.get("week_reset_at") or snapshot.get("session_reset_at")
    return snapshot.get("session_reset_at") or snapshot.get("week_reset_at")


def _primary_reset(snapshot: dict[str, Any]) -> int | None:
    rate_type = str(snapshot.get("rate_limit_type") or "").lower()
    if rate_type in _WEEK_TYPES:
        return snapshot.get("week_reset_at") or snapshot.get("session_reset_at")
    return snapshot.get("session_reset_at") or snapshot.get("week_reset_at")


def plan_rejection_error(engine: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    window = rejection_window(snapshot)
    return {
        "type": "error",
        "code": CLAUDE_PLAN_REJECTED_CODE if engine == "claude" else f"{engine}_plan_rejected",
        "engine": engine,
        "window": window,
        "reset_at": _primary_reset(snapshot) if snapshot else None,
        "message": "",  # Integration localizes; runtime may fill a short English fallback.
    }


def is_plan_rejection(*, api_error: str = "", status: object = None, text: str = "") -> bool:
    if str(api_error or "").strip().lower() in {"rate_limit", "rate_limit_error", "billing_error"}:
        return True
    if status in {429, 529}:
        return True
    low = str(text or "").lower()
    return "rate limit" in low or "usage limit" in low or "limit reached" in low


class PlanQuotaBook:
    """Persisted plan snapshots keyed by engine (JSON file on the Runtime)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._engines: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            self._engines = {}
            return
        engines = raw.get("engines") if isinstance(raw, dict) else {}
        self._engines = {str(k): v for k, v in engines.items() if isinstance(v, dict)} if isinstance(engines, dict) else {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"engines": self._engines}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def public(self) -> dict[str, dict[str, Any]]:
        return dict(self._engines)

    def get(self, engine: str) -> dict[str, Any] | None:
        row = self._engines.get(engine)
        return dict(row) if isinstance(row, dict) else None

    def apply(self, engine: str, snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        old = self.get(engine)
        merged = merge_snapshots(old, snapshot)
        self._engines[engine] = merged
        self.save()
        events: list[dict[str, Any]] = []
        if crossed_warning(old, merged):
            events.append(plan_notice_event(engine, merged))
        return merged, events


def plan_events_from_sdk(book: PlanQuotaBook, engine: str, message: Any) -> list[dict[str, Any]]:
    parsers = {
        "claude": parse_claude_sdk_message,
        "cursor": parse_cursor_sdk_message,
        "codex": parse_codex_sdk_message,
    }
    parser = parsers.get(engine)
    if parser is None:
        return []
    snapshot = parser(message)
    if not snapshot:
        return []
    _, events = book.apply(engine, snapshot)
    return events