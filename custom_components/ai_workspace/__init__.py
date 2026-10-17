from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .agents import CursorAgent, entry_agents
from .assist_pipelines import async_remove_assist_pipeline
from .const import (
    CONF_CROSS_CHAT,
    CONF_ENABLE_DICTATE,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ALLOW_USERS,
    CONF_HOUSE_MAP,
    CONF_SHORTEN_MCP_RESULTS,
    CONF_CHANGE_HISTORY,
    CONF_KEEP_CHATS,
    CONF_MCP_KIND,
    CONF_SPEAK_REPLIES,
    CONF_TTS_NATURAL,
    CONF_STT_ENGINE,
    CONF_SYSTEM_PROMPT,
    CONF_TTS_ENGINE,
    DEFAULT_KEEP_CHATS,
    DOMAIN,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_HA_MCP,
    MODE_API,
    MODE_CURSOR,
    OVERLAY_JS,
    PANEL_ELEMENT,
    PANEL_JS,
    PANEL_URL,
    STATIC_URL,
    STT_BROWSER,
    SUBENTRY_AGENT,
    SUBENTRY_MCP,
    TTS_OFF,
)
from .discovery import async_bind_runtime
from .http import register_views
from .mcp_config import mcp_servers_from_saved
from .mcp_resolve import async_resolve_mcp_url, infer_mcp_kind
from .models import Settings

_LOGGER = logging.getLogger(__name__)
_PLATFORMS = [Platform.CONVERSATION, Platform.STT, Platform.TTS]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _merged(entry: ConfigEntry) -> dict:
    return {**entry.data, **entry.options}


def _disabled_subentries(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    """Rows whose service device the user disabled.

    Reloads from `_listen_device_disable` when `disabled_by` changes, then
    `mcp_rows()` drops those subentries so their tools never reach the model.
    Unloading Home Assistant's MCP Server integration is a different path:
    the subentry stays, and the API provider skips local `/api/mcp` until
    `mcp_server` is loaded again.
    """
    registry = dr.async_get(hass)
    return {
        device.config_subentry_id
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if device.config_subentry_id and device.disabled_by is not None
    }


def mcp_rows(hass: HomeAssistant, entry: ConfigEntry) -> list[dict]:
    disabled = _disabled_subentries(hass, entry)
    found: list[dict] = []
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_MCP or sub.subentry_id in disabled:
            continue
        raw = dict(sub.data)
        name = str(raw.get("name") or sub.title or "").strip()
        url = str(raw.get("url") or "").strip()
        kind = str(raw.get(CONF_MCP_KIND) or "").strip() or infer_mcp_kind(url)
        if not name or (not url and kind == MCP_CUSTOM):
            continue
        found.append(
            {
                "name": name,
                "url": url,
                "token": str(raw.get("token") or "").strip(),
                "kind": kind,
                "primary": bool(raw.get("primary")),
            }
        )
    if found and not any(row["primary"] for row in found):
        found[0]["primary"] = True
    return found


def _keep_chats(data: dict) -> int:
    try:
        keep = int(data.get(CONF_KEEP_CHATS, DEFAULT_KEEP_CHATS) or DEFAULT_KEEP_CHATS)
    except (TypeError, ValueError):
        keep = DEFAULT_KEEP_CHATS
    return max(1, min(keep, 500))


async def _build_settings(hass: HomeAssistant, entry: ConfigEntry) -> Settings:
    data = _merged(entry)
    rows = mcp_rows(hass, entry)
    for row in rows:
        if not row["url"]:
            row["url"] = await async_resolve_mcp_url(hass, row["kind"], "", row["token"])
    primary = next((row for row in rows if row["primary"]), None)
    extras = [row for row in rows if row is not primary]
    servers = mcp_servers_from_saved(
        primary["url"] if primary else "",
        primary["token"] if primary else "",
        extras,
    )
    house_map = bool(data.get(CONF_HOUSE_MAP, False))
    token = primary["token"] if primary else ""
    if house_map:
        from .house_map import mcp_server_config

        servers = {**servers, "catalog": mcp_server_config(hass)}
    kind = primary["kind"] if primary else MCP_CUSTOM
    if kind not in {MCP_HA, MCP_HA_MCP, MCP_COOLVER}:
        kind = MCP_CUSTOM
    from .voice import resolved_overlay_tts

    tts = resolved_overlay_tts(hass, str(data.get(CONF_TTS_ENGINE) or TTS_OFF).strip() or TTS_OFF)
    root = Path(hass.config.path(DOMAIN))
    return Settings(
        data_dir=root,
        workspace_dir=root / "workspace",
        state_dir=root / "cursor-state",
        cursor_api_key="",
        model="",
        mcp_kind=kind,
        mcp_token=token,
        mcp_servers=servers,
        mcp_rows=[{key: row[key] for key in ("name", "url", "kind", "primary")} for row in rows],
        enable_overlay=bool(data.get(CONF_ENABLE_OVERLAY, True)),
        enable_sidebar=bool(data.get(CONF_ENABLE_SIDEBAR, True)),
        enable_dictate=bool(data.get(CONF_ENABLE_DICTATE, True)),
        allow_users=bool(data.get(CONF_ALLOW_USERS, False)),
        house_map=house_map,
        shorten_mcp_results=bool(data.get(CONF_SHORTEN_MCP_RESULTS, True)),
        change_history=bool(data.get(CONF_CHANGE_HISTORY, True)),
        cross_chat=bool(data.get(CONF_CROSS_CHAT, False)),
        keep_chats=_keep_chats(data),
        mode=MODE_API,
        system_prompt=str(data.get(CONF_SYSTEM_PROMPT) or "").strip(),
        stt_engine=str(data.get(CONF_STT_ENGINE) or STT_BROWSER).strip() or STT_BROWSER,
        tts_engine=tts,
        speak_replies=bool(data.get(CONF_SPEAK_REPLIES, False)) and tts != TTS_OFF,
        tts_natural=bool(data.get(CONF_TTS_NATURAL, True)),
    )


def _one_provider(hass: HomeAssistant, settings: Settings, agent, store):
    from .api_provider import ApiProvider

    if agent.mode == MODE_CURSOR:
        return CursorAgent(agent, False, None)
    agent_settings = replace(
        settings,
        mode=MODE_API,
        api_provider=agent.provider,
        api_key=agent.api_key,
        api_base=agent.api_base,
        model=agent.model,
        effort=agent.effort,
        low_token=agent.low_token,
        check_house=agent.check_house,
        azure_api_version=agent.azure_api_version,
        agent_id=agent.id,
        agent_title=agent.title,
    )
    return ApiProvider(hass, agent_settings, store)


def _sync_subentry_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """One service device per connection and agent row, so each row can be disabled on its own."""
    registry = dr.async_get(hass)
    wanted: set[str] = set()
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_MCP:
            ident, model = f"mcp:{sub.subentry_id}", "Connection"
        elif sub.subentry_type == SUBENTRY_AGENT:
            ident, model = f"agent:{agent_device_key(sub)}", "Agent"
        else:
            continue
        wanted.add(sub.subentry_id)
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=sub.subentry_id,
            identifiers={(DOMAIN, ident)},
            name=str(sub.title or model),
            manufacturer="AI Workspace",
            model=model,
            entry_type=dr.DeviceEntryType.SERVICE,
        )
    for device in list(dr.async_entries_for_config_entry(registry, entry.entry_id)):
        if not device.config_subentry_id or device.config_subentry_id not in wanted:
            for entity_id in _conversation_entities(hass, device_id=device.id):
                hass.async_create_task(async_remove_assist_pipeline(hass, entity_id))
            registry.async_remove_device(device.id)


def _conversation_entities(hass: HomeAssistant, *, device_id: str | None = None, entry_id: str | None = None) -> list[str]:
    entities = er.async_get(hass)
    if device_id:
        rows = er.async_entries_for_device(entities, device_id, include_disabled_entities=True)
    else:
        rows = er.async_entries_for_config_entry(entities, entry_id or "")
    return [row.entity_id for row in rows if row.domain == "conversation" and row.platform == DOMAIN]


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Deleting AI Workspace also deletes the Assist pipelines it created."""
    for entity_id in _conversation_entities(hass, entry_id=entry.entry_id):
        await async_remove_assist_pipeline(hass, entity_id)


def agent_device_key(sub) -> str:
    from .const import CONF_AGENT_ID

    return str(sub.data.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)


def _listen_device_disable(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Disabling a row's device takes that connection or agent out of the chat."""
    entry_id = entry.entry_id

    async def _updated(event) -> None:
        if event.data.get("action") != "update" or "disabled_by" not in (event.data.get("changes") or {}):
            return
        device = dr.async_get(hass).async_get(event.data.get("device_id"))
        if device is None or entry_id not in device.config_entries:
            return
        hass.config_entries.async_schedule_reload(entry_id)

    entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _updated))


async def _register_frontend(hass: HomeAssistant, settings: Settings) -> None:
    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), False)]
        )
        hass.data[f"{DOMAIN}_static"] = True
    if not hass.data.get(f"{DOMAIN}_http"):
        register_views(hass)
        hass.data[f"{DOMAIN}_http"] = True
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .house_map import async_setup_house_map
    from .http import _prune_all_chats
    from .store import Store

    settings = await _build_settings(hass, entry)
    await hass.async_add_executor_job(settings.ensure_dirs)
    store = await hass.async_add_executor_job(Store, settings.data_dir / "ai-workspace.sqlite")
    bucket: dict = {
        "entry": entry,
        "settings": settings,
        "store": store,
        "providers": {},
        "locks": {},
        "chat_jobs": set(),
        "runtime_url": "",
        "runtime_token": "",
    }
    hass.data[DOMAIN] = bucket
    _sync_subentry_devices(hass, entry)
    _listen_device_disable(hass, entry)
    disabled = _disabled_subentries(hass, entry)
    bucket["providers"] = {
        agent.id: _one_provider(hass, settings, agent, store)
        for agent in entry_agents(entry)
        if agent.subentry_id not in disabled
    }
    await async_bind_runtime(hass, bucket, force=True)
    await _register_frontend(hass, settings)
    await async_setup_house_map(hass, store, settings.house_map)
    await _prune_all_chats(hass, store, settings.keep_chats)
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    from .voice import resolved_overlay_tts

    settings.tts_engine = resolved_overlay_tts(hass, settings.tts_engine)
    if settings.tts_engine == TTS_OFF:
        settings.speak_replies = False
    _LOGGER.info("AI Workspace agents: %s", ", ".join(bucket["providers"]) or "none yet")
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
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
    try:
        frontend.remove_extra_js_url(hass, OVERLAY_JS)
    except (KeyError, ValueError):
        pass
    if enabled:
        frontend.add_extra_js_url(hass, OVERLAY_JS)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
    if not unloaded:
        return False
    data = hass.data.pop(DOMAIN, None) or {}
    jobs = list(data.get("chat_jobs") or ())
    for job in jobs:
        job.cancel()
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)
    unsub = data.get("house_map_unsub")
    if callable(unsub):
        unsub()
    _set_overlay_js(hass, False)
    _remove_panel(hass)
    store = data.get("store")
    if store is not None:
        await hass.async_add_executor_job(store.close)
    return True
