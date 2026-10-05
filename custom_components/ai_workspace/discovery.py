from __future__ import annotations

import logging
import os

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import ADDON_PORT, ADDON_SLUG, COMPOSE_RUNTIME_URL, HOST_RUNTIME_URL

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
        base = configured.rstrip("/")
        if await async_probe_runtime(hass, base):
            return base
        _LOGGER.warning("AI Workspace runtime at %s did not answer", base)
        return base
    found = hassio_runtime_url(hass)
    for candidate in (found, HOST_RUNTIME_URL, COMPOSE_RUNTIME_URL):
        if not candidate:
            continue
        if os.environ.get("SUPERVISOR_TOKEN") and candidate == COMPOSE_RUNTIME_URL:
            continue
        if await async_probe_runtime(hass, candidate):
            _LOGGER.info("AI Workspace runtime using %s", candidate)
            return candidate
    return found or ""

