"""The no-token plan usage read (GET /api/oauth/usage) and when the Claude provider uses it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ai_workspace.app.claude_usage import BACKOFF, MIN_INTERVAL, ClaudeUsageReader
from ai_workspace.app.plan_quota import PlanQuotaBook


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_read_is_throttled_and_stored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PLAN_USAGE_READ", "on")
    calls: list[str] = []

    def getter(token: str):
        calls.append(token)
        return 200, {"five_hour": {"utilization": 12, "resets_at": "2026-11-17T15:00:00Z"}, "seven_day": {"utilization": 55, "resets_at": None}}

    clock = Clock()
    reader = ClaudeUsageReader(getter=getter, clock=clock)
    book = PlanQuotaBook(tmp_path / "plan_quota.json")

    async def run() -> None:
        reader.refresh_in_background(book, "sk-ant-oat01-x")
        await reader._task
        reader.refresh_in_background(book, "sk-ant-oat01-x")  # within MIN_INTERVAL: no second call
        assert reader._task.done()

    asyncio.run(run())
    assert calls == ["sk-ant-oat01-x"]
    snap = book.get("claude")
    assert snap["session_percent"] == 12 and snap["week_percent"] == 55 and snap["source"] == "usage_api"
    clock.now += MIN_INTERVAL + 1
    assert reader.due()


def test_scope_error_backs_off(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PLAN_USAGE_READ", "on")
    clock = Clock()
    reader = ClaudeUsageReader(getter=lambda token: (403, None), clock=clock)
    assert asyncio.run(reader.read("t")) is None
    clock.now += MIN_INTERVAL + 1
    assert not reader.due()
    clock.now += BACKOFF
    assert reader.due()


def test_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PLAN_USAGE_READ", "off")
    assert not ClaudeUsageReader(getter=lambda t: (200, {})).due()
