from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_CURSOR_API_KEY,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_MCP_KIND,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_URL,
    CONF_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    DOMAIN,
    MODE_API,
    MODE_CURSOR,
    OVERLAY_JS,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_URL,
    STATIC_URL,
)
from .discovery import async_resolve_runtime_url
from .http import register_views
from .mcp_config import mcp_servers_from_url
from .mcp_resolve import async_resolve_mcp_url, mcp_kind_of
from .models import Settings

_LOGGER = logging.getLogger(__name__)

_MISSING_RUNTIME = (
    "Start the AI Workspace Runtime app, or configure Chat Backend as "
    "Cloud API Provider with an API key and MCP."
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_MCP_URL, default=""): cv.string,
                vol.Optional(CONF_MCP_KIND, default=""): cv.string,
                vol.Optional(CONF_MCP_TOKEN, default=""): cv.string,
                vol.Optional(CONF_CURSOR_API_KEY, default=""): cv.string,
                vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): cv.string,
                vol.Optional(CONF_RUNTIME_URL, default=""): cv.string,
                vol.Optional(CONF_MODE, default=""): cv.string,
                vol.Optional(CONF_API_PROVIDER, default="openai"): cv.string,
                vol.Optional(CONF_API_KEY, default=""): cv.string,
                vol.Optional(CONF_API_BASE, default=""): cv.string,
                vol.Optional(CONF_SYSTEM_PROMPT, default=""): cv.string,
                vol.Optional(CONF_ENABLE_SIDEBAR, default=True): cv.boolean,
                vol.Optional(CONF_ENABLE_OVERLAY, default=True): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def _merged(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


def _mode(data: dict) -> str:
    configured = str(data.get(CONF_MODE) or "").strip()
    if configured in {MODE_API, MODE_CURSOR}:
        return configured
    return MODE_CURSOR if str(data.get(CONF_RUNTIME_URL) or "").strip() else MODE_API


def _model_for_mode(data: dict) -> str:
    model = str(data.get(CONF_MODEL) or "").strip()
    mode = _mode(data)
    if mode == MODE_CURSOR:
        return model or DEFAULT_MODEL
    if not model or model == DEFAULT_MODEL:
        return ""
    return model


def _settings(hass: HomeAssistant, entry: ConfigEntry, mcp_url: str | None = None) -> Settings:
    data = _merged(entry)
    root = Path(hass.config.path(DOMAIN))
    token = str(data.get(CONF_MCP_TOKEN) or "").strip()
    configured = str(data.get(CONF_MCP_URL) or "").strip()
    return Settings(
        data_dir=root,
        workspace_dir=root / "workspace",
        state_dir=root / "cursor-state",
        cursor_api_key=str(data.get(CONF_CURSOR_API_KEY) or "").strip(),
        model=_model_for_mode(data),
        mcp_kind=mcp_kind_of(data),
        mcp_token=token,
        mcp_servers=mcp_servers_from_url(mcp_url if mcp_url is not None else configured, token),
        enable_overlay=bool(data.get(CONF_ENABLE_OVERLAY, True)),
        enable_sidebar=bool(data.get(CONF_ENABLE_SIDEBAR, True)),
        mode=_mode(data),
        api_provider=str(data.get(CONF_API_PROVIDER) or "openai").strip() or "openai",
        api_key=str(data.get(CONF_API_KEY) or "").strip(),
        api_base=str(data.get(CONF_API_BASE) or "").strip(),
        system_prompt=str(data.get(CONF_SYSTEM_PROMPT) or "").strip(),
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = _merged(entry)
    mcp_url = await async_resolve_mcp_url(
        hass,
        mcp_kind_of(data),
        str(data.get(CONF_MCP_URL) or "").strip(),
        str(data.get(CONF_MCP_TOKEN) or "").strip(),
    )
    settings = _settings(hass, entry, mcp_url)
    mode = settings.mode
    configured = str(data.get(CONF_RUNTIME_URL) or "").strip().rstrip("/")
    runtime_url = ""
    if mode == MODE_CURSOR:
        runtime_url = await async_resolve_runtime_url(hass, configured)
    hass.data[DOMAIN] = {
        "entry": entry,
        "settings": settings,
        "mode": mode,
        "runtime_url": runtime_url,
        "runtime": None,
        "store": None,
        "providers": {},
        "locks": {},
    }

    if not hass.data.get(f"{DOMAIN}_http"):
        register_views(hass)
        hass.data[f"{DOMAIN}_http"] = True

    if mode == MODE_API:
        from .api_provider import ApiProvider
        from .store import Store

        await hass.async_add_executor_job(settings.ensure_dirs)
        store = await hass.async_add_executor_job(Store, settings.data_dir / "ai-workspace.sqlite")
        provider = ApiProvider(hass, settings, store)
        hass.data[DOMAIN].update({"store": store, "providers": {"api": provider}, "locks": {}})
        _LOGGER.info("AI Workspace using API provider %s", settings.api_provider)
    elif runtime_url:
        _LOGGER.info("AI Workspace chat API proxied to %s", runtime_url)
    else:
        try:
            import cursor_sdk  # noqa: F401
        except ImportError as exc:
            raise ConfigEntryError(_MISSING_RUNTIME) from exc
        from .cursor_provider import CursorRuntime, build_providers
        from .store import Store

        await hass.async_add_executor_job(settings.ensure_dirs)
        store = await hass.async_add_executor_job(Store, settings.data_dir / "ai-workspace.sqlite")
        runtime = CursorRuntime(settings)
        hass.data[DOMAIN].update(
            {
                "store": store,
                "runtime": runtime,
                "providers": build_providers(settings, runtime),
                "locks": {},
            }
        )

        async def _on_stop(_event):
            await runtime.aclose()

        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))

    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), False)]
        )
        hass.data[f"{DOMAIN}_static"] = True

    try:
        frontend.async_remove_panel(hass, PANEL_URL)
    except (KeyError, ValueError, AttributeError):
        pass
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_ELEMENT,
        frontend_url_path=PANEL_URL,
        sidebar_title="AI Workspace" if settings.enable_sidebar else None,
        sidebar_icon="mdi:robot" if settings.enable_sidebar else None,
        module_url=PANEL_JS,
        embed_iframe=False,
        require_admin=True,
    )
    _set_overlay_js(hass, settings.enable_overlay)

    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _set_overlay_js(hass: HomeAssistant, enabled: bool) -> None:
    remove = getattr(frontend, "remove_extra_js_url", None)
    stale = f"{STATIC_URL}/overlay.js"
    if remove:
        for url in (OVERLAY_JS, stale):
            try:
                remove(hass, url)
            except (KeyError, ValueError, AttributeError):
                pass
    if enabled:
        frontend.add_extra_js_url(hass, OVERLAY_JS)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.pop(DOMAIN, None)
    _set_overlay_js(hass, False)
    try:
        frontend.async_remove_panel(hass, PANEL_URL)
    except (KeyError, ValueError, AttributeError):
        pass
    if data and data.get("runtime"):
        await data["runtime"].aclose()
    if data and data.get("store"):
        data["store"].close()
    return True
