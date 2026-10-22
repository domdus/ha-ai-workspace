from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import replace

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ADDON_PORT,
    ADDON_SLUG,
    COMPOSE_RUNTIME_URLS,
    CONF_RUNTIME_TOKEN,
    CONF_RUNTIME_URL,
    CONF_SHORTEN_MCP_RESULTS,
    CONF_CHANGE_HISTORY,
    DOMAIN,
    HOST_RUNTIME_URL,
)

MISSING_RUNTIME = "Start the Cursor SDK Runtime and set its URL on the Cursor agent."
BAD_TOKEN = (
    "The Cursor SDK Runtime refused the token. Set the same Runtime token on the Runtime "
    "and on AI Workspace (Configure)."
)
PAIRING = "Pairing with the AI Workspace Runtime app. Try again in a minute."

_LOGGER = logging.getLogger(__name__)
_HASS_URL_OPTION = "hass_url"
_SHORTEN_OPTION = "shorten_mcp_results"
_HISTORY_OPTION = "change_history"
_PROBE_COOLDOWN = 30.0
_PAIR_WAIT = 90.0


def _slug_matches(slug: str) -> bool:
    name = slug.replace("-", "_")
    return name == ADDON_SLUG or name.endswith(f"_{ADDON_SLUG}")


def _hassio_addon(hass: HomeAssistant) -> tuple[str, str] | None:
    """Slug and URL of the running Runtime app."""
    try:
        from homeassistant.components.hassio import get_addons_info
    except ImportError:
        return None
    try:
        addons = get_addons_info(hass)
    except Exception:
        return None
    for slug, info in (addons or {}).items():
        if not info or not _slug_matches(str(slug)):
            continue
        state = str(info.get("state") or "").lower()
        if state not in {"started", "running"}:
            _LOGGER.debug("AI Workspace add-on %s is %s", slug, state)
            continue
        hostname = info.get("hostname") or str(slug).replace("_", "-")
        return str(slug), f"http://{hostname}:{ADDON_PORT}"
    return None


def hassio_runtime_url(hass: HomeAssistant) -> str | None:
    found = _hassio_addon(hass)
    return found[1] if found else None


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def async_probe_runtime(hass: HomeAssistant, base: str) -> bool:
    return await async_runtime_health(hass, base) is not None


async def async_runtime_health(hass: HomeAssistant, base: str) -> dict | None:
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(f"{base.rstrip('/')}/api/health", timeout=ClientTimeout(total=3))
    except (ClientError, TimeoutError, OSError):
        return None
    try:
        if resp.status != 200:
            return None
        body = await resp.json(content_type=None)
    except (ClientError, ValueError):
        return None
    finally:
        resp.release()
    return body if isinstance(body, dict) else {}


async def async_token_accepted(hass: HomeAssistant, base: str, token: str) -> bool:
    session = async_get_clientsession(hass)
    try:
        resp = await session.get(
            f"{base.rstrip('/')}/api/providers",
            headers=_auth(token),
            timeout=ClientTimeout(total=5),
        )
    except (ClientError, TimeoutError, OSError):
        return False
    status = resp.status
    resp.release()
    return status != 401


def _same_runtime_url(left: str, right: str) -> bool:
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


async def async_detect_runtime_url(hass: HomeAssistant) -> str:
    """Return a Runtime URL only when /api/health answered. No compose-name guesses."""
    found = hassio_runtime_url(hass)
    for candidate in (found, HOST_RUNTIME_URL, *COMPOSE_RUNTIME_URLS):
        if not candidate:
            continue
        if os.environ.get("SUPERVISOR_TOKEN") and candidate in COMPOSE_RUNTIME_URLS:
            continue
        if await async_probe_runtime(hass, candidate):
            _LOGGER.info("AI Workspace runtime using %s", candidate)
            return candidate.rstrip("/")
    return ""


async def async_resolve_runtime_url(hass: HomeAssistant, configured: str) -> str:
    configured = str(configured or "").strip().rstrip("/")
    if configured and await async_probe_runtime(hass, configured):
        return configured
    detected = await async_detect_runtime_url(hass)
    if detected:
        return detected
    if configured:
        _LOGGER.warning("AI Workspace runtime at %s did not answer", configured)
        return configured
    return hassio_runtime_url(hass) or ""


def runtime_form_placeholders(*, live: bool, auto: bool) -> dict[str, str]:
    if live:
        note = "✅ Runtime found."
    elif auto:
        note = "We found your Cursor runtime on this system."
    else:
        note = (
            "Address of your Cursor runtime, as seen from Home Assistant. "
            "Leave empty to auto-detect when the runtime is reachable."
        )
    return {
        "runtime_url_mark": " · auto-detected" if auto and live else "",
        "runtime_url_note": note,
    }


async def async_runtime_form_url(hass: HomeAssistant, saved: str) -> tuple[str, bool, bool]:
    """URL to show on the Cursor form: fill from detection only when health answers."""
    saved = str(saved or "").strip().rstrip("/")
    detected = await async_detect_runtime_url(hass)
    saved_live = bool(saved) and await async_probe_runtime(hass, saved)
    if saved_live:
        return saved, True, bool(detected) and _same_runtime_url(saved, detected)
    if detected:
        return detected, True, True
    return saved, False, False


def _entry_value(entry, key: str) -> str:
    if entry is None:
        return ""
    blob = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
    return str(blob.get(key) or "").strip()


async def _async_addon_token(hass: HomeAssistant, slug: str) -> str:
    from homeassistant.components.hassio import AddonError, AddonManager

    try:
        info = await AddonManager(hass, _LOGGER, "AI Workspace Runtime", slug).async_get_addon_info()
    except AddonError:
        return ""
    return str((info.options or {}).get(CONF_RUNTIME_TOKEN) or "").strip()


def _shorten_mcp_results(hass: HomeAssistant) -> bool:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    if settings is None:
        return True
    return bool(getattr(settings, CONF_SHORTEN_MCP_RESULTS, True))


def _change_history(hass: HomeAssistant) -> bool:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    if settings is None:
        return True
    return bool(getattr(settings, CONF_CHANGE_HISTORY, True))


def _sync_runtime_options(hass: HomeAssistant, opts: dict) -> bool:
    wanted_url = _runtime_hass_url(hass)
    wanted_shorten = _shorten_mcp_results(hass)
    wanted_history = _change_history(hass)
    changed = False
    if str(opts.get(_HASS_URL_OPTION) or "").rstrip("/") != wanted_url:
        opts[_HASS_URL_OPTION] = wanted_url
        changed = True
    current = opts.get(_SHORTEN_OPTION)
    if current is None or bool(current) != wanted_shorten:
        opts[_SHORTEN_OPTION] = wanted_shorten
        changed = True
    current_history = opts.get(_HISTORY_OPTION)
    if current_history is None or bool(current_history) != wanted_history:
        opts[_HISTORY_OPTION] = wanted_history
        changed = True
    return changed


def _on_supervisor(hass: HomeAssistant) -> bool:
    try:
        from homeassistant.components.hassio import is_hassio

        return bool(is_hassio(hass))
    except Exception:
        return hass.data.get("hassio") is not None


def _runtime_hass_url(hass: HomeAssistant) -> str:
    # The Runtime add-on is not on the host network. 127.0.0.1 inside that
    # container is the add-on, not Core, so Change History callbacks never land.
    if _on_supervisor(hass):
        api = getattr(hass.config, "api", None)
        port = int(getattr(api, "port", None) or 8123)
        return f"http://homeassistant:{port}"
    try:
        from homeassistant.helpers.network import NoURLAvailableError, get_url

        return str(
            get_url(hass, allow_internal=True, allow_external=False, allow_ip=True, prefer_external=False)
        ).rstrip("/")
    except (ImportError, NoURLAvailableError):
        pass
    api = getattr(hass.config, "api", None)
    port = int(getattr(api, "port", None) or 8123)
    tls = bool(getattr(api, "use_ssl", False))
    scheme = "https" if tls else "http"
    return f"{scheme}://127.0.0.1:{port}"


async def _async_pair_addon(hass: HomeAssistant, slug: str, base: str) -> str:
    """Give the Runtime app a token through the Supervisor, the way Z-Wave JS sets its keys."""
    from homeassistant.components.hassio import AddonError, AddonManager

    manager = AddonManager(hass, _LOGGER, "AI Workspace Runtime", slug)
    try:
        info = await manager.async_get_addon_info()
        token = str((info.options or {}).get(CONF_RUNTIME_TOKEN) or "").strip()
        if token and await async_token_accepted(hass, base, token):
            opts = dict(info.options or {})
            if _sync_runtime_options(hass, opts):
                try:
                    await manager.async_set_addon_options(opts)
                except AddonError:
                    pass
            return token
        if not token:
            token = secrets.token_urlsafe(32)
            opts = {
                **(info.options or {}),
                CONF_RUNTIME_TOKEN: token,
            }
            _sync_runtime_options(hass, opts)
            await manager.async_set_addon_options(opts)
        _LOGGER.info("Restarting the AI Workspace Runtime app so it picks up its token")
        await manager.async_restart_addon()
    except AddonError as exc:
        _LOGGER.warning("Could not pair with the AI Workspace Runtime app: %s", exc)
        return ""
    deadline = time.monotonic() + _PAIR_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        if await async_token_accepted(hass, base, token):
            return token
    _LOGGER.warning("The AI Workspace Runtime app did not come back with its token")
    return token


def apply_runtime_to_providers(bucket: dict, runtime_url: str, reason: str | None = None) -> None:
    bucket["runtime_url"] = runtime_url
    if not runtime_url and reason is None:
        reason = MISSING_RUNTIME
    for item in (bucket.get("providers") or {}).values():
        if getattr(item, "kind", "") != "cursor":
            continue
        info = item.info
        available = reason is None
        if bool(info.available) == available and info.reason == reason:
            continue
        item.info = replace(info, available=available, reason=reason)


def _needs_cursor(bucket: dict) -> bool:
    return any(getattr(item, "kind", "") == "cursor" for item in (bucket.get("providers") or {}).values())


async def async_bind_runtime(hass: HomeAssistant, bucket: dict | None = None, *, force: bool = False) -> str:
    """Find the Runtime, make sure it accepts our token, and mark Cursor agents."""
    data = bucket if bucket is not None else hass.data.get(DOMAIN)
    if not data:
        return ""
    now = time.monotonic()
    previous = str(data.get("runtime_url") or "")
    if not force and previous and now - float(data.get("runtime_checked") or 0) < _PROBE_COOLDOWN:
        return previous
    data["runtime_checked"] = now
    entry = data.get("entry")
    url = await async_resolve_runtime_url(hass, _entry_value(entry, CONF_RUNTIME_URL))
    if not url:
        apply_runtime_to_providers(data, "")
        return ""
    health = await async_runtime_health(hass, url)
    if health is None:
        apply_runtime_to_providers(data, url, MISSING_RUNTIME)
        return url
    token = _entry_value(entry, CONF_RUNTIME_TOKEN) or str(data.get("runtime_token") or "")
    reason: str | None = None
    if health.get("token_required") or token:
        accepted = bool(token) and await async_token_accepted(hass, url, token)
        addon = _hassio_addon(hass)
        own_addon = bool(addon) and addon[1] == url and not _entry_value(entry, CONF_RUNTIME_TOKEN)
        if not accepted and own_addon:
            stored = await _async_addon_token(hass, addon[0])
            if stored and await async_token_accepted(hass, url, stored):
                token, accepted = stored, True
        if not accepted:
            if own_addon:
                reason = PAIRING
                if not data.get("pairing") and _needs_cursor(data):
                    data["pairing"] = True
                    hass.async_create_background_task(
                        _async_finish_pairing(hass, data, addon[0], url), "ai_workspace_pair_runtime"
                    )
            else:
                reason = BAD_TOKEN
    data["runtime_token"] = token
    apply_runtime_to_providers(data, url, reason)
    if url != previous:
        _LOGGER.info("AI Workspace Cursor Runtime at %s", url)
    return url


async def _async_finish_pairing(hass: HomeAssistant, data: dict, slug: str, url: str) -> None:
    try:
        token = await _async_pair_addon(hass, slug, url)
    finally:
        data["pairing"] = False
    if token:
        data["runtime_token"] = token
    ok = bool(token) and await async_token_accepted(hass, url, token)
    apply_runtime_to_providers(data, url, None if ok else BAD_TOKEN)


async def async_retry_runtime(hass: HomeAssistant, bucket: dict) -> None:
    """Keep probing after startup so a late Docker runtime still clears the Cursor banner."""
    for delay in (2, 5, 10, 20):
        if not _needs_cursor(bucket):
            return
        if str(bucket.get("runtime_url") or "") and all(
            item.info.available
            for item in (bucket.get("providers") or {}).values()
            if getattr(item, "kind", "") == "cursor"
        ):
            return
        await asyncio.sleep(delay)
        if hass.data.get(DOMAIN) is not bucket:
            return
        await async_bind_runtime(hass, bucket, force=True)
