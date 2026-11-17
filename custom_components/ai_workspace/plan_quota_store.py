"""Home Assistant persistence for plan-quota snapshots."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN
from .plan_quota import ENGINES, merge_snapshots

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.plan_quota"
SIGNAL_PLAN_QUOTA_UPDATE = f"{DOMAIN}_plan_quota_update"


def _store(hass: HomeAssistant):
    from homeassistant.helpers.storage import Store

    return Store(hass, STORAGE_VERSION, STORAGE_KEY)


async def async_load_plan_quota(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    data = await _store(hass).async_load()
    if not isinstance(data, dict):
        return {}
    engines = data.get("engines")
    if not isinstance(engines, dict):
        return {}
    return {str(k): v for k, v in engines.items() if isinstance(v, dict)}


async def async_save_plan_quota(hass: HomeAssistant, engines: dict[str, dict[str, Any]]) -> None:
    await _store(hass).async_save({"engines": engines})


def plan_quota_cache(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    bucket = hass.data.setdefault(DOMAIN, {})
    cached = bucket.get("plan_quota")
    if isinstance(cached, dict):
        return cached
    bucket["plan_quota"] = {}
    return bucket["plan_quota"]


async def async_ensure_plan_quota(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    cached = plan_quota_cache(hass)
    if cached or bucket_loaded(hass):
        return cached
    engines = await async_load_plan_quota(hass)
    cached.clear()
    cached.update(engines)
    return cached


def bucket_loaded(hass: HomeAssistant) -> bool:
    return bool((hass.data.get(DOMAIN) or {}).get("plan_quota_loaded"))


async def async_init_plan_quota(hass: HomeAssistant) -> None:
    engines = await async_load_plan_quota(hass)
    cached = plan_quota_cache(hass)
    cached.clear()
    cached.update(engines)
    hass.data[DOMAIN]["plan_quota_loaded"] = True


@callback
def _signal(hass: HomeAssistant) -> None:
    async_dispatcher_send(hass, SIGNAL_PLAN_QUOTA_UPDATE)


async def async_merge_plan_quota(hass: HomeAssistant, engine: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    engine = str(engine or "").strip().lower()
    if engine not in ENGINES:
        return snapshot
    await async_ensure_plan_quota(hass)
    cached = plan_quota_cache(hass)
    merged = merge_snapshots(cached.get(engine), snapshot)
    if merged == cached.get(engine):
        return merged
    cached[engine] = merged
    await async_save_plan_quota(hass, dict(cached))
    _signal(hass)
    return merged


async def async_merge_runtime_plan_quota(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    changed = False
    await async_ensure_plan_quota(hass)
    cached = plan_quota_cache(hass)
    for engine in ENGINES:
        snap = payload.get(engine)
        if not isinstance(snap, dict):
            continue
        merged = merge_snapshots(cached.get(engine), snap)
        if merged != cached.get(engine):
            cached[engine] = merged
            changed = True
    if changed:
        await async_save_plan_quota(hass, dict(cached))
        _signal(hass)


def public_plan_quota(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    cached = plan_quota_cache(hass)
    return {engine: dict(cached[engine]) for engine in ENGINES if engine in cached}

_REFRESH_EVERY = 30.0


async def async_refresh_runtime_plan_quota(hass: HomeAssistant) -> None:
    """Pull the Runtime's latest plan snapshots (from /api/health) when the Usage page opens.

    The chat stream already carries them (plan_usage events); this also picks up what the Runtime
    read on its own after a turn (app.claude_usage) and what came in while HA was not listening.
    """
    import time

    bucket = hass.data.get(DOMAIN) or {}
    base = str(bucket.get("runtime_url") or "")
    if not base:
        return
    now = time.monotonic()
    if now - float(bucket.get("plan_quota_pulled") or 0) < _REFRESH_EVERY:
        return
    bucket["plan_quota_pulled"] = now
    from .discovery import async_runtime_health

    try:
        health = await async_runtime_health(hass, base)
        payload = (health or {}).get("plan_quota")
        if isinstance(payload, dict) and payload:
            await async_merge_runtime_plan_quota(hass, payload)
    except Exception:  # noqa: BLE001 - the Usage page must open without the Runtime.
        _LOGGER.debug("Runtime plan quota not pulled", exc_info=True)
