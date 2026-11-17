"""Plan subscription quota parsing and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workspace.app.plan_quota import (
    CLAUDE_PLAN_REJECTED_CODE,
    PlanQuotaBook,
    crossed_warning,
    merge_snapshots,
    normalize_rate_limit_info,
    parse_rate_limit_event,
    plan_rejection_error,
)


def test_allowed_without_utilization_keeps_resets() -> None:
    info = {
        "status": "allowed",
        "resetsAt": 1774918800,
        "rateLimitType": "five_hour",
        "unifiedWindows": {
            "five_hour": {"resetsAt": 1774918800},
            "seven_day": {"resetsAt": 1775000000, "utilization": 0.8},
        },
    }
    snap = normalize_rate_limit_info(info)
    assert snap["session_percent"] is None
    assert snap["session_reset_at"] == 1774918800
    assert snap["week_percent"] == 80


def test_warning_utilization_and_crossing() -> None:
    info = {
        "status": "allowed_warning",
        "rateLimitType": "five_hour",
        "utilization": 0.9,
        "resetsAt": 1774918800,
        "unifiedWindows": {"five_hour": {"utilization": 0.9, "resetsAt": 1774918800}},
    }
    snap = normalize_rate_limit_info(info)
    assert snap["session_percent"] == 90
    assert crossed_warning({"status": "allowed"}, snap)
    assert not crossed_warning({"status": "allowed_warning"}, snap)


def test_rejected_week_window() -> None:
    info = {"status": "rejected", "rateLimitType": "seven_day", "resetsAt": 1775000000}
    snap = normalize_rate_limit_info(info)
    err = plan_rejection_error("claude", snap)
    assert err["code"] == CLAUDE_PLAN_REJECTED_CODE
    assert err["window"] == "week"
    assert err["reset_at"] == 1775000000


def test_sdk_event_parser() -> None:
    payload = {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed_warning",
            "utilization": 0.9,
            "resetsAt": 1774918800,
            "rateLimitType": "five_hour",
        },
    }
    assert parse_rate_limit_event(payload)["session_percent"] == 90


def test_book_persists_and_warns_once(tmp_path: Path) -> None:
    path = tmp_path / "plan_quota.json"
    book = PlanQuotaBook(path)
    snap = normalize_rate_limit_info(
        {"status": "allowed_warning", "utilization": 0.9, "resetsAt": 1, "rateLimitType": "five_hour"}
    )
    _, events = book.apply("claude", snap)
    assert [e["type"] for e in events] == ["plan_usage", "plan_notice"]
    _, again = book.apply("claude", merge_snapshots(snap, {"session_percent": 91}))
    assert [e["type"] for e in again] == ["plan_usage"]
    book2 = PlanQuotaBook(path)
    assert book2.get("claude")["session_percent"] == 91


def test_worker_completed_final_status() -> None:
    from app.worker_usage import worker_usage_event

    job = {
        "job_id": "j9",
        "status": "completed",
        "engine": "claude",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    assert worker_usage_event("agent_job", {}, {"content": [{"type": "text", "text": json.dumps(job)}]}) is not None


def test_worker_legacy_status_succeeded() -> None:
    from app.worker_usage import worker_usage_event

    job = {
        "job_id": "j10",
        "status": "done",
        "legacy_status": "succeeded",
        "engine": "claude",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    event = worker_usage_event("agent_job", {}, {"content": [{"type": "text", "text": json.dumps(job)}]})
    assert event and event["status"] == "succeeded"

# --- 1.6.0b16: what claude-agent-sdk 0.2.x really hands over -------------------------------------

_CLI_ALLOWED = {
    # What Claude Code 2.1.x writes after the first API answer of a turn on a Claude plan.
    "status": "allowed",
    "resetsAt": 1774918800,
    "rateLimitType": "five_hour",
    "isUsingOverage": False,
    "unifiedWindows": {
        "five_hour": {"utilization": 0.23, "resetsAt": 1774918800},
        "seven_day": {"utilization": 0.41, "resetsAt": 1775300000},
    },
}


def _sdk_event(info: dict):
    from claude_agent_sdk._internal.message_parser import parse_message

    return parse_message(
        {"type": "rate_limit_event", "rate_limit_info": info, "uuid": "u1", "session_id": "s1"}
    )


def test_real_sdk_dataclass_is_parsed() -> None:
    pytest.importorskip("claude_agent_sdk")
    from ai_workspace.app.plan_quota import parse_claude_sdk_message

    message = _sdk_event(_CLI_ALLOWED)
    assert type(message).__name__ == "RateLimitEvent"
    snap = parse_claude_sdk_message(message)
    assert snap is not None
    assert snap["status"] == "allowed"
    assert snap["session_percent"] == 23
    assert snap["week_percent"] == 41
    assert snap["session_reset_at"] == 1774918800
    assert snap["week_reset_at"] == 1775300000
    assert snap["source"] == "sdk"


def test_dataclass_without_raw_uses_typed_fields() -> None:
    from types import SimpleNamespace

    from ai_workspace.app.plan_quota import parse_claude_sdk_message

    info = SimpleNamespace(status="allowed_warning", resets_at=1774918800, rate_limit_type="five_hour", utilization=0.91, raw={})
    snap = parse_claude_sdk_message(SimpleNamespace(rate_limit_info=info, uuid="u", session_id="s"))
    assert snap["status"] == "allowed_warning"
    assert snap["session_percent"] == 91


def test_status_only_event_is_kept() -> None:
    pytest.importorskip("claude_agent_sdk")
    from ai_workspace.app.plan_quota import has_plan_data, parse_claude_sdk_message

    snap = parse_claude_sdk_message(_sdk_event({"status": "allowed"}))
    assert snap["status"] == "allowed"
    assert snap["session_percent"] is None
    assert has_plan_data(snap)


def test_other_sdk_messages_are_ignored() -> None:
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk import AssistantMessage, TextBlock

    from ai_workspace.app.plan_quota import parse_claude_sdk_message

    assert parse_claude_sdk_message(AssistantMessage(content=[TextBlock(text="hi")], model="m")) is None


def test_every_snapshot_emits_plan_usage(tmp_path: Path) -> None:
    pytest.importorskip("claude_agent_sdk")
    from ai_workspace.app.plan_quota import plan_events_from_sdk

    book = PlanQuotaBook(tmp_path / "plan_quota.json")
    events = plan_events_from_sdk(book, "claude", _sdk_event(_CLI_ALLOWED))
    assert [e["type"] for e in events] == ["plan_usage"]
    assert events[0]["session_percent"] == 23 and events[0]["week_percent"] == 41
    warn = dict(_CLI_ALLOWED, status="allowed_warning")
    events = plan_events_from_sdk(book, "claude", _sdk_event(warn))
    assert [e["type"] for e in events] == ["plan_usage", "plan_notice"]
    # Persisted across restarts.
    assert PlanQuotaBook(tmp_path / "plan_quota.json").get("claude")["week_percent"] == 41


def test_bad_message_does_not_raise(tmp_path: Path) -> None:
    from ai_workspace.app.plan_quota import plan_events_from_sdk

    class Weird:
        rate_limit_info = property(lambda self: 1 / 0)

    book = PlanQuotaBook(tmp_path / "p.json")
    assert plan_events_from_sdk(book, "claude", Weird()) == []


def test_oauth_usage_body() -> None:
    from ai_workspace.app.plan_quota import normalize_oauth_usage

    body = {
        "five_hour": {"utilization": 37.0, "resets_at": "2026-11-17T15:00:00+00:00"},
        "seven_day": {"utilization": 1.0, "resets_at": "2026-11-20T08:00:00Z"},
        "seven_day_opus": None,
    }
    snap = normalize_oauth_usage(body)
    assert snap["session_percent"] == 37
    assert snap["week_percent"] == 1  # percent, not a fraction
    from datetime import datetime, timezone

    assert snap["session_reset_at"] == int(datetime(2026, 11, 17, 15, tzinfo=timezone.utc).timestamp())
    assert snap["source"] == "usage_api"
    assert normalize_oauth_usage({}) is None


def test_zero_after_window_reset_overwrites() -> None:
    old = {"session_percent": 80, "session_reset_at": 1000}
    assert merge_snapshots(old, {"session_percent": 0, "session_reset_at": 2000})["session_percent"] == 0
    # Same window, a bare 0: partial reading, keep 80 (unless the stored reset already passed).
    future = 4_000_000_000
    kept = merge_snapshots({"session_percent": 80, "session_reset_at": future}, {"session_percent": 0})
    assert kept["session_percent"] == 80
    passed = merge_snapshots({"session_percent": 80, "session_reset_at": 1000}, {"session_percent": 0})
    assert passed["session_percent"] == 0


def test_snapshot_from_event_roundtrip() -> None:
    from ai_workspace.app.plan_quota import plan_usage_event, snapshot_from_event

    snap = normalize_rate_limit_info(_CLI_ALLOWED)
    event = plan_usage_event("claude", snap)
    back = snapshot_from_event(event)
    assert back["session_percent"] == 23 and back["week_reset_at"] == 1775300000
    assert "type" not in back and "engine" not in back


def test_sdk_shaped_dataclass_without_sdk_installed() -> None:
    """Same shape as claude_agent_sdk.RateLimitEvent / RateLimitInfo (CI has no SDK installed)."""
    from dataclasses import dataclass, field
    from typing import Any

    from ai_workspace.app.plan_quota import parse_claude_sdk_message

    @dataclass
    class RateLimitInfo:
        status: str
        resets_at: int | None = None
        rate_limit_type: str | None = None
        utilization: float | None = None
        raw: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class RateLimitEvent:
        rate_limit_info: RateLimitInfo
        uuid: str
        session_id: str

    event = RateLimitEvent(RateLimitInfo(status="allowed", resets_at=1774918800, rate_limit_type="five_hour", raw=_CLI_ALLOWED), "u", "s")
    snap = parse_claude_sdk_message(event)
    assert (snap["session_percent"], snap["week_percent"]) == (23, 41)
