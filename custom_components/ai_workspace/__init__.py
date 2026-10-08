from __future__ import annotations

import logging
from pathlib import Path
from types import MappingProxyType

import voluptuous as vol
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
import asyncio

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    SOURCE_SYSTEM,
    ConfigEntry,
    ConfigEntryState,
    ConfigSubentry,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .agents import (
    CursorAgent,
    agent_from_entry,
    agents_entry,
    entry_agents,
    hub_entry,
    is_agents,
    is_provider,
    legacy_agent_data,
    legacy_title,
    provider_entries,
)
from .const import (
    AGENTS_TITLE,
    CONF_AGENT_ID,
    CONF_HUB_ID,
    CONF_ROLE,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_CURSOR_API_KEY,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ALLOW_USERS,
    CONF_ENABLE_DICTATE,
    CONF_HOUSE_MAP,
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
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_HA_MCP,
    MODE_API,
    MODE_CURSOR,
    ROLE_AGENTS,
    SUBENTRY_AGENT,
    SUBENTRY_MCP,
    OVERLAY_JS,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_URL,
    STATIC_URL,
)
from .discovery import async_resolve_runtime_url
from .http import register_views
from .mcp_config import clean_mcp_extra, mcp_servers_from_saved, server_slug
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
                vol.Optional(CONF_HOUSE_MAP, default=False): cv.boolean,
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


_PRIMARY_TITLES = {
    MCP_HA: "Home Assistant",
    MCP_HA_MCP: "HA-MCP",
    MCP_COOLVER: "Coolver",
    MCP_CUSTOM: "Custom",
}


def _mcp_rows(entry: ConfigEntry) -> list[dict]:
    found: list[dict] = []
    for sub in getattr(entry, "subentries", {}).values():
        if getattr(sub, "subentry_type", "") != SUBENTRY_MCP:
            continue
        raw = dict(getattr(sub, "data", {}) or {})
        name = str(raw.get("name") or getattr(sub, "title", "") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not name or not url:
            continue
        found.append(
            {
                "name": name,
                "url": url,
                "token": str(raw.get("token") or "").strip(),
                "primary": bool(raw.get("primary")),
            }
        )
    return found


def _primary_and_extras(entry: ConfigEntry) -> tuple[dict | None, list[dict[str, str]]]:
    rows = _mcp_rows(entry)
    primary = next((row for row in rows if row.get("primary")), None)
    extras = [
        {"name": row["name"], "url": row["url"], "token": row["token"]}
        for row in rows
        if row is not primary
    ]
    if primary is None and not rows:
        return None, clean_mcp_extra(_merged(entry).get(CONF_MCP_EXTRA))
    return primary, extras


def _migrate_mcp_connections(hass: HomeAssistant, hub: ConfigEntry) -> None:
    """Move connections that used to live on the form onto the service."""
    if hub.data.get("mcp_connections_migrated"):
        return
    extras = clean_mcp_extra(_merged(hub).get(CONF_MCP_EXTRA))
    existing = {
        str(sub.unique_id or "")
        for sub in hub.subentries.values()
        if getattr(sub, "subentry_type", "") == SUBENTRY_MCP
    }
    for item in extras:
        if item["name"] in existing:
            continue
        hass.config_entries.async_add_subentry(
            hub,
            ConfigSubentry(
                data=MappingProxyType(
                    {"name": item["name"], "url": item["url"], "token": item["token"]}
                ),
                subentry_type=SUBENTRY_MCP,
                title=item["name"],
                unique_id=item["name"],
            ),
        )
    data = dict(hub.data)
    data.pop(CONF_MCP_EXTRA, None)
    data["mcp_connections_migrated"] = True
    options = dict(hub.options)
    changed_options = CONF_MCP_EXTRA in options
    options.pop(CONF_MCP_EXTRA, None)
    hass.config_entries.async_update_entry(
        hub,
        data=data,
        options=options if changed_options else hub.options,
    )


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
    primary, extras = _primary_and_extras(entry)
    if primary:
        token = primary["token"]
        configured = primary["url"]
    else:
        token = str(data.get(CONF_MCP_TOKEN) or "").strip()
        configured = str(data.get(CONF_MCP_URL) or "").strip()
    servers = mcp_servers_from_saved(
        mcp_url if mcp_url is not None else configured,
        token,
        extras,
    )
    house_map = bool(data.get(CONF_HOUSE_MAP, False))
    if house_map:
        from .house_map import mcp_server_config

        servers = {**servers, "house-map": mcp_server_config(hass, token)}
    return Settings(
        data_dir=root,
        workspace_dir=root / "workspace",
        state_dir=root / "cursor-state",
        cursor_api_key=str(data.get(CONF_CURSOR_API_KEY) or "").strip(),
        model=_model_for_mode(data),
        mcp_kind=mcp_kind_of(data),
        mcp_token=token,
        mcp_servers=servers,
        enable_overlay=bool(data.get(CONF_ENABLE_OVERLAY, True)),
        enable_sidebar=bool(data.get(CONF_ENABLE_SIDEBAR, True)),
        enable_dictate=bool(data.get(CONF_ENABLE_DICTATE, True)),
        allow_users=bool(data.get(CONF_ALLOW_USERS, False)),
        house_map=house_map,
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

    async def _remove_integration(_call) -> None:
        hub = hub_entry(hass)
        if hub is None:
            return
        await hass.config_entries.async_remove(hub.entry_id)

    hass.services.async_register(DOMAIN, "remove", _remove_integration)
    return True


def _as_system(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Hide Delete and Disable on the integration page (Home Assistant system source)."""
    data = dict(entry.data)
    if entry.source == SOURCE_SYSTEM and data.get("system_entry"):
        return
    if entry.source != SOURCE_SYSTEM:
        entry.source = SOURCE_SYSTEM
    if not data.get("system_entry"):
        data["system_entry"] = True
    hass.config_entries.async_update_entry(entry, data=data)


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
    migrating = bool((hass.data.get(DOMAIN) or {}).get("migrating"))
    hass.data[DOMAIN] = {
        "entry": hub,
        "settings": settings,
        "mode": "agents",
        "runtime_url": runtime_url,
        "runtime": None,
        "store": store,
        "providers": {},
        "locks": {},
        "migrating": migrating,
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
    from .house_map import async_setup_house_map

    await async_setup_house_map(hass, store, bool(settings.house_map))
    return hass.data[DOMAIN]


async def _build_settings(hass: HomeAssistant, hub: ConfigEntry) -> Settings:
    primary, _extras = _primary_and_extras(hub)
    if primary:
        return _settings(hass, hub, primary["url"])
    data = _merged(hub)
    mcp_url = await async_resolve_mcp_url(
        hass,
        mcp_kind_of(data),
        str(data.get(CONF_MCP_URL) or "").strip(),
        str(data.get(CONF_MCP_TOKEN) or "").strip(),
    )
    return _settings(hass, hub, mcp_url)


def _drop_loose_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop devices that are not one of the connection or agent rows.

    Home Assistant files those under "Devices that don't belong to a sub-entry".
    """
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if device.config_subentry_id:
            continue
        registry.async_remove_device(device.id)


def _migrate_primary_mcp(hass: HomeAssistant, hub: ConfigEntry) -> None:
    """The first Home Assistant connection becomes a row, same as the others."""
    if hub.data.get("primary_mcp_migrated"):
        return
    data = _merged(hub)
    url = str(data.get(CONF_MCP_URL) or "").strip()
    token = str(data.get(CONF_MCP_TOKEN) or "").strip()
    kind = str(data.get(CONF_MCP_KIND) or "")
    existing = {
        str(dict(getattr(sub, "data", {}) or {}).get("url") or "").rstrip("/")
        for sub in hub.subentries.values()
        if getattr(sub, "subentry_type", "") == SUBENTRY_MCP
    }
    has_primary = any(
        bool(dict(getattr(sub, "data", {}) or {}).get("primary"))
        for sub in hub.subentries.values()
        if getattr(sub, "subentry_type", "") == SUBENTRY_MCP
    )
    if url and url.rstrip("/") not in existing and not has_primary:
        title = _PRIMARY_TITLES.get(kind, "Home Assistant")
        hass.config_entries.async_add_subentry(
            hub,
            ConfigSubentry(
                data=MappingProxyType(
                    {
                        "name": server_slug(title, url) or "home-assistant",
                        "url": url,
                        "token": token,
                        "primary": True,
                    }
                ),
                subentry_type=SUBENTRY_MCP,
                title=title,
                unique_id="primary",
            ),
        )
    hass.config_entries.async_update_entry(hub, data={**dict(hub.data), "primary_mcp_migrated": True})


def _add_agent_subentry(hass: HomeAssistant, agents: ConfigEntry, agent_id: str, title: str, raw: dict):
    for sub in agents.subentries.values():
        if getattr(sub, "subentry_type", "") == SUBENTRY_AGENT and str(sub.unique_id or "") == agent_id:
            return sub
    payload = {key: value for key, value in raw.items() if key not in {"enabled", "role", "hub_id"}}
    payload[CONF_AGENT_ID] = agent_id
    hass.config_entries.async_add_subentry(
        agents,
        ConfigSubentry(
            data=MappingProxyType(payload),
            subentry_type=SUBENTRY_AGENT,
            title=title or "Agent",
            unique_id=agent_id,
        ),
    )
    for sub in agents.subentries.values():
        if str(sub.unique_id or "") == agent_id:
            return sub
    return None


def _move_conversation_entity(hass: HomeAssistant, agent_id: str, agents_id: str, subentry_id: str) -> None:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("conversation", DOMAIN, agent_id)
    if not entity_id:
        return
    try:
        registry.async_update_entity(
            entity_id,
            config_entry_id=agents_id,
            config_subentry_id=subentry_id,
        )
    except TypeError:
        registry.async_update_entity(entity_id, config_subentry_id=subentry_id)


async def _ensure_agents_entry(hass: HomeAssistant, hub: ConfigEntry) -> ConfigEntry | None:
    """Create AI Workspace agents without a second trip through Add integration."""
    found = agents_entry(hass, hub.entry_id)
    if found is not None:
        _as_system(hass, found)
        if found.title != AGENTS_TITLE:
            hass.config_entries.async_update_entry(found, title=AGENTS_TITLE)
        return found
    created = ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title=AGENTS_TITLE,
        data={CONF_ROLE: ROLE_AGENTS, CONF_HUB_ID: hub.entry_id, "system_entry": True},
        options={},
        source=SOURCE_SYSTEM,
        unique_id=f"{hub.entry_id}-agents",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    await hass.config_entries.async_add(created)
    return created


async def _fold_devices(hass: HomeAssistant, hub: ConfigEntry) -> None:
    """AI Workspace for connections, AI Workspace agents for providers."""
    agents = await _ensure_agents_entry(hass, hub)
    if agents is None:
        return
    bucket = hass.data[DOMAIN]
    bucket["migrating"] = True
    try:
        moved: list[tuple[str, object]] = []
        # Undo 1.0.14 one-block layout: agent rows belong on the agents entry.
        for sub in list(getattr(hub, "subentries", {}).values()):
            if getattr(sub, "subentry_type", "") != SUBENTRY_AGENT:
                continue
            raw = dict(sub.data)
            agent_id = str(raw.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)
            created = _add_agent_subentry(hass, agents, agent_id, sub.title, raw)
            if created is not None:
                moved.append((agent_id, created))
            hass.config_entries.async_remove_subentry(hub, sub.subentry_id)

        if not hub.data.get("devices_migrated"):
            for child in list(provider_entries(hass, hub.entry_id)):
                raw = {**child.data, **child.options}
                agent_id = str(raw.get(CONF_AGENT_ID) or child.unique_id or child.entry_id)
                sub = _add_agent_subentry(hass, agents, agent_id, child.title, raw)
                if sub is not None:
                    moved.append((agent_id, sub))
            if not moved and not hub.data.get("agents_migrated") and not entry_agents(agents):
                payload = legacy_agent_data(_merged(hub))
                worth = bool(
                    payload
                    and (
                        str(payload.get(CONF_CURSOR_API_KEY) or "").strip()
                        or str(payload.get(CONF_API_KEY) or "").strip()
                        or str(payload.get(CONF_API_PROVIDER) or "") == "ollama"
                    )
                )
                if worth and payload:
                    created = _add_agent_subentry(hass, agents, "legacy", legacy_title(payload), payload)
                    if created is not None:
                        moved.append(("legacy", created))
            for child in list(provider_entries(hass, hub.entry_id)):
                await hass.config_entries.async_remove(child.entry_id)

        for agent_id, sub in moved:
            _move_conversation_entity(hass, agent_id, agents.entry_id, sub.subentry_id)

        data = {
            **dict(hub.data),
            "providers_migrated": True,
            "agents_migrated": True,
            "devices_migrated": True,
        }
        data.pop("agents_on_hub", None)
        if moved or hub.data.get("agents_on_hub") or not hub.data.get("devices_migrated"):
            hass.config_entries.async_update_entry(hub, data=data)
    finally:
        bucket["migrating"] = False


async def _open_agents(hass: HomeAssistant, entry_id: str) -> None:
    agents = hass.config_entries.async_get_entry(entry_id)
    if agents is None or agents.disabled_by:
        return
    if agents.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_reload(entry_id)
    elif agents.state is ConfigEntryState.NOT_LOADED:
        await hass.config_entries.async_setup(entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if is_provider(entry):
        return await _setup_provider(hass, entry)
    if is_agents(entry):
        return await _setup_agents(hass, entry)
    _as_system(hass, entry)
    hass.data.setdefault(DOMAIN, {})["migrating"] = True
    _migrate_mcp_connections(hass, entry)
    _migrate_primary_mcp(hass, entry)
    await _ensure_shared(hass, entry)
    _drop_loose_devices(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_reload))
    hass.data[DOMAIN]["migrating"] = True
    hass.data[DOMAIN]["defer_platforms"] = True
    try:
        await _fold_devices(hass, entry)
    finally:
        hass.data[DOMAIN]["defer_platforms"] = False
    agents = agents_entry(hass, entry.entry_id)
    if agents and not agents.disabled_by:
        if hass.is_running:
            hass.async_create_task(_open_agents(hass, agents.entry_id))
        else:
            agent_id = agents.entry_id

            async def _schedule(_event) -> None:
                await _open_agents(hass, agent_id)

            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule)
    names = ", ".join(hass.data.get(DOMAIN, {}).get("providers", {})) or "none yet"
    _LOGGER.info("AI Workspace providers: %s", names)
    return True


async def _setup_provider(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub_id = str(entry.data.get("hub_id") or "")
    hub = hass.config_entries.async_get_entry(hub_id) if hub_id else None
    if hub is None or hub.disabled_by or hub.data.get("devices_migrated"):
        return False
    bucket = await _ensure_shared(hass, hub)
    if hub.data.get("devices_migrated"):
        return False
    agent = agent_from_entry(entry)
    if agent.mode == MODE_CURSOR and not bucket.get("runtime_url"):
        configured = str(_merged(hub).get(CONF_RUNTIME_URL) or "").strip().rstrip("/")
        bucket["runtime_url"] = await async_resolve_runtime_url(hass, configured)
    if hub.data.get("devices_migrated"):
        return False
    bucket["providers"][agent.id] = _one_provider(hass, bucket["settings"], agent, bucket.get("runtime_url") or "")
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def _setup_agents(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub_id = str(entry.data.get(CONF_HUB_ID) or "")
    hub = hass.config_entries.async_get_entry(hub_id) if hub_id else hub_entry(hass)
    if hub is None or hub.disabled_by:
        return False
    bucket = await _ensure_shared(hass, hub)
    _drop_loose_devices(hass, entry)
    if not bucket.get("runtime_url"):
        configured = str(_merged(hub).get(CONF_RUNTIME_URL) or "").strip().rstrip("/")
        bucket["runtime_url"] = await async_resolve_runtime_url(hass, configured) if configured else ""
    runtime = bucket.get("runtime_url") or ""
    providers = {}
    for agent in entry_agents(entry):
        providers[agent.id] = _one_provider(hass, bucket["settings"], agent, runtime)
    bucket["providers"] = providers
    entry.async_on_unload(entry.add_update_listener(_reload))
    if not hass.is_running or (hass.data.get(DOMAIN) or {}).get("defer_platforms"):
        return True
    hass.data[DOMAIN].setdefault("agents_platforms", set()).add(entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if (hass.data.get(DOMAIN) or {}).get("migrating"):
        return
    await hass.config_entries.async_reload(entry.entry_id)
    if is_provider(entry) or is_agents(entry):
        return
    agents = agents_entry(hass, entry.entry_id)
    if agents and agents.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_reload(agents.entry_id)


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
        hub_id = str(entry.data.get("hub_id") or "")
        hub = hass.config_entries.async_get_entry(hub_id) if hub_id else None
        bucket = hass.data.get(DOMAIN)
        if bucket is not None and not (hub and hub.data.get("devices_migrated")):
            bucket.get("providers", {}).pop(agent_from_entry(entry).id, None)
        return unloaded
    if is_agents(entry):
        ready = (hass.data.get(DOMAIN) or {}).get("agents_platforms") or set()
        if entry.entry_id not in ready:
            return True
        ready.discard(entry.entry_id)
        return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    agents = agents_entry(hass, entry.entry_id)
    if agents and agents.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(agents.entry_id)
    for child in list(provider_entries(hass, entry.entry_id)):
        if child.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(child.entry_id)
    data = hass.data.pop(DOMAIN, None)
    if data and callable(data.get("house_map_unsub")):
        data["house_map_unsub"]()
    _set_overlay_js(hass, False)
    _remove_panel(hass)
    if data and data.get("runtime"):
        await data["runtime"].aclose()
    if data and data.get("store"):
        data["store"].close()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    bucket = hass.data.setdefault(DOMAIN, {})
    if is_provider(entry):
        return
    if is_agents(entry):
        if bucket.get("removing_hub"):
            return
        hub_id = str(entry.data.get(CONF_HUB_ID) or "")
        hub = hass.config_entries.async_get_entry(hub_id) if hub_id else hub_entry(hass)
        if hub is not None and not hub.disabled_by:
            hass.async_create_task(_ensure_agents_entry(hass, hub))
        return
    bucket["removing_hub"] = True
    try:
        agents = agents_entry(hass, entry.entry_id)
        if agents is not None:
            await hass.config_entries.async_remove(agents.entry_id)
        for child in list(provider_entries(hass, entry.entry_id)):
            await hass.config_entries.async_remove(child.entry_id)
    finally:
        bucket.pop("removing_hub", None)
