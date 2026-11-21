"""Hub refreshes never write state of sensors that are not (or no longer) added to hass."""

import asyncio
from types import SimpleNamespace

from custom_components.ai_workspace import sensor


class _Hass:
    """Enough of hass for the hub: no dispatcher calls, executor runs inline."""

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _entry():
    return SimpleNamespace(entry_id="e1")


def _plan_sensor(hass, hub):
    return sensor.PlanQuotaSensor(hass, _entry(), hub, "claude", "claude_week_percent", "Claude plan week %", "week_percent")


def _added(entity, entity_id):
    written = []
    entity.entity_id = entity_id
    entity.async_write_ha_state = lambda: written.append(entity.native_value)
    return written


def test_plan_refresh_skips_and_drops_aborted_entity(monkeypatch) -> None:
    hass = _Hass()
    hub = sensor.PlanQuotaHub(hass)
    monkeypatch.setattr(sensor, "public_plan_quota", lambda hass: {"claude": {"week_percent": 42}})
    live = _plan_sensor(hass, hub)
    written = _added(live, "sensor.claude_plan_week")
    # Created and attached, but HA aborted the add: hass is None, no entity_id.
    ghost = _plan_sensor(hass, hub)
    ghost.hass = None
    hub.attach(live)
    hub.attach(ghost)
    asyncio.run(hub.refresh())  # used to raise "Attribute hass is None for <entity unknown.unknown=unknown>"
    assert written == [42]
    assert hub._entities == [live]


def test_never_added_entity_does_not_write() -> None:
    hass = _Hass()
    hub = sensor.PlanQuotaHub(hass)
    entity = _plan_sensor(hass, hub)  # hass set in __init__, but no entity_id: not added yet
    entity.apply_hub()  # no RuntimeError


def test_abort_and_remove_detach_from_hub(monkeypatch) -> None:
    hass = _Hass()
    hub = sensor.PlanQuotaHub(hass)

    async def no_setup():
        return None

    monkeypatch.setattr(hub, "async_setup", no_setup)
    first, second = _plan_sensor(hass, hub), _plan_sensor(hass, hub)
    _added(first, "sensor.a")
    _added(second, "sensor.b")
    hub._unsub.append(lambda: None)
    asyncio.run(first.async_added_to_hass())
    asyncio.run(second.async_added_to_hass())
    assert hub._entities == [first, second]
    # HA aborts the add (async_will_remove_from_hass is not called on this path).
    first.add_to_platform_abort()
    assert hub._entities == [second]
    assert hub._unsub, "the other sensor still listens"
    second._call_on_remove_callbacks()
    assert hub._entities == [] and hub._unsub == []


def test_usage_refresh_skips_removed_entity(monkeypatch) -> None:
    class _Store:
        def summarize_usage(self, **kwargs):
            return {"cost_usd": 1.5, "total_tokens": 10, "turns": 1}

        def last_usage(self, **kwargs):
            return None

        def usage_by_agent(self, **kwargs):
            return []

    hass = _Hass()
    hub = sensor.UsageHub(hass, _Store(), [])
    monkeypatch.setattr(sensor, "day_bounds", lambda hass: (0, 1, 0))
    live = sensor.WorkspaceUsageSensor(hass, _entry(), hub, "cost_today", "Cost today", "cost", "today")
    written = _added(live, "sensor.cost_today")
    gone = sensor.WorkspaceUsageSensor(hass, _entry(), hub, "cost_month", "Cost this month", "cost", "month")
    _added(gone, "sensor.cost_month")
    gone.add_to_platform_abort()
    hub.attach(live)
    hub.attach(gone)
    asyncio.run(hub.refresh())
    assert written == [1.5]
    assert hub._entities == [live]
