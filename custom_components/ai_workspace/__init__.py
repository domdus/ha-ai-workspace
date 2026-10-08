from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
import asyncio

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .agents import (
    CursorAgent,
    agent_from_entry,
    is_provider,
    legacy_agent_data,
    provider_entries,
)
from .const import (
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_CURSOR_API_KEY,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ALLOW_USERS,
    CONF_ENABLE_DICTATE,
    CONF_MCP_EXTRA,
    CONF_MCP_KIND,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_URL,
    CONF_AZURE_API_VERSION,
    CONF_EFFORT,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_SYSTEM_PROMPT,
    CONF_TTS_ENGINE,
    DEFAULT_AZURE_API_VERSION,
    STT_BROWSER,
    TTS_OFF,
    CLOUD_ONLY_MODELS,
    DEFAULT_MODEL,
    DOMAIN,
    MODE_API,
    MODE_CURSOR,
    ROLE_PROVIDER,
    SUBENTRY_AGENT,
    OVERLAY_JS,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_URL,
    STATIC_URL,
)
from .discovery import async_resolve_runtime_url
from .http import register_views
from .mcp_config import mcp_servers_from_saved
from .mcp_resolve import async_resolve_mcp_url, mcp_kind_of
from .models import Settings

_LOGGER = logging.getLogger(__name__)
_PLATFORMS = ["conversation"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_MCP_URL, default=""): cv.string,
                vol.Optional(CONF_MCP_KIND, default=""): cv.string,
                vol.Optional(CONF_MCP_TOKEN, default=""): cv.string,
                vol.Optional(CONF_CURSOR_API_KEY, default=""): cv.string,
                vol.Optional(CONF_MODEL, default=""): cv.string,
                vol.Optional(CONF_RUNTIME_URL, default=""): cv.string,
                vol.Optional(CONF_MODE, default=""): cv.string,
                vol.Optional(CONF_API_PROVIDER, default="openai"): cv.string,
                vol.Optional(CONF_API_KEY, default=""): cv.string,
                vol.Optional(CONF_API_BASE, default=""): cv.string,
                vol.Optional(CONF_SYSTEM_PROMPT, default=""): cv.string,
                vol.Optional(CONF_ENABLE_SIDEBAR, default=True): cv.boolean,
                vol.Optional(CONF_ENABLE_OVERLAY, default=True): cv.boolean,
                vol.Optional(CONF_ENABLE_DICTATE, default=True): cv.boolean,
                vol.Optional(CONF_ALLOW_USERS, default=False): cv.boolean,
                vol.Optional(CONF_STT_ENGINE, default=STT_BROWSER): cv.string,
                vol.Optional(CONF_TTS_ENGINE, default=TTS_OFF): cv.string,
                vol.Optional(CONF_SPEAK_REPLIES, default=False): cv.boolean,
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
        if model in CLOUD_ONLY_MODELS:
            return ""
        return model
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
        mcp_servers=mcp_servers_from_saved(
            mcp_url if mcp_url is not None else configured,
            token,
            data.get(CONF_MCP_EXTRA),
        ),
        enable_overlay=bool(data.get(CONF_ENABLE_OVERLAY, True)),
        enable_sidebar=bool(data.get(CONF_ENABLE_SIDEBAR, True)),
        enable_dictate=bool(data.get(CONF_ENABLE_DICTATE, True)),
        allow_users=bool(data.get(CONF_ALLOW_USERS, False)),
        mode=_mode(data),
        api_provider=str(data.get(CONF_API_PROVIDER) or "openai").strip() or "openai",
        api_key=str(data.get(CONF_API_KEY) or "").strip(),
        api_base=str(data.get(CONF_API_BASE) or "").strip(),
        system_prompt=str(data.get(CONF_SYSTEM_PROMPT) or "").strip(),
        effort=str(data.get(CONF_EFFORT) or "").strip(),
        azure_api_version=str(data.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION).strip(),
        stt_engine=str(data.get(CONF_STT_ENGINE) or STT_BROWSER).strip() or STT_BROWSER,
        tts_engine=str(data.get(CONF_TTS_ENGINE) or TTS_OFF).strip() or TTS_OFF,
        speak_replies=bool(data.get(CONF_SPEAK_REPLIES, False)),
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


def _one_provider(hass: HomeAssistant, settings: Settings, agent, runtime_url: str):
    from dataclasses import replace

    from .api_provider import ApiProvider

    if agent.mode == MODE_CURSOR:
        reason = None if runtime_url else "Start the Cursor SDK Runtime and set its URL on AI Workspace."
        return CursorAgent(agent, bool(runtime_url), reason)
    store = hass.data[DOMAIN].get("store")
    agent_settings = replace(
        settings,
        mode=MODE_API,
        api_provider=agent.provider,
        api_key=agent.api_key,
        api_base=agent.api_base,
        model=agent.model,
        effort=agent.effort,
        azure_api_version=agent.azure_api_version,
        agent_id=agent.id,
        agent_title=agent.title,
    )
    return ApiProvider(hass, agent_settings, store)


async def _ensure_shared(hass: HomeAssistant, hub: ConfigEntry) -> dict:
    existing = hass.data.get(DOMAIN)
    if existing and getattr(existing.get("entry"), "entry_id", None) == hub.entry_id and existing.get("store"):
        existing["settings"] = await _build_settings(hass, hub)
        return existing
    data = _merged(hub)
    settings = await _build_settings(hass, hub)
    configured = str(data.get(CONF_RUNTIME_URL) or "").strip().rstrip("/")
    runtime_url = await async_resolve_runtime_url(hass, configured) if configured else ""
    from .store import Store

    await hass.async_add_executor_job(settings.ensure_dirs)
    store = await hass.async_add_executor_job(Store, settings.data_dir / "ai-workspace.sqlite")
    hass.data[DOMAIN] = {
        "entry": hub,
        "settings": settings,
        "mode": "agents",
        "runtime_url": runtime_url,
        "runtime": None,
        "store": store,
        "providers": {},
        "locks": {},
        "migrating": False,
    }
    if runtime_url:
        _LOGGER.info("AI Workspace Cursor Runtime at %s", runtime_url)
    if not hass.data.get(f"{DOMAIN}_http"):
        register_views(hass)
        hass.data[f"{DOMAIN}_http"] = True
    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), False)]
        )
        hass.data[f"{DOMAIN}_static"] = True
    _remove_panel(hass)
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
    return hass.data[DOMAIN]


async def _build_settings(hass: HomeAssistant, hub: ConfigEntry) -> Settings:
    data = _merged(hub)
    mcp_url = await async_resolve_mcp_url(
        hass,
        mcp_kind_of(data),
        str(data.get(CONF_MCP_URL) or "").strip(),
        str(data.get(CONF_MCP_TOKEN) or "").strip(),
    )
    return _settings(hass, hub, mcp_url)


async def _migrate_provider_entries(hass: HomeAssistant, hub: ConfigEntry) -> None:
    if hub.data.get("providers_migrated"):
        return
    bucket = hass.data[DOMAIN]
    bucket["migrating"] = True
    try:
        pending: list[tuple[str, str, dict]] = []
        for sub in list(getattr(hub, "subentries", {}).values()):
            if getattr(sub, "subentry_type", "") != SUBENTRY_AGENT:
                continue
            pending.append((sub.subentry_id, sub.title, dict(sub.data)))
        if not pending and not hub.data.get("agents_migrated"):
            payload = legacy_agent_data(_merged(hub))
            if payload:
                pending.append(("legacy", "Agent", payload))
        for subentry_id, title, raw in pending:
            if hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, subentry_id):
                continue
            payload = {key: value for key, value in raw.items() if key != "enabled"}
            payload["role"] = ROLE_PROVIDER
            payload["hub_id"] = hub.entry_id
            payload["agent_id"] = subentry_id
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "migration"},
                data={"title": title, "unique_id": subentry_id, **payload},
            )
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        for child in provider_entries(hass, hub.entry_id):
            for entity in er.async_entries_for_config_entry(registry, child.entry_id):
                if entity.config_subentry_id:
                    registry.async_update_entity(entity.entity_id, config_subentry_id=None)
        for subentry_id, _title, _raw in pending:
            if any(getattr(sub, "subentry_id", None) == subentry_id for sub in getattr(hub, "subentries", {}).values()):
                hass.config_entries.async_remove_subentry(hub, subentry_id)
        await asyncio.sleep(0)
        hass.config_entries.async_update_entry(
            hub,
            data={**dict(hub.data), "providers_migrated": True, "agents_migrated": True},
        )
        await asyncio.sleep(0)
    finally:
        bucket["migrating"] = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if is_provider(entry):
        return await _setup_provider(hass, entry)
    await _ensure_shared(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_reload))
    await _migrate_provider_entries(hass, entry)
    for child in provider_entries(hass, entry.entry_id):
        if child.disabled_by or child.state is not ConfigEntryState.NOT_LOADED:
            continue
        await hass.config_entries.async_setup(child.entry_id)
    names = ", ".join(hass.data.get(DOMAIN, {}).get("providers", {})) or "none yet"
    _LOGGER.info("AI Workspace providers: %s", names)
    return True


async def _setup_provider(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub_id = str(entry.data.get("hub_id") or "")
    hub = hass.config_entries.async_get_entry(hub_id) if hub_id else None
    if hub is None or hub.disabled_by:
        return False
    bucket = await _ensure_shared(hass, hub)
    agent = agent_from_entry(entry)
    if agent.mode == MODE_CURSOR and not bucket.get("runtime_url"):
        configured = str(_merged(hub).get(CONF_RUNTIME_URL) or "").strip().rstrip("/")
        bucket["runtime_url"] = await async_resolve_runtime_url(hass, configured)
    bucket["providers"][agent.id] = _one_provider(hass, bucket["settings"], agent, bucket.get("runtime_url") or "")
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if (hass.data.get(DOMAIN) or {}).get("migrating"):
        return
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_panel(hass: HomeAssistant) -> None:
    panels = hass.data.get("frontend_panels")
    if not isinstance(panels, dict) or PANEL_URL not in panels:
        return
    try:
        frontend.async_remove_panel(hass, PANEL_URL)
    except (KeyError, ValueError, AttributeError):
        pass


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
    if is_provider(entry):
        unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
        bucket = hass.data.get(DOMAIN)
        if bucket is not None:
            bucket.get("providers", {}).pop(agent_from_entry(entry).id, None)
        return unloaded
    for child in list(provider_entries(hass, entry.entry_id)):
        if child.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(child.entry_id)
    data = hass.data.pop(DOMAIN, None)
    _set_overlay_js(hass, False)
    _remove_panel(hass)
    if data and data.get("runtime"):
        await data["runtime"].aclose()
    if data and data.get("store"):
        data["store"].close()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if is_provider(entry):
        return
    for child in list(provider_entries(hass, entry.entry_id)):
        await hass.config_entries.async_remove(child.entry_id)
