"""Plan subscription limits (not token cost) for Claude, Cursor and Codex.

Pure Python: the integration and the Runtime ship separate copies of this file.
"""

from __future__ import annotations

import hashlib
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


def credential_id(secret: str) -> str:
    """A short, non-secret ID for one credential: which sign-in or key a plan snapshot belongs to.

    Runtime and integration compute it the same way, so Home Assistant can match an agent's own Plan
    token to the snapshot its turns produced, and a runtime agent to the Runtime's own credential.
    One-way (SHA-256, domain-separated, 16 hex digits); "" for no credential.
    """
    value = str(secret or "").strip()
    if not value:
        return ""
    return "c" + hashlib.sha256(f"ai-workspace-credential:{value}".encode()).hexdigest()[:16]


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


def _info_dict(info: Any) -> dict[str, Any] | None:
    """The CLI's rate_limit_info as a camelCase dict.

    claude-agent-sdk (0.2.x) hands over ``RateLimitEvent(rate_limit_info=RateLimitInfo(...))``
    dataclasses, not dicts. ``RateLimitInfo.raw`` is the CLI's own JSON (with ``unifiedWindows``);
    the typed fields are the fallback for an SDK that leaves ``raw`` empty.
    """
    if isinstance(info, dict):
        return info
    if info is None:
        return None
    raw = getattr(info, "raw", None)
    out: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    for attr, key in (
        ("status", "status"),
        ("resets_at", "resetsAt"),
        ("rate_limit_type", "rateLimitType"),
        ("utilization", "utilization"),
        ("overage_status", "overageStatus"),
    ):
        value = getattr(info, attr, None)
        if value is not None and key not in out:
            out[key] = value
    return out if out.get("status") or out.get("unifiedWindows") else None


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


def _percent(value: object, *, fraction: bool | None = None) -> int | None:
    """0..100. ``fraction`` True: 0.0-1.0 (the CLI's headers); False: already percent (/api/oauth/usage)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if fraction is None:
        fraction = 0 < raw <= 1.0
    if fraction:
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
    # The CLI sends utilization as a fraction (0.0-1.0) in unifiedWindows and at the top level.
    session_pct = _percent(session_row.get("utilization"), fraction=True)
    week_pct = _percent(week_row.get("utilization"), fraction=True)
    session_reset = _epoch(session_row.get("resetsAt") or session_row.get("resets_at"))
    week_reset = _epoch(week_row.get("resetsAt") or week_row.get("resets_at"))
    primary_util = _percent(info.get("utilization"), fraction=True)
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
        "source": "sdk",
        "updated_at": _utc_now(),
    }
    if info.get("isUsingOverage") is not None:
        snapshot["overage"] = bool(info.get("isUsingOverage"))
    return snapshot


def parse_rate_limit_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    info = _info_dict(payload.get("rate_limit_info") or payload.get("rateLimitInfo"))
    if not info:
        return None
    return normalize_rate_limit_info(info)


def normalize_oauth_usage(body: dict[str, Any]) -> dict[str, Any] | None:
    """Snapshot from Anthropic's ``GET /api/oauth/usage`` (what Claude Code's ``/usage`` shows).

    Percent values (0-100) and ISO reset times; reading it costs no tokens. ``status`` stays empty:
    the endpoint has no allowed/warning/rejected verdict, the in-chat rate_limit_event does.
    """
    if not isinstance(body, dict):
        return None
    five = body.get("five_hour") if isinstance(body.get("five_hour"), dict) else {}
    seven = body.get("seven_day") if isinstance(body.get("seven_day"), dict) else {}
    if not five and not seven:
        return None
    return {
        "session_percent": _percent(five.get("utilization"), fraction=False),
        "week_percent": _percent(seven.get("utilization"), fraction=False),
        "session_reset_at": _epoch(five.get("resets_at")),
        "week_reset_at": _epoch(seven.get("resets_at")),
        "source": "usage_api",
        "updated_at": _utc_now(),
    }


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


# Codex warns from this share of a window on; it has no allowed/warning verdict of its own.
CODEX_WARNING_PERCENT = 80


def normalize_codex_rate_limits(limits: dict[str, Any]) -> dict[str, Any] | None:
    """Snapshot from Codex's ``account/rateLimits/updated`` (``rateLimits``: primary and secondary window).

    Each window has ``usedPercent`` (0-100), ``windowDurationMins`` and ``resetsAt`` (epoch seconds).
    A window up to a day long is the session window (ChatGPT plans: 5 hours), a longer one the week.
    """
    if not isinstance(limits, dict):
        return None
    session: dict[str, Any] = {}
    week: dict[str, Any] = {}
    for key, fallback in (("primary", "session"), ("secondary", "week")):
        window = limits.get(key)
        if not isinstance(window, dict) or window.get("usedPercent", window.get("used_percent")) is None:
            continue
        minutes = window.get("windowDurationMins", window.get("window_duration_mins"))
        kind = fallback if not isinstance(minutes, (int, float)) else ("session" if minutes <= 24 * 60 else "week")
        target = session if kind == "session" else week
        if not target:
            target.update(window)
    if not session and not week:
        return None
    session_pct = _percent(session.get("usedPercent", session.get("used_percent")), fraction=False)
    week_pct = _percent(week.get("usedPercent", week.get("used_percent")), fraction=False)
    reached = limits.get("rateLimitReachedType", limits.get("rate_limit_reached_type"))
    highest = max([pct for pct in (session_pct, week_pct) if pct is not None], default=0)
    if reached:
        status = "rejected"
    elif highest >= CODEX_WARNING_PERCENT:
        status = _STATUS_WARNING
    else:
        status = "allowed"
    return {
        "status": status,
        "session_percent": session_pct,
        "week_percent": week_pct,
        "session_reset_at": _epoch(session.get("resetsAt", session.get("resets_at"))),
        "week_reset_at": _epoch(week.get("resetsAt", week.get("resets_at"))),
        "source": "codex",
        "updated_at": _utc_now(),
    }


def parse_codex_sdk_message(message: Any) -> dict[str, Any] | None:
    data = _mapping(message)
    limits = data.get("rateLimits", data.get("rate_limits"))
    if isinstance(limits, dict):
        return normalize_codex_rate_limits(limits)
    return _dig_plan_fields(data)


_RESET_FOR = {"session_percent": "session_reset_at", "week_percent": "week_reset_at"}


def merge_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Newest known values win; a value the new snapshot does not carry (None) keeps the old one.

    A snapshot from another credential (``credential`` differs) replaces the old one completely:
    two sign-ins never mix into one reading.
    """
    base = dict(old or {})
    if new.get("credential") and base.get("credential") != new.get("credential"):
        base = {}
    for key, value in new.items():
        if key == "updated_at":
            base[key] = value
            continue
        if value is None:
            continue
        if key in _RESET_FOR and value == 0 and base.get(key):
            # A bare 0 next to a known percent is a partial reading, unless the window has rolled
            # over (a new reset time, or the stored one has passed).
            reset_key = _RESET_FOR[key]
            new_reset = new.get(reset_key)
            old_reset = base.get(reset_key)
            rolled = (new_reset is not None and new_reset != old_reset) or (
                isinstance(old_reset, (int, float)) and old_reset <= datetime.now(timezone.utc).timestamp()
            )
            if not rolled:
                continue
        base[key] = value
    if not base.get("updated_at"):
        base["updated_at"] = _utc_now()
    return base


def crossed_warning(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    previous = str((old or {}).get("status") or "")
    current = str(new.get("status") or "")
    return current == _STATUS_WARNING and previous != _STATUS_WARNING


_USAGE_FIELDS = (
    "status",
    "session_percent",
    "week_percent",
    "session_reset_at",
    "week_reset_at",
    "rate_limit_type",
    "overage",
    "source",
    "credential",
    "updated_at",
)


def plan_usage_event(engine: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """The latest snapshot for Home Assistant to store (not shown in the chat)."""
    event: dict[str, Any] = {"type": "plan_usage", "engine": engine}
    for key in _USAGE_FIELDS:
        if snapshot.get(key) is not None:
            event[key] = snapshot[key]
    return event


def snapshot_from_event(event: dict[str, Any]) -> dict[str, Any]:
    """plan_usage / plan_notice event -> snapshot for merge_snapshots (Home Assistant side)."""
    return {key: event.get(key) for key in _USAGE_FIELDS if key in event}


def has_plan_data(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    return any(snapshot.get(key) is not None for key in ("status", "session_percent", "week_percent", "session_reset_at", "week_reset_at"))


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

    def apply(
        self, engine: str, snapshot: dict[str, Any], credential: str = ""
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Store the newest values; events: plan_usage (always) and plan_notice (on crossing the warning).

        ``credential`` (see credential_id) tags the snapshot with the credential the turn ran on.
        """
        if credential:
            snapshot = {**snapshot, "credential": credential}
        old = self.get(engine)
        merged = merge_snapshots(old, snapshot)
        self._engines[engine] = merged
        try:
            self.save()
        except OSError:
            pass  # The snapshot still reaches Home Assistant in the event; the file is a cache.
        events: list[dict[str, Any]] = [plan_usage_event(engine, merged)]
        if crossed_warning(old, merged):
            events.append(plan_notice_event(engine, merged))
        return merged, events


def plan_events_from_sdk(
    book: PlanQuotaBook, engine: str, message: Any, credential: str = ""
) -> list[dict[str, Any]]:
    parsers = {
        "claude": parse_claude_sdk_message,
        "cursor": parse_cursor_sdk_message,
        "codex": parse_codex_sdk_message,
    }
    parser = parsers.get(engine)
    if parser is None:
        return []
    try:
        snapshot = parser(message)
    except Exception:  # noqa: BLE001 - plan data is extra; a strange message must not break the turn.
        return []
    if not snapshot:
        return []
    _, events = book.apply(engine, snapshot, credential)
    return events