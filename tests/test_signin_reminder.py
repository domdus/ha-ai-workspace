"""Repair notice before the Runtime's Claude plan sign-in (setup-token, one year) runs out."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

reminder = pytest.importorskip("custom_components.ai_workspace.signin_reminder")

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _status(expires: str, credential: str = "signed-in") -> dict:
    return {"credential": credential, "signed_in": {"saved_at": "2025-12-10T09:00:00+00:00", "expires_at": expires}}


def test_days_left_only_for_a_sign_in_on_the_runtime() -> None:
    assert reminder.days_left(_status("2026-12-10T09:00:00+00:00"), NOW) == (12, "2026-12-10")
    assert reminder.days_left(_status("2026-11-20T09:00:00+00:00"), NOW)[0] < 0
    assert reminder.days_left(_status("2027-06-01T00:00:00"), NOW)[0] > reminder.WARN_DAYS
    # A token from the environment or an API key has no date we know.
    assert reminder.days_left(_status("2026-12-10T09:00:00+00:00", "settings"), NOW) is None
    assert reminder.days_left({"credential": "signed-in", "signed_in": None}, NOW) is None
    assert reminder.days_left(None, NOW) is None


class FakeIssues:
    def __init__(self, monkeypatch) -> None:
        self.open: dict[str, dict] = {}
        monkeypatch.setattr(reminder.ir, "async_create_issue", self.create)
        monkeypatch.setattr(reminder.ir, "async_delete_issue", self.delete)

    def create(self, hass, domain, issue_id, **kwargs) -> None:
        self.open[issue_id] = kwargs

    def delete(self, hass, domain, issue_id) -> None:
        self.open.pop(issue_id, None)


def test_notice_from_thirty_days_before_and_gone_after_a_new_sign_in(monkeypatch) -> None:
    issues = FakeIssues(monkeypatch)
    hass = SimpleNamespace(data={})
    reminder.update_issue(hass, (40, "2027-01-06"))
    assert issues.open == {}
    reminder.update_issue(hass, (12, "2026-12-10"))
    shown = issues.open[reminder.ISSUE_ID]
    assert shown["translation_placeholders"] == {"date": "2026-12-10", "days": "12"}
    assert shown["severity"] == reminder.ir.IssueSeverity.WARNING and not shown["is_fixable"]
    reminder.update_issue(hass, (-3, "2026-11-24"))
    assert issues.open[reminder.ISSUE_ID]["severity"] == reminder.ir.IssueSeverity.ERROR
    assert issues.open[reminder.ISSUE_ID]["translation_placeholders"]["days"] == "0"
    reminder.signed_in_again(hass)
    assert issues.open == {}


def test_check_reads_the_runtime_at_most_every_few_hours(monkeypatch) -> None:
    issues = FakeIssues(monkeypatch)
    calls: list[str] = []

    async def status(hass, base, token, engine):
        calls.append(engine)
        return _status("2026-12-01T00:00:00+00:00")

    from custom_components.ai_workspace import runtime_auth

    monkeypatch.setattr(runtime_auth, "async_auth_status", status)
    hass = SimpleNamespace(data={})
    data = {"providers": {"a1": SimpleNamespace(kind="claude")}}

    async def run():
        await reminder.async_check_claude_signin(hass, data, "http://rt:8090", "tok")
        await reminder.async_check_claude_signin(hass, data, "http://rt:8090", "tok")

    asyncio.run(run())
    assert calls == ["claude"] and reminder.ISSUE_ID in issues.open
    # No Claude (runtime) agent left: the notice goes, nothing is asked.
    asyncio.run(reminder.async_check_claude_signin(hass, {"providers": {}}, "http://rt:8090", "tok"))
    assert issues.open == {} and calls == ["claude"]


def test_a_runtime_that_cannot_answer_changes_nothing(monkeypatch) -> None:
    issues = FakeIssues(monkeypatch)
    issues.open[reminder.ISSUE_ID] = {"kept": True}

    async def broken(hass, base, token, engine):
        raise OSError("down")

    from custom_components.ai_workspace import runtime_auth

    monkeypatch.setattr(runtime_auth, "async_auth_status", broken)
    hass = SimpleNamespace(data={})
    asyncio.run(
        reminder.async_check_claude_signin(hass, {"providers": {"a": SimpleNamespace(kind="claude")}}, "u", "t")
    )
    assert issues.open == {reminder.ISSUE_ID: {"kept": True}}
