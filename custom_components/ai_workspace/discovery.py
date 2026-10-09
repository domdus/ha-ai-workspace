from __future__ import annotations

import logging
import os

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ADDON_PORT,
    ADDON_SLUG,
    COMPOSE_RUNTIME_URLS,
    CONF_RUNTIME_URL,
    DOMAIN,
    HOST_RUNTIME_URL,
)
from .models import ProviderInfo

MISSING_RUNTIME = "Start the Cursor SDK Runtime and set its URL on AI Workspace."

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
    for candidate in (found, HOST_RUNTIME_URL, *COMPOSE_RUNTIME_URLS):
        if not candidate:
            continue
        if os.environ.get("SUPERVISOR_TOKEN") and candidate in COMPOSE_RUNTIME_URLS:
            continue
        if await async_probe_runtime(hass, candidate):
            _LOGGER.info("AI Workspace runtime using %s", candidate)
            return candidate
    return found or ""


def _configured_runtime(entry) -> str:
    if entry is None:
        return ""
    blob = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
    return str(blob.get(CONF_RUNTIME_URL) or "").strip().rstrip("/")


def apply_runtime_to_providers(bucket: dict, runtime_url: str) -> None:
    bucket["runtime_url"] = runtime_url
    reason = None if runtime_url else MISSING_RUNTIME
    for item in (bucket.get("providers") or {}).values():
        if getattr(item, "kind", "") != "cursor":
            continue
        info = item.info
        if bool(info.available) == bool(runtime_url) and info.reason == reason:
            continue
        item.info = ProviderInfo(info.id, info.label, bool(runtime_url), reason)


async def async_bind_runtime(hass: HomeAssistant, bucket: dict | None = None) -> str:
    """Probe the Runtime (including an empty URL = auto-detect) and mark Cursor agents."""
    data = bucket if bucket is not None else hass.data.get(DOMAIN)
    if not data:
        return ""
    previous = str(data.get("runtime_url") or "")
    url = await async_resolve_runtime_url(hass, _configured_runtime(data.get("entry")))
    apply_runtime_to_providers(data, url)
    if url and url != previous:
        _LOGGER.info("AI Workspace Cursor Runtime at %s", url)
    return url

