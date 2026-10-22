"""Optional configuration.yaml import for AI Workspace."""

from __future__ import annotations

import logging
import re
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    API_AZURE,
    API_PROVIDERS,
    API_SHORT_LABELS,
    CONF_AGENT_ID,
    CONF_ALLOW_USERS,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_ASSIST,
    CONF_ASSIST_STT,
    CONF_ASSIST_TTS,
    CONF_AZURE_API_VERSION,
    CONF_CHANGE_HISTORY,
    CONF_CHANGE_HISTORY_TTL_DAYS,
    CONF_CHECK_HOUSE,
    CONF_CROSS_CHAT,
    CONF_CURSOR_API_KEY,
    CONF_EFFORT,
    CONF_ENABLE_DICTATE,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_HA_USAGE_SENSORS,
    CONF_HOUSE_MAP,
    CONF_KEEP_CHATS,
    CONF_LOW_TOKEN,
    CONF_MCP_KIND,
    CONF_MODE,
    CONF_MODEL,
    CONF_PROMPT_CACHE,
    CONF_RUNTIME_TOKEN,
    CONF_RUNTIME_URL,
    CONF_SHORTEN_MCP_RESULTS,
    CONF_SHOW_CHAT_USAGE,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_STT_MODEL,
    CONF_SYSTEM_PROMPT,
    CONF_TRACK_USAGE,
    CONF_TTS_ENGINE,
    CONF_TTS_MODEL,
    CONF_TTS_NATURAL,
    CONF_TTS_SPEED,
    CONF_TTS_VOICE,
    CONF_UI_THEME,
    CHANGE_HISTORY_TTL_MAX_DAYS,
    CHANGE_HISTORY_TTL_MIN_DAYS,
    DEFAULT_AZURE_API_VERSION,
    DEFAULT_CHANGE_HISTORY_TTL_DAYS,
    DEFAULT_KEEP_CHATS,
    change_history_ttl_days,
    DOMAIN,
    EFFORT_DEFAULT,
    EFFORTS,
    MCP_CONNECTION_TITLES,
    MCP_CUSTOM,
    MCP_HA,
    MCP_KINDS,
    MODE_API,
    MODE_CURSOR,
    STT_BROWSER,
    SUBENTRY_AGENT,
    SUBENTRY_MCP,
    SUBENTRY_USAGE,
    TOKEN_MODE_OFF,
    TOKEN_MODES,
    TTS_OFF,
    assist_enabled,
    assist_stt_enabled,
    assist_tts_enabled,
    provider_supports_stt,
    provider_supports_tts,
    provider_supports_tts_speed,
    resolved_tts_speed,
    token_mode_of,
    tts_speed_choice,
    ui_theme_of,
)
from .mcp_config import server_slug

_LOGGER = logging.getLogger(__name__)
YAML_STORAGE = f"{DOMAIN}_yaml"
_SLUG = re.compile(r"[^a-z0-9]+")
YAML_CONNECTIONS = "connections"
YAML_AGENTS = "agents"
_PROVIDERS = (MODE_CURSOR, *API_PROVIDERS)
YAML_SHARED_KEYS = (
    CONF_SYSTEM_PROMPT,
    CONF_RUNTIME_URL,
    CONF_RUNTIME_TOKEN,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ENABLE_DICTATE,
    CONF_ALLOW_USERS,
    CONF_HOUSE_MAP,
    CONF_SHORTEN_MCP_RESULTS,
    CONF_CHANGE_HISTORY,
    CONF_CHANGE_HISTORY_TTL_DAYS,
    CONF_CHECK_HOUSE,
    CONF_TRACK_USAGE,
    CONF_SHOW_CHAT_USAGE,
    CONF_HA_USAGE_SENSORS,
    CONF_LOW_TOKEN,
    CONF_PROMPT_CACHE,
    CONF_UI_THEME,
    CONF_CROSS_CHAT,
    CONF_KEEP_CHATS,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_TTS_ENGINE,
    CONF_TTS_NATURAL,
)
YAML_OPTION_DEFAULTS = {
    CONF_SYSTEM_PROMPT: "",
    CONF_RUNTIME_URL: "",
    CONF_RUNTIME_TOKEN: "",
    CONF_ENABLE_OVERLAY: True,
    CONF_ENABLE_SIDEBAR: True,
    CONF_ENABLE_DICTATE: True,
    CONF_ALLOW_USERS: False,
    CONF_HOUSE_MAP: False,
    CONF_SHORTEN_MCP_RESULTS: True,
    CONF_CHANGE_HISTORY: True,
    CONF_CHANGE_HISTORY_TTL_DAYS: DEFAULT_CHANGE_HISTORY_TTL_DAYS,
    CONF_CHECK_HOUSE: True,
    CONF_TRACK_USAGE: True,
    CONF_SHOW_CHAT_USAGE: True,
    CONF_HA_USAGE_SENSORS: False,
    CONF_LOW_TOKEN: TOKEN_MODE_OFF,
    CONF_PROMPT_CACHE: True,
    CONF_UI_THEME: "standard",
    CONF_CROSS_CHAT: False,
    CONF_KEEP_CHATS: DEFAULT_KEEP_CHATS,
    CONF_SPEAK_REPLIES: False,
    CONF_STT_ENGINE: STT_BROWSER,
    CONF_TTS_ENGINE: TTS_OFF,
    CONF_TTS_NATURAL: True,
}


def _keep_chats(value: Any) -> int:
    try:
        keep = int(value or DEFAULT_KEEP_CHATS)
    except (TypeError, ValueError):
        keep = DEFAULT_KEEP_CHATS
    return max(1, min(keep, 500))


def _normalize_option(key: str, value: Any) -> Any:
    if key == CONF_LOW_TOKEN:
        return token_mode_of(value)
    if key == CONF_UI_THEME:
        return ui_theme_of(value)
    if key == CONF_KEEP_CHATS:
        return _keep_chats(value)
    if key == CONF_CHANGE_HISTORY_TTL_DAYS:
        return change_history_ttl_days(value)
    if key in {
        CONF_ENABLE_OVERLAY,
        CONF_ENABLE_SIDEBAR,
        CONF_ENABLE_DICTATE,
        CONF_ALLOW_USERS,
        CONF_HOUSE_MAP,
        CONF_SHORTEN_MCP_RESULTS,
        CONF_CHANGE_HISTORY,
        CONF_CHECK_HOUSE,
        CONF_TRACK_USAGE,
        CONF_SHOW_CHAT_USAGE,
        CONF_HA_USAGE_SENSORS,
        CONF_PROMPT_CACHE,
        CONF_CROSS_CHAT,
        CONF_SPEAK_REPLIES,
        CONF_TTS_NATURAL,
    }:
        return bool(value)
    return str(value or "").strip()


def options_from_yaml(conf: dict[str, Any], *, fill_defaults: bool = False) -> dict[str, Any]:
    """Map YAML keys onto config-entry options. Omitted keys stay unset unless filling defaults."""
    out: dict[str, Any] = dict(YAML_OPTION_DEFAULTS) if fill_defaults else {}
    for key in YAML_SHARED_KEYS:
        if key in conf:
            out[key] = _normalize_option(key, conf[key])
    return out


def _slug(value: str, fallback: str) -> str:
    slug = _SLUG.sub("-", str(value or "").strip().lower()).strip("-")[:40]
    return slug or fallback


CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Optional("kind", default=MCP_CUSTOM): vol.In(list(MCP_KINDS)),
        vol.Optional("name", default=""): cv.string,
        vol.Optional("url", default=""): cv.string,
        vol.Optional("token", default=""): cv.string,
        vol.Optional("primary", default=False): cv.boolean,
    }
)

AGENT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Required("provider"): vol.In(list(_PROVIDERS)),
        vol.Optional("api_key", default=""): cv.string,
        vol.Optional("api_base", default=""): cv.string,
        vol.Optional("model", default=""): cv.string,
        vol.Optional("effort", default=EFFORT_DEFAULT): vol.In(list(EFFORTS)),
        vol.Optional("cursor_api_key", default=""): cv.string,
        vol.Optional("azure_api_version", default=DEFAULT_AZURE_API_VERSION): cv.string,
        vol.Optional("check_house", default=True): cv.boolean,
        vol.Optional("assist"): cv.boolean,
        vol.Optional("assist_stt"): cv.boolean,
        vol.Optional("stt_model", default=""): cv.string,
        vol.Optional("assist_tts"): cv.boolean,
        vol.Optional("tts_model", default=""): cv.string,
        vol.Optional("tts_voice", default=""): cv.string,
        vol.Optional("tts_speed"): vol.Any(cv.string, vol.Coerce(float)),
    }
)

YAML_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SYSTEM_PROMPT): cv.string,
        vol.Optional(CONF_RUNTIME_URL): cv.string,
        vol.Optional(CONF_RUNTIME_TOKEN): cv.string,
        vol.Optional(CONF_ENABLE_OVERLAY): cv.boolean,
        vol.Optional(CONF_ENABLE_SIDEBAR): cv.boolean,
        vol.Optional(CONF_ENABLE_DICTATE): cv.boolean,
        vol.Optional(CONF_ALLOW_USERS): cv.boolean,
        vol.Optional(CONF_HOUSE_MAP): cv.boolean,
        vol.Optional(CONF_SHORTEN_MCP_RESULTS): cv.boolean,
        vol.Optional(CONF_CHANGE_HISTORY): cv.boolean,
        vol.Optional(CONF_CHANGE_HISTORY_TTL_DAYS): vol.All(
            vol.Coerce(int),
            vol.Range(min=CHANGE_HISTORY_TTL_MIN_DAYS, max=CHANGE_HISTORY_TTL_MAX_DAYS),
        ),
        vol.Optional(CONF_CHECK_HOUSE): cv.boolean,
        vol.Optional(CONF_TRACK_USAGE): cv.boolean,
        vol.Optional(CONF_SHOW_CHAT_USAGE): cv.boolean,
        vol.Optional(CONF_HA_USAGE_SENSORS): cv.boolean,
        vol.Optional(CONF_LOW_TOKEN): vol.All(token_mode_of, vol.In(list(TOKEN_MODES))),
        vol.Optional(CONF_PROMPT_CACHE): cv.boolean,
        vol.Optional(CONF_UI_THEME): vol.Any(cv.boolean, vol.In(("standard", "ha_components"))),
        vol.Optional(CONF_CROSS_CHAT): cv.boolean,
        vol.Optional(CONF_KEEP_CHATS): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
        vol.Optional(CONF_SPEAK_REPLIES): cv.boolean,
        vol.Optional(CONF_STT_ENGINE): cv.string,
        vol.Optional(CONF_TTS_ENGINE): cv.string,
        vol.Optional(CONF_TTS_NATURAL): cv.boolean,
        vol.Optional(YAML_CONNECTIONS): [CONNECTION_SCHEMA],
        vol.Optional(YAML_AGENTS): [AGENT_SCHEMA],
    }
)

CONFIG_SCHEMA = vol.Schema({DOMAIN: YAML_SCHEMA}, extra=vol.ALLOW_EXTRA)


def connection_unique_id(row: dict[str, Any]) -> str:
    kind = str(row.get("kind") or MCP_CUSTOM)
    name = str(row.get("name") or "").strip() or MCP_CONNECTION_TITLES.get(kind, "")
    url = str(row.get("url") or "").strip()
    return server_slug(name, url) or kind


def connection_payload(row: dict[str, Any], *, primary: bool) -> dict[str, Any]:
    kind = str(row.get("kind") or MCP_CUSTOM)
    if kind not in MCP_KINDS:
        kind = MCP_CUSTOM
    name = str(row.get("name") or "").strip() or MCP_CONNECTION_TITLES.get(kind) or "MCP"
    url = str(row.get("url") or "").strip()
    unique = connection_unique_id({**row, "kind": kind, "name": name, "url": url})
    return {
        "subentry_type": SUBENTRY_MCP,
        "title": MCP_CONNECTION_TITLES.get(kind) or name,
        "unique_id": unique,
        "data": {
            "name": unique,
            "url": url,
            "token": str(row.get("token") or "").strip(),
            CONF_MCP_KIND: kind,
            "primary": primary,
        },
    }


def default_connection() -> dict[str, Any]:
    return connection_payload({"kind": MCP_HA, "name": "", "url": "", "token": ""}, primary=True)


def connections_from_yaml(conf: dict[str, Any], *, fill_default: bool = False) -> list[dict[str, Any]]:
    rows = list(conf.get(YAML_CONNECTIONS) or [])
    if not rows:
        return [default_connection()] if fill_default else []
    found: list[dict[str, Any]] = []
    used: set[str] = set()
    primary_set = False
    for row in rows:
        item = connection_payload(row, primary=bool(row.get("primary")))
        unique = item["unique_id"]
        if unique in used:
            unique = f"{unique}-{len(used) + 1}"
            item["unique_id"] = unique
            item["data"]["name"] = unique
        used.add(unique)
        if item["data"]["primary"]:
            if primary_set:
                item["data"]["primary"] = False
            else:
                primary_set = True
        found.append(item)
    if found and not primary_set:
        found[0]["data"]["primary"] = True
    return found


def agent_unique_id(row: dict[str, Any], used: set[str]) -> str:
    provider = str(row.get("provider") or MODE_CURSOR)
    wanted = _slug(str(row.get("id") or row.get("title") or provider), provider)
    unique = wanted
    number = 2
    while unique in used:
        unique = f"{wanted}-{number}"
        number += 1
    used.add(unique)
    return unique


def agent_payload(row: dict[str, Any], unique: str) -> dict[str, Any]:
    provider = str(row.get("provider") or MODE_CURSOR)
    if provider not in _PROVIDERS:
        provider = MODE_CURSOR
    cursor = provider == MODE_CURSOR
    effort = str(row.get("effort") or "")
    if effort not in EFFORTS or effort == EFFORT_DEFAULT:
        effort = ""
    title = str(row.get("title") or "").strip() or ("Cursor" if cursor else API_SHORT_LABELS.get(provider, "Agent"))
    raw = {**row, CONF_API_PROVIDER: provider}
    data = {
        CONF_AGENT_ID: unique,
        CONF_MODE: MODE_CURSOR if cursor else MODE_API,
        CONF_API_PROVIDER: provider,
        CONF_CURSOR_API_KEY: str(row.get("cursor_api_key") or "").strip() if cursor else "",
        CONF_API_KEY: "" if cursor else str(row.get("api_key") or "").strip(),
        CONF_API_BASE: "" if cursor else str(row.get("api_base") or "").strip(),
        CONF_MODEL: str(row.get("model") or "").strip(),
        CONF_EFFORT: effort,
        CONF_ASSIST: assist_enabled(raw, new=True) if "assist" in row else assist_enabled({}, new=True),
        CONF_ASSIST_STT: assist_stt_enabled(raw, provider) if provider_supports_stt(provider) else False,
        CONF_STT_MODEL: str(row.get("stt_model") or "").strip() if provider_supports_stt(provider) else "",
        CONF_ASSIST_TTS: assist_tts_enabled(raw, provider) if provider_supports_tts(provider) else False,
        CONF_TTS_MODEL: str(row.get("tts_model") or "").strip() if provider_supports_tts(provider) else "",
        CONF_TTS_VOICE: str(row.get("tts_voice") or "").strip() if provider_supports_tts(provider) else "",
        CONF_TTS_SPEED: tts_speed_choice(resolved_tts_speed(raw)) if provider_supports_tts_speed(provider) else "",
        CONF_AZURE_API_VERSION: str(row.get("azure_api_version") or DEFAULT_AZURE_API_VERSION)
        if provider == API_AZURE
        else "",
    }
    return {"subentry_type": SUBENTRY_AGENT, "title": title, "unique_id": unique, "data": data}


def agents_from_yaml(conf: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in conf.get(YAML_AGENTS) or []:
        unique = agent_unique_id(row, used)
        found.append(agent_payload(row, unique))
    return found


def usage_subentry_dict() -> dict[str, Any]:
    return {"subentry_type": SUBENTRY_USAGE, "title": "Usage", "unique_id": "usage", "data": {}}


def entry_from_yaml(conf: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    options = options_from_yaml(conf, fill_defaults=True)
    if CONF_CHECK_HOUSE not in conf:
        agents = [row for row in (conf.get(YAML_AGENTS) or []) if str(row.get("provider") or "") != MODE_CURSOR]
        if agents and all(not bool(row.get("check_house", True)) for row in agents):
            options[CONF_CHECK_HOUSE] = False
    subentries = connections_from_yaml(conf, fill_default=True) + agents_from_yaml(conf)
    if options.get(CONF_HA_USAGE_SENSORS):
        subentries.append(usage_subentry_dict())
    return options, subentries


def _same_data(left: Any, right: dict[str, Any]) -> bool:
    return dict(left or {}) == right


def _sync_typed_subentries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    subentry_type: str,
    wanted: list[dict[str, Any]],
) -> bool:
    existing = {sub.unique_id or sub.subentry_id: sub for sub in entry.subentries.values() if sub.subentry_type == subentry_type}
    changed = False
    keep: set[str] = set()
    for item in wanted:
        unique = str(item["unique_id"])
        keep.add(unique)
        current = existing.get(unique)
        if current is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(item["data"]),
                    subentry_type=subentry_type,
                    title=item["title"],
                    unique_id=unique,
                ),
            )
            changed = True
            continue
        if current.title != item["title"] or not _same_data(current.data, item["data"]):
            hass.config_entries.async_update_subentry(
                entry,
                current,
                title=item["title"],
                data=item["data"],
            )
            changed = True
    for unique, current in existing.items():
        if unique in keep:
            continue
        hass.config_entries.async_remove_subentry(entry, current.subentry_id)
        changed = True
    return changed


async def async_apply_yaml(hass: HomeAssistant, entry: ConfigEntry, conf: dict[str, Any]) -> bool:
    """Apply YAML onto an existing entry. Only listed keys/lists are written."""
    changed = False
    patch = options_from_yaml(conf, fill_defaults=False)
    if patch:
        options = {**entry.options, **patch}
        if dict(entry.options) != options:
            hass.config_entries.async_update_entry(entry, options=options)
            changed = True
    if YAML_CONNECTIONS in conf:
        if _sync_typed_subentries(hass, entry, subentry_type=SUBENTRY_MCP, wanted=connections_from_yaml(conf)):
            changed = True
    if YAML_AGENTS in conf:
        if _sync_typed_subentries(hass, entry, subentry_type=SUBENTRY_AGENT, wanted=agents_from_yaml(conf)):
            changed = True
    if changed:
        _LOGGER.info("Applied AI Workspace YAML configuration")
    return changed
