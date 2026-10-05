from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ADDON_PORT, ADDON_SLUG, COMPOSE_RUNTIME_URL

_LOGGER = logging.getLogger(__name__)


def _slug_matches(slug: str) -> bool:
    name = slug.replace("-", "_")
    return name == ADDON_SLUG or name.endswith(f"_{ADDON_SLUG}")


def hassio_runtime_url(hass: HomeAssistant) -> str | None:
    try:
        from homeassistant.components.hassio import get_addons_info
    except ImportError:
        return None
    try:
        addons = get_addons_info(hass)
    except Exception:
        return None
    if not addons:
        return None
    for slug, info in addons.items():
        if not info or not _slug_matches(str(slug)):
            continue
        state = str(info.get("state") or "").lower()
        if state not in {"started", "running"}:
            _LOGGER.debug("AI Workspace add-on %s is %s", slug, state)
            continue
        hostname = info.get("hostname") or str(slug).replace("_", "-")
        return f"http://{hostname}:{ADDON_PORT}"
    return None


async def async_probe_runtime(hass: HomeAssistant, base: str) -> bool:
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(
            f"{base.rstrip('/')}/api/health",
            timeout=ClientTimeout(total=3),
        )
    except (ClientError, TimeoutError, OSError):
        return False
    ok = resp.status == 200
    resp.release()
    return ok


async def async_resolve_runtime_url(hass: HomeAssistant, configured: str) -> str:
    if configured:
        return configured.rstrip("/")
    found = hassio_runtime_url(hass)
    if found and await async_probe_runtime(hass, found):
        return found
    if not os.environ.get("SUPERVISOR_TOKEN") and Path("/.dockerenv").exists():
        if await async_probe_runtime(hass, COMPOSE_RUNTIME_URL):
            return COMPOSE_RUNTIME_URL
    return found or ""

