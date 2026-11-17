"""Home Assistant side: plan_usage events and the Runtime pull land in the plan-quota store."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant")

from custom_components.ai_workspace import plan_quota_store as pqs  # noqa: E402
from custom_components.ai_workspace.const import DOMAIN  # noqa: E402


class FakeHass:
    def __init__(self) -> None:
        self.data: dict = {DOMAIN: {"plan_quota_loaded": True, "runtime_url": "http://runtime:8787"}}


@pytest.fixture
def hass(monkeypatch):
    saved: list[dict] = []

    async def save(_hass, engines):
        saved.append(dict(engines))

    monkeypatch.setattr(pqs, "async_save_plan_quota", save)
    monkeypatch.setattr(pqs, "_signal", lambda _hass: None)
    h = FakeHass()
    h.saved = saved
    return h


def test_plan_usage_event_is_stored(hass) -> None:
    from custom_components.ai_workspace.http import _ingest_runtime_plan_event

    event = {
        "type": "plan_usage",
        "engine": "claude",
        "status": "allowed",
        "session_percent": 23,
        "week_percent": 41,
        "session_reset_at": 1774918800,
        "week_reset_at": 1775300000,
        "source": "sdk",
        "updated_at": "2026-11-17T10:00:00+00:00",
    }
    asyncio.run(_ingest_runtime_plan_event(hass, event))
    snap = pqs.public_plan_quota(hass)["claude"]
    assert snap["session_percent"] == 23 and snap["week_percent"] == 41 and snap["status"] == "allowed"
    assert hass.saved


def test_usage_page_pulls_runtime(hass, monkeypatch) -> None:
    calls: list[str] = []

    async def health(_hass, base):
        calls.append(base)
        return {"plan_quota": {"claude": {"session_percent": 5, "week_percent": 9, "source": "usage_api"}}}

    from custom_components.ai_workspace import discovery

    monkeypatch.setattr(discovery, "async_runtime_health", health)
    asyncio.run(pqs.async_refresh_runtime_plan_quota(hass))
    asyncio.run(pqs.async_refresh_runtime_plan_quota(hass))  # throttled
    assert calls == ["http://runtime:8787"]
    assert pqs.public_plan_quota(hass)["claude"]["week_percent"] == 9


def test_pull_without_runtime_is_quiet(hass) -> None:
    hass.data[DOMAIN]["runtime_url"] = ""
    asyncio.run(pqs.async_refresh_runtime_plan_quota(hass))
    assert pqs.public_plan_quota(hass) == {}
