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
    assert len(events) == 1
    _, again = book.apply("claude", merge_snapshots(snap, {"session_percent": 91}))
    assert again == []
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