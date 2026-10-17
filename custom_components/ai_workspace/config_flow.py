from __future__ import annotations

import logging
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    Selector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .agent_flow import AgentSubentryFlow
from .const import (
    CONF_ALLOW_USERS,
    CONF_CROSS_CHAT,
    CONF_ENABLE_DICTATE,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_HOUSE_MAP,
    CONF_SHORTEN_MCP_RESULTS,
    CONF_CHANGE_HISTORY,
    CONF_KEEP_CHATS,
    CONF_MCP_KIND,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_RUNTIME_TOKEN,
    CONF_RUNTIME_URL,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_SYSTEM_PROMPT,
    CONF_TTS_ENGINE,
    CONF_TTS_NATURAL,
    DEFAULT_KEEP_CHATS,
    DEFAULT_SYSTEM_PROMPT,
    DOMAIN,
    MCP_CONNECTION_TITLES,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_KINDS,
    STT_BROWSER,
    SUBENTRY_AGENT,
    SUBENTRY_MCP,
    TTS_OFF,
    mcp_kind_options,
)
from .mcp_config import server_slug
from .mcp_flow import McpConnectionFlow
from .mcp_resolve import async_detect_mcp_kinds, async_resolve_mcp_url, default_mcp_url, mcp_kind_of
from .voice import async_speech_engines

_LOGGER = logging.getLogger(__name__)

SECTION_MCP = "mcp"
SECTION_PROMPT = "prompt"
SECTION_VOICE = "voice"
_SHARED_KEYS = (
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
    CONF_CROSS_CHAT,
    CONF_KEEP_CHATS,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_TTS_ENGINE,
    CONF_TTS_NATURAL,
)
_URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PROMPT_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
_MCP_URL_NOTE = (
    "Leave empty to auto-detect. HA-MCP is often a webhook under /api/webhook/… on this "
    "Home Assistant (port 8123), or http://127.0.0.1:8086/mcp. Built-in MCP is /api/mcp."
)


def _same_url(left: str, right: str) -> bool:
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


def _looks_detected_mcp(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    path = (parsed.path or "").lower()
    host = (parsed.hostname or "").lower()
    if "webhook" in path or "/api/mcp" in path:
        return True
    return parsed.port in {8086, 9583, 9584} or host in {"ha-mcp"}


def _mcp_url_note(url: str, auto: bool) -> str:
    if not auto:
        return _MCP_URL_NOTE
    path = (urlparse(url).path or "").lower()
    if "webhook" in path:
        return "Auto-detected HA-MCP webhook. Keep this unless you use a different MCP."
    if "/api/mcp" in path:
        return "Auto-detected built-in Home Assistant MCP. Keep this unless you use a different MCP."
    return "Auto-detected MCP URL. Keep this unless you use a different MCP."


def _form_placeholders(*, mcp_url: str = "", mcp_auto: bool = False) -> dict[str, str]:
    return {
        "mcp_url_mark": " · auto-detected" if mcp_auto else "",
        "mcp_url_note": _mcp_url_note(mcp_url, mcp_auto),
    }


def _ui_schema(defaults: dict | None = None) -> dict:
    current = defaults or {}
    return {
        vol.Optional(CONF_ENABLE_SIDEBAR, default=current.get(CONF_ENABLE_SIDEBAR, True)): cv.boolean,
        vol.Optional(CONF_ENABLE_OVERLAY, default=current.get(CONF_ENABLE_OVERLAY, True)): cv.boolean,
        vol.Optional(CONF_ENABLE_DICTATE, default=current.get(CONF_ENABLE_DICTATE, True)): cv.boolean,
        vol.Optional(CONF_ALLOW_USERS, default=current.get(CONF_ALLOW_USERS, False)): cv.boolean,
        vol.Optional(CONF_HOUSE_MAP, default=current.get(CONF_HOUSE_MAP, False)): cv.boolean,
        vol.Optional(CONF_SHORTEN_MCP_RESULTS, default=current.get(CONF_SHORTEN_MCP_RESULTS, True)): cv.boolean,
        vol.Optional(CONF_CHANGE_HISTORY, default=current.get(CONF_CHANGE_HISTORY, True)): cv.boolean,
        vol.Optional(CONF_CROSS_CHAT, default=current.get(CONF_CROSS_CHAT, False)): cv.boolean,
        vol.Optional(
            CONF_KEEP_CHATS,
            default=int(current.get(CONF_KEEP_CHATS, DEFAULT_KEEP_CHATS) or DEFAULT_KEEP_CHATS),
        ): NumberSelector(NumberSelectorConfig(min=1, max=500, mode="box", step=1)),
    }


def _mcp_url_for_form(current: dict, hass: HomeAssistant | None = None) -> str:
    value = str(current.get(CONF_MCP_URL) or "").strip()
    return value or default_mcp_url(hass, mcp_kind_of(current))


def _normalize(user_input: dict, hass: HomeAssistant | None = None) -> dict:
    out = dict(user_input)
    kind = str(out.get(CONF_MCP_KIND) or "").strip()
    if kind not in MCP_KINDS:
        kind = mcp_kind_of(out)
    out[CONF_MCP_KIND] = kind
    out[CONF_MCP_TOKEN] = str(out.get(CONF_MCP_TOKEN) or "").strip()
    url = str(out.get(CONF_MCP_URL) or "").strip()
    parsed = urlparse(url)
    if kind == MCP_HA and "/api/mcp" not in (parsed.path or ""):
        url = default_mcp_url(hass, kind)
    elif kind == MCP_COOLVER and parsed.port != 8099:
        url = default_mcp_url(hass, kind)
    out[CONF_MCP_URL] = url
    if CONF_KEEP_CHATS in out:
        try:
            keep = int(out[CONF_KEEP_CHATS])
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP_CHATS
        out[CONF_KEEP_CHATS] = max(1, min(keep, 500))
    return out


async def _restore_auto_mcp(hass: HomeAssistant, out: dict) -> dict:
    """Store an empty MCP URL when the submitted one is still the auto-detected one."""
    kind = str(out.get(CONF_MCP_KIND) or "").strip()
    submitted = str(out.get(CONF_MCP_URL) or "").strip()
    if kind and kind != MCP_CUSTOM:
        detected = await async_resolve_mcp_url(hass, kind, "", str(out.get(CONF_MCP_TOKEN) or ""))
        if not submitted or _same_url(submitted, detected):
            out[CONF_MCP_URL] = ""
    return out


def _explicit_mcp_kind(current: dict) -> str:
    kind = str(current.get(CONF_MCP_KIND) or "").strip()
    if kind in MCP_KINDS:
        return kind
    url = str(current.get(CONF_MCP_URL) or "").strip()
    return mcp_kind_of({CONF_MCP_URL: url}) if url else ""


def _default_mcp_kind(current: dict, kinds: list[str]) -> str:
    explicit = _explicit_mcp_kind(current)
    if explicit in kinds:
        return explicit
    return next((kind for kind in kinds if kind != MCP_CUSTOM), MCP_CUSTOM)


def _mcp_schema(current: dict, hass: HomeAssistant | None, kinds: list[str]) -> vol.Schema:
    kind = _default_mcp_kind(current, kinds)
    fields: dict = {
        vol.Required(CONF_MCP_KIND, default=kind): SelectSelector(
            SelectSelectorConfig(options=kinds, mode="dropdown", translation_key="mcp_kind")
        ),
        vol.Optional(CONF_MCP_URL, default=_mcp_url_for_form(current, hass)): _URL_SELECTOR,
    }
    if kind in {MCP_CUSTOM, MCP_COOLVER} or str(current.get(CONF_MCP_TOKEN) or "").strip():
        fields[vol.Optional(CONF_MCP_TOKEN, default="")] = _TOKEN_SELECTOR
    return vol.Schema(fields)


async def _prepare_mcp_form(hass: HomeAssistant, current: dict) -> tuple[dict, bool, list[str]]:
    detected = await async_detect_mcp_kinds(hass)
    kinds = mcp_kind_options(detected, _explicit_mcp_kind(current))
    data = dict(current)
    if not _explicit_mcp_kind(data):
        data[CONF_MCP_KIND] = _default_mcp_kind(data, kinds)
    kind = mcp_kind_of(data)
    saved = str(data.get(CONF_MCP_URL) or "").strip()
    found = await async_resolve_mcp_url(hass, kind, "", str(data.get(CONF_MCP_TOKEN) or ""))
    auto = kind != MCP_CUSTOM and (not saved or _same_url(saved, found))
    if auto and found:
        data[CONF_MCP_URL] = found
    mcp_auto = auto and bool(data.get(CONF_MCP_URL)) and _looks_detected_mcp(str(data.get(CONF_MCP_URL) or ""))
    return data, mcp_auto, kinds


def _prompt_schema(current: dict) -> vol.Schema:
    value = str(current.get(CONF_SYSTEM_PROMPT) or "").strip() or DEFAULT_SYSTEM_PROMPT
    return vol.Schema({vol.Optional(CONF_SYSTEM_PROMPT, default=value): _PROMPT_SELECTOR})


def _flatten(user_input: dict) -> dict:
    out = dict(user_input)
    for key in (SECTION_MCP, SECTION_PROMPT, SECTION_VOICE):
        nested = out.pop(key, None)
        if isinstance(nested, dict):
            out.update(nested)
    if str(out.get(CONF_SYSTEM_PROMPT) or "").strip() == DEFAULT_SYSTEM_PROMPT.strip():
        out[CONF_SYSTEM_PROMPT] = ""
    return out


class _SideBySide(Selector):
    """Two fields on one row. The form stores them under the field name."""

    selector_type = "grid"
    CONFIG_SCHEMA = vol.Schema({})

    def __init__(self, nested: vol.Schema, column_min_width: str = "240px") -> None:
        super().__init__({})
        self._nested = nested
        self._width = column_min_width

    def __call__(self, value):
        if not isinstance(value, dict):
            value = {}
        return self._nested(value)

    def serialize(self) -> dict:
        from probatio import to_field_list

        return {
            "type": "grid",
            "column_min_width": self._width,
            "schema": to_field_list(self._nested, custom_serializer=cv.custom_serializer),
        }


def _voice_schema(defaults: dict, stt: list, tts: list) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_STT_ENGINE, default=str(defaults.get(CONF_STT_ENGINE) or STT_BROWSER)): SelectSelector(
                SelectSelectorConfig(options=stt, mode="dropdown")
            ),
            vol.Optional(CONF_TTS_ENGINE, default=str(defaults.get(CONF_TTS_ENGINE) or TTS_OFF)): SelectSelector(
                SelectSelectorConfig(options=tts, mode="dropdown")
            ),
            vol.Optional(CONF_SPEAK_REPLIES, default=bool(defaults.get(CONF_SPEAK_REPLIES, False))): cv.boolean,
            vol.Optional(CONF_TTS_NATURAL, default=bool(defaults.get(CONF_TTS_NATURAL, True))): cv.boolean,
        }
    )


async def _shared_form(
    hass: HomeAssistant,
    defaults: dict,
    kinds: list[str] | None,
    *,
    include_mcp: bool,
) -> vol.Schema:
    stt = await async_speech_engines(hass, "stt")
    tts = await async_speech_engines(hass, "tts")
    saved_tts = str(defaults.get(CONF_TTS_ENGINE) or TTS_OFF)
    tts_ids = {item.get("value") for item in tts}
    if saved_tts not in tts_ids:
        saved_tts = TTS_OFF
    voice = {
        CONF_STT_ENGINE: str(defaults.get(CONF_STT_ENGINE) or STT_BROWSER),
        CONF_TTS_ENGINE: saved_tts,
        CONF_SPEAK_REPLIES: bool(defaults.get(CONF_SPEAK_REPLIES, False)),
        CONF_TTS_NATURAL: bool(defaults.get(CONF_TTS_NATURAL, True)),
    }
    fields: dict = {}
    if include_mcp:
        fields[vol.Required(SECTION_MCP)] = section(_mcp_schema(defaults, hass, kinds or []), {"collapsed": False})
    fields[vol.Required(SECTION_PROMPT)] = section(_prompt_schema(defaults), {"collapsed": True})
    fields[vol.Optional(SECTION_VOICE, default=voice)] = _SideBySide(_voice_schema(voice, stt, tts))
    fields.update(_ui_schema(defaults))
    return vol.Schema(fields, extra=vol.ALLOW_EXTRA)


def _mcp_errors(flat: dict) -> dict:
    errors = {}
    kind = str(flat.get(CONF_MCP_KIND) or "")
    if kind == MCP_CUSTOM and not str(flat.get(CONF_MCP_URL) or "").strip():
        errors[CONF_MCP_URL] = "required"
    if kind == MCP_COOLVER and not str(flat.get(CONF_MCP_TOKEN) or "").strip():
        errors[CONF_MCP_TOKEN] = "required"
    return errors


def _primary_connection(flat: dict) -> dict:
    kind = str(flat.get(CONF_MCP_KIND) or MCP_CUSTOM)
    url = str(flat.get(CONF_MCP_URL) or "")
    title = MCP_CONNECTION_TITLES.get(kind) or (urlparse(url).hostname or "MCP")
    return {
        "subentry_type": SUBENTRY_MCP,
        "title": title,
        "unique_id": server_slug(title, url) or "home-assistant",
        "data": {
            "name": server_slug(title, url) or "home-assistant",
            "url": url,
            "token": str(flat.get(CONF_MCP_TOKEN) or ""),
            CONF_MCP_KIND: kind,
            "primary": True,
        },
    }


class AiWorkspaceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_on_create_entry(self, result):
        """Ask for the first agent right after the integration is added."""
        from homeassistant.config_entries import SOURCE_USER, FlowType

        created = result.get("result")
        flow_type = getattr(FlowType, "CONFIG_SUBENTRIES_FLOW", None)
        if created is None or flow_type is None:
            return result
        try:
            started = await self.hass.config_entries.subentries.async_init(
                (created.entry_id, SUBENTRY_AGENT),
                context={"source": SOURCE_USER},
            )
        except Exception:
            _LOGGER.debug("First agent form skipped", exc_info=True)
            return result
        result["next_flow"] = (flow_type, started["flow_id"])
        return result

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        saved: dict = {}
        if user_input is not None:
            flat = _normalize(_flatten(user_input), self.hass)
            errors = _mcp_errors(flat)
            if not errors:
                flat = await _restore_auto_mcp(self.hass, flat)
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(
                    title="AI Workspace",
                    data={},
                    options={key: flat.get(key) for key in _SHARED_KEYS},
                    subentries=[_primary_connection(flat)],
                )
            saved = flat
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, saved)
        placeholders = _form_placeholders(
            mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
            mcp_auto=mcp_auto,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=await _shared_form(self.hass, defaults, kinds, include_mcp=True),
            errors=errors,
            description_placeholders=placeholders,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {
            SUBENTRY_MCP: McpConnectionFlow,
            SUBENTRY_AGENT: AgentSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AiWorkspaceOptionsFlow()


class AiWorkspaceOptionsFlow(config_entries.OptionsFlow):
    def _current(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input=None):
        current = self._current()
        if user_input is not None:
            flat = _flatten(user_input)
            if CONF_KEEP_CHATS in flat:
                flat = _normalize(flat, self.hass)
            merged = {**current, **flat}
            return self.async_create_entry(title="", data={key: merged.get(key) for key in _SHARED_KEYS})
        return self.async_show_form(
            step_id="init",
            data_schema=await _shared_form(self.hass, current, None, include_mcp=False),
        )
