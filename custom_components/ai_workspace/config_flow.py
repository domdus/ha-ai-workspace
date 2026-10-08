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

from homeassistant.util.ulid import ulid

from .agent_flow import AgentSubentryFlow, ProviderOptionsFlow, ProviderSteps, _provider_names, _title
from .agents import hub_entry, is_agents, is_provider
from .const import (
    API_COMPATIBLE,
    API_OPENAI,
    API_PROVIDERS,
    CONF_ALLOW_USERS,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ENABLE_DICTATE,
    CONF_HOUSE_MAP,
    CONF_KEEP_CHATS,
    DEFAULT_KEEP_CHATS,
    CONF_MCP_KIND,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_URL,
    CONF_SPEAK_REPLIES,
    CONF_STT_ENGINE,
    CONF_SYSTEM_PROMPT,
    CONF_TTS_ENGINE,
    CLOUD_ONLY_MODELS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    CONF_AGENT_ID,
    CONF_HUB_ID,
    CONF_ROLE,
    DOMAIN,
    HOST_RUNTIME_URL,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_KINDS,
    MODE_API,
    MODE_CURSOR,
    ROLE_HUB,
    ROLE_PROVIDER,
    STT_BROWSER,
    SUBENTRY_AGENT,
    SUBENTRY_MCP,
    TTS_OFF,
    default_api_model,
    mcp_kind_options,
)
from .voice import async_speech_engines
from .discovery import async_probe_runtime, async_resolve_runtime_url, hassio_runtime_url
from .mcp_flow import McpConnectionFlow
from .mcp_resolve import async_detect_mcp_kinds, async_probe_mcp, async_resolve_mcp_url, default_mcp_url, mcp_kind_of

_LOGGER = logging.getLogger(__name__)
_HUB_FLAGS = (
    "providers_migrated",
    "agents_migrated",
    "mcp_connections_migrated",
    "primary_mcp_migrated",
    "devices_migrated",
)

SECTION_PROVIDER = "provider"
SECTION_MCP = "mcp"
SECTION_PROMPT = "prompt"
SECTION_VOICE = "voice"
_PARENT_KEYS = (
    CONF_MCP_KIND,
    CONF_MCP_URL,
    CONF_MCP_TOKEN,
    CONF_SYSTEM_PROMPT,
    CONF_RUNTIME_URL,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_ENABLE_DICTATE,
    CONF_ALLOW_USERS,
    CONF_HOUSE_MAP,
    CONF_KEEP_CHATS,
    CONF_STT_ENGINE,
    CONF_TTS_ENGINE,
    CONF_SPEAK_REPLIES,
)
_MCP_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PROMPT_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))
_PROVIDER_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=list(API_PROVIDERS), mode="dropdown", translation_key="api_provider")
)
_MCP_URL_NOTE = (
    "Leave empty to auto-detect. HA-MCP is often a webhook under /api/webhook/… on this "
    "Home Assistant (port 8123), or http://127.0.0.1:8086/mcp. Built-in MCP is /api/mcp."
)
_RUNTIME_URL_NOTE = (
    "Where this Home Assistant reaches the Cursor SDK container. Leave empty to auto-detect. "
    "Loopback publish: http://127.0.0.1:8090. Same Docker network: http://cursor-sdk:8090."
)


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
        return "Auto-detected HA-MCP webhook from the HA-MCP integration. Keep this unless you use a different MCP."
    if "/api/mcp" in path:
        return "Auto-detected built-in Home Assistant MCP. Keep this unless you use a different MCP."
    return "Auto-detected MCP URL. Keep this unless you use a different MCP."


def _form_placeholders(
    *,
    mcp_url: str = "",
    mcp_auto: bool = False,
    runtime_auto: bool = False,
    runtime_live: bool = False,
) -> dict[str, str]:
    if runtime_live:
        runtime_note = "✅ Runtime found."
    elif runtime_auto:
        runtime_note = "Auto-detected Cursor SDK on this machine."
    else:
        runtime_note = _RUNTIME_URL_NOTE
    return {
        "mcp_url_mark": " (Auto-detected)" if mcp_auto else "",
        "mcp_url_note": _mcp_url_note(mcp_url, mcp_auto),
        "runtime_url_mark": " (Auto-detected)" if runtime_auto else "",
        "runtime_url_note": runtime_note,
    }


def _ui_schema(defaults: dict | None = None):
    current = defaults or {}
    return {
        vol.Optional(
            CONF_ENABLE_SIDEBAR,
            default=current.get(CONF_ENABLE_SIDEBAR, True),
        ): cv.boolean,
        vol.Optional(
            CONF_ENABLE_OVERLAY,
            default=current.get(CONF_ENABLE_OVERLAY, True),
        ): cv.boolean,
        vol.Optional(
            CONF_ENABLE_DICTATE,
            default=current.get(CONF_ENABLE_DICTATE, True),
        ): cv.boolean,
        vol.Optional(
            CONF_ALLOW_USERS,
            default=current.get(CONF_ALLOW_USERS, False),
        ): cv.boolean,
        vol.Optional(
            CONF_HOUSE_MAP,
            default=current.get(CONF_HOUSE_MAP, False),
        ): cv.boolean,
        vol.Optional(
            CONF_KEEP_CHATS,
            default=int(current.get(CONF_KEEP_CHATS, DEFAULT_KEEP_CHATS) or DEFAULT_KEEP_CHATS),
        ): NumberSelector(NumberSelectorConfig(min=1, max=500, mode="box", step=1)),
    }


def _provider_schema(defaults: dict | None = None):
    current = defaults or {}
    kind = current.get(CONF_API_PROVIDER, API_OPENAI)
    model = str(current.get(CONF_MODEL) or "").strip()
    others = {default_api_model(name) for name in API_PROVIDERS if name != kind}
    if not model or model == DEFAULT_MODEL or model in others:
        model = default_api_model(kind)
    providers = dict(API_PROVIDERS)
    return vol.Schema(
        {
            vol.Required(
                CONF_API_PROVIDER,
                default=kind if kind in providers else API_OPENAI,
            ): _PROVIDER_SELECTOR,
            vol.Optional(CONF_API_KEY, default=current.get(CONF_API_KEY, "")): cv.string,
            vol.Optional(CONF_MODEL, default=model): cv.string,
            vol.Optional(CONF_API_BASE, default=current.get(CONF_API_BASE, "")): cv.string,
        }
    )


def _mcp_url_for_form(current: dict, hass: HomeAssistant | None = None) -> str:
    kind = mcp_kind_of(current)
    value = str(current.get(CONF_MCP_URL) or "").strip()
    if not value:
        return default_mcp_url(hass, kind)
    return value


def _normalize(user_input: dict, current: dict | None = None, hass: HomeAssistant | None = None) -> dict:
    out = dict(user_input)
    saved = current or {}
    kind = str(out.get(CONF_MCP_KIND) or saved.get(CONF_MCP_KIND) or "").strip()
    if kind not in MCP_KINDS:
        kind = mcp_kind_of({**saved, **out})
    out[CONF_MCP_KIND] = kind
    token = str(out.get(CONF_MCP_TOKEN) or "").strip()
    if not token:
        token = str(saved.get(CONF_MCP_TOKEN) or "").strip()
    out[CONF_MCP_TOKEN] = token
    url = str(out.get(CONF_MCP_URL) or "").strip()
    path = urlparse(url).path or ""
    port = urlparse(url).port
    if kind == MCP_HA and "/api/mcp" not in path:
        url = default_mcp_url(hass, kind)
    elif kind == MCP_COOLVER and port != 8099:
        url = default_mcp_url(hass, kind)
    out[CONF_MCP_URL] = url
    if CONF_KEEP_CHATS in out or CONF_KEEP_CHATS in saved:
        try:
            keep = int(out.get(CONF_KEEP_CHATS, saved.get(CONF_KEEP_CHATS, DEFAULT_KEEP_CHATS)))
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP_CHATS
        out[CONF_KEEP_CHATS] = max(1, min(keep, 500))
    return out


def _mcp_kind_selector(kinds: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=kinds, mode="dropdown", translation_key="mcp_kind")
    )


def _explicit_mcp_kind(current: dict) -> str:
    kind = str(current.get(CONF_MCP_KIND) or "").strip()
    if kind in MCP_KINDS:
        return kind
    url = str(current.get(CONF_MCP_URL) or "").strip()
    if url:
        return mcp_kind_of({CONF_MCP_URL: url})
    return ""


def _default_mcp_kind(current: dict, kinds: list[str]) -> str:
    explicit = _explicit_mcp_kind(current)
    if explicit in kinds:
        return explicit
    for kind in kinds:
        if kind != MCP_CUSTOM:
            return kind
    return MCP_CUSTOM


async def _form_mcp_kinds(hass: HomeAssistant, current: dict) -> list[str]:
    detected = await async_detect_mcp_kinds(hass)
    return mcp_kind_options(detected, _explicit_mcp_kind(current))


def _mcp_schema(
    defaults: dict | None = None,
    hass: HomeAssistant | None = None,
    kinds: list[str] | None = None,
):
    current = defaults or {}
    options = kinds or mcp_kind_options([], _explicit_mcp_kind(current))
    return vol.Schema(
        {
            vol.Required(CONF_MCP_KIND, default=_default_mcp_kind(current, options)): _mcp_kind_selector(
                options
            ),
            vol.Optional(CONF_MCP_URL, default=_mcp_url_for_form(current, hass)): _MCP_SELECTOR,
            vol.Optional(CONF_MCP_TOKEN, default=""): _TOKEN_SELECTOR,
        }
    )


async def _prepare_mcp_form(hass: HomeAssistant, current: dict) -> tuple[dict, bool, list[str]]:
    kinds = await _form_mcp_kinds(hass, current)
    data = dict(current)
    if not _explicit_mcp_kind(data):
        data[CONF_MCP_KIND] = _default_mcp_kind(data, kinds)
    defaults, mcp_auto = await _defaults_with_mcp(hass, data)
    return defaults, mcp_auto, kinds


async def _defaults_with_mcp(hass: HomeAssistant, current: dict) -> tuple[dict, bool]:
    data = dict(current)
    kind = mcp_kind_of(data)
    token = str(data.get(CONF_MCP_TOKEN) or "").strip()
    found = await async_resolve_mcp_url(
        hass,
        kind,
        str(data.get(CONF_MCP_URL) or "").strip(),
        token,
    )
    live = False
    if found:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        live = await async_probe_mcp(hass, found, headers)
        data[CONF_MCP_URL] = found
    return data, live and _looks_detected_mcp(found)


async def _cursor_placeholders(hass: HomeAssistant, defaults: dict, mcp_auto: bool) -> dict[str, str]:
    discovered = hassio_runtime_url(hass) or ""
    base = str(defaults.get(CONF_RUNTIME_URL) or discovered or HOST_RUNTIME_URL).rstrip("/")
    live = await async_probe_runtime(hass, base)
    return _form_placeholders(
        mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
        mcp_auto=mcp_auto,
        runtime_auto=bool(discovered),
        runtime_live=live,
    )


def _prompt_schema(defaults: dict | None = None):
    current = defaults or {}
    value = str(current.get(CONF_SYSTEM_PROMPT) or "").strip() or DEFAULT_SYSTEM_PROMPT
    return vol.Schema(
        {
            vol.Optional(CONF_SYSTEM_PROMPT, default=value): _PROMPT_SELECTOR,
        }
    )


def _flatten(user_input: dict) -> dict:
    out = dict(user_input)
    for key in (SECTION_PROVIDER, SECTION_MCP, SECTION_PROMPT, SECTION_VOICE):
        nested = out.pop(key, None)
        if isinstance(nested, dict):
            out.update(nested)
    return out


def _api_form(defaults: dict, *, kinds: list[str], hass: HomeAssistant | None = None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(SECTION_PROVIDER): section(
                _provider_schema(defaults), {"collapsed": False}
            ),
            vol.Required(SECTION_MCP): section(_mcp_schema(defaults, hass, kinds), {"collapsed": False}),
            vol.Required(SECTION_PROMPT): section(_prompt_schema(defaults), {"collapsed": False}),
            **_ui_schema(defaults),
        }
    )


def _cursor_model(current: dict) -> str:
    model = str(current.get(CONF_MODEL) or "").strip()
    if not model or model in CLOUD_ONLY_MODELS:
        return ""
    return model


def _cursor_form(
    defaults: dict,
    *,
    kinds: list[str],
    runtime_url: bool = False,
    hass: HomeAssistant | None = None,
) -> vol.Schema:
    schema: dict = {
        vol.Required(SECTION_MCP): section(_mcp_schema(defaults, hass, kinds), {"collapsed": False}),
        vol.Required(SECTION_PROMPT): section(_prompt_schema(defaults), {"collapsed": False}),
        vol.Optional(CONF_MODEL, default=_cursor_model(defaults)): cv.string,
    }
    if runtime_url:
        schema[
            vol.Optional(
                CONF_RUNTIME_URL,
                default=str(defaults.get(CONF_RUNTIME_URL) or HOST_RUNTIME_URL),
            )
        ] = _MCP_SELECTOR
    schema.update(_ui_schema(defaults))
    return vol.Schema(schema)


def _api_errors(user_input: dict) -> dict:
    errors = {}
    if not str(user_input.get(CONF_API_KEY) or "").strip():
        errors[CONF_API_KEY] = "required"
    if user_input.get(CONF_API_PROVIDER) == API_COMPATIBLE and not str(
        user_input.get(CONF_API_BASE) or ""
    ).strip():
        errors[CONF_API_BASE] = "required"
    kind = str(user_input.get(CONF_MCP_KIND) or "")
    if kind == MCP_CUSTOM and not str(user_input.get(CONF_MCP_URL) or "").strip():
        errors[CONF_MCP_URL] = "required"
    if kind == MCP_COOLVER and not str(user_input.get(CONF_MCP_TOKEN) or "").strip():
        errors[CONF_MCP_TOKEN] = "required"
    return errors


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
        }
    )


async def _shared_form(hass, defaults: dict, kinds: list[str], *, include_mcp: bool = True) -> vol.Schema:
    stt = await async_speech_engines(hass, "stt")
    tts = await async_speech_engines(hass, "tts")
    voice = {
        CONF_STT_ENGINE: str(defaults.get(CONF_STT_ENGINE) or STT_BROWSER),
        CONF_TTS_ENGINE: str(defaults.get(CONF_TTS_ENGINE) or TTS_OFF),
    }
    fields: dict = {}
    if include_mcp:
        fields[vol.Required(SECTION_MCP)] = section(_mcp_schema(defaults, hass, kinds), {"collapsed": False})
    fields[vol.Required(SECTION_PROMPT)] = section(_prompt_schema(defaults), {"collapsed": False})
    fields[
        vol.Optional(
            CONF_RUNTIME_URL,
            default=str(defaults.get(CONF_RUNTIME_URL) or ""),
        )
    ] = _MCP_SELECTOR
    fields[vol.Optional(SECTION_VOICE, default=voice)] = _SideBySide(_voice_schema(defaults, stt, tts))
    fields[vol.Optional(CONF_SPEAK_REPLIES, default=bool(defaults.get(CONF_SPEAK_REPLIES, False)))] = cv.boolean
    fields.update(_ui_schema(defaults))
    return vol.Schema(fields, extra=vol.ALLOW_EXTRA)


def _keep_saved_mcp(flat: dict, saved: dict, sent: bool) -> dict:
    if sent:
        return flat
    for key in (CONF_MCP_KIND, CONF_MCP_URL, CONF_MCP_TOKEN):
        flat[key] = saved.get(key, "")
    return flat


def _shared_errors(flat: dict) -> dict:
    errors = {}
    kind = str(flat.get(CONF_MCP_KIND) or "")
    if kind == MCP_CUSTOM and not str(flat.get(CONF_MCP_URL) or "").strip():
        errors[CONF_MCP_URL] = "required"
    if kind == MCP_COOLVER and not str(flat.get(CONF_MCP_TOKEN) or "").strip():
        errors[CONF_MCP_TOKEN] = "required"
    return errors


class AiWorkspaceConfigFlow(ProviderSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._ui: dict = {}

    async def async_on_create_entry(self, result):
        from homeassistant.config_entries import SOURCE_USER, FlowType

        created = result.get("result")
        if created is None or is_provider(created) or is_agents(created):
            return result
        try:
            from . import _ensure_agents_entry

            agents_created = await _ensure_agents_entry(self.hass, created)
            if agents_created is None:
                return result
            started = await self.hass.config_entries.subentries.async_init(
                (agents_created.entry_id, SUBENTRY_AGENT),
                context={"source": SOURCE_USER},
            )
        except Exception:
            _LOGGER.debug("First agent form skipped", exc_info=True)
            return result
        flow_type = getattr(FlowType, "CONFIG_SUBENTRIES_FLOW", None)
        if flow_type is None:
            flow_type = getattr(FlowType, "CONFIG_SUBENTRIES", FlowType.CONFIG_FLOW)
        result["next_flow"] = (flow_type, started["flow_id"])
        return result

    async def _begin_provider(self):
        hub = hub_entry(self.hass)
        self._hub_id = str(self.context.get("hub_id") or (hub.entry_id if hub else ""))
        self._current = {}
        self._provider = MODE_CURSOR
        self._agent_id = ""
        return await self.async_step_provider()

    async def _finish_provider(self, provider: str, data: dict):
        titles, _uniques = _provider_names(self)
        if self.source == "reconfigure":
            entry = self._get_reconfigure_entry()
            titles.discard(entry.title)
            same = str({**entry.data, **entry.options}.get(CONF_API_PROVIDER) or "") == provider
            title = entry.title if same else _title(provider, titles)
            data[CONF_AGENT_ID] = str(data.get(CONF_AGENT_ID) or entry.data.get(CONF_AGENT_ID) or entry.entry_id)
            data[CONF_HUB_ID] = str(data.get(CONF_HUB_ID) or entry.data.get(CONF_HUB_ID) or self._hub_id)
            data[CONF_ROLE] = ROLE_PROVIDER
            return self.async_update_reload_and_abort(entry, title=title, data=data)
        agent_id = ulid()
        data[CONF_AGENT_ID] = agent_id
        data[CONF_HUB_ID] = str(self._hub_id or "")
        data[CONF_ROLE] = ROLE_PROVIDER
        await self.async_set_unique_id(agent_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=_title(provider, titles), data=data)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        if is_provider(entry):
            raw = {**entry.data, **entry.options}
            self._hub_id = str(raw.get(CONF_HUB_ID) or "")
            self._current = raw
            self._provider = str(raw.get(CONF_API_PROVIDER) or MODE_CURSOR)
            self._agent_id = str(raw.get(CONF_AGENT_ID) or entry.entry_id)
            return await self.async_step_provider()
        return await self.async_step_user(user_input)

    async def async_step_migration(self, user_input=None):
        info = dict(user_input or {})
        unique_id = str(info.pop("unique_id", "") or "") or ulid()
        title = str(info.pop("title") or "Agent")
        info.pop("enabled", None)
        info[CONF_ROLE] = ROLE_PROVIDER
        info[CONF_AGENT_ID] = str(info.get(CONF_AGENT_ID) or unique_id)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=info)

    async def async_step_user(self, user_input=None):
        if self.source != "reconfigure" and hub_entry(self.hass) is not None:
            return self.async_abort(reason="already_configured")
        errors = {}
        include_mcp = self.source != "reconfigure"
        saved = self._ui
        if self.source == "reconfigure":
            entry = self._get_reconfigure_entry()
            saved = {**entry.data, **entry.options, **self._ui}
        if user_input is not None:
            sent_mcp = SECTION_MCP in user_input or CONF_MCP_URL in user_input
            flat = _keep_saved_mcp(
                _normalize(_flatten(user_input), saved, self.hass),
                saved,
                sent_mcp or include_mcp,
            )
            errors = _shared_errors(flat) if include_mcp else {}
            if not errors:
                data = {key: flat.get(key) for key in _PARENT_KEYS}
                data[CONF_ROLE] = ROLE_HUB
                if self.source == "reconfigure":
                    entry = self._get_reconfigure_entry()
                    for flag in _HUB_FLAGS:
                        if entry.data.get(flag):
                            data[flag] = True
                    return self.async_update_reload_and_abort(entry, data=data)
                data["mcp_connections_migrated"] = True
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(title="AI Workspace", data=data)
            user_input = {**saved, **flat}
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, user_input or saved)
        return self.async_show_form(
            step_id="user",
            data_schema=await _shared_form(self.hass, defaults, kinds, include_mcp=include_mcp),
            errors=errors,
            description_placeholders=_form_placeholders(
                mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
                mcp_auto=mcp_auto,
            ),
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        # Both entries advertise both types. Home Assistant's header Add buttons
        # list every domain entry and do not filter by type; advertising both
        # avoids "Invalid handler". Flows still save on the correct parent.
        if is_provider(config_entry):
            return {}
        return {
            SUBENTRY_MCP: McpConnectionFlow,
            SUBENTRY_AGENT: AgentSubentryFlow,
        }

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry):
        return not is_agents(config_entry) and not is_provider(config_entry)

    async def async_step_cursor(self, user_input=None):
        errors = {}
        discovered = hassio_runtime_url(self.hass) or ""
        if user_input is not None:
            flat = _normalize(_flatten(user_input), self._ui, self.hass)
            configured = str(flat.get(CONF_RUNTIME_URL) or discovered or "").strip()
            runtime = await async_resolve_runtime_url(self.hass, configured)
            if not runtime:
                errors["base"] = "no_runtime"
            else:
                data = {
                    **self._ui,
                    **flat,
                    CONF_MODE: MODE_CURSOR,
                    CONF_MODEL: _cursor_model({**self._ui, **flat, CONF_MODE: MODE_CURSOR}),
                    CONF_RUNTIME_URL: runtime,
                }
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(title="AI Workspace", data=data)
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, self._ui)
        return self.async_show_form(
            step_id="cursor",
            data_schema=_cursor_form(defaults, kinds=kinds, runtime_url=True, hass=self.hass),
            errors=errors,
            description_placeholders=await _cursor_placeholders(self.hass, defaults, mcp_auto),
        )

    async def async_step_api(self, user_input=None):
        errors = {}
        if user_input is not None:
            flat = _normalize(_flatten(user_input), self._ui, self.hass)
            errors = _api_errors(flat)
            if not errors:
                data = {**self._ui, **flat, CONF_MODE: MODE_API}
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(title="AI Workspace", data=data)
            user_input = {**self._ui, **flat}
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, user_input or self._ui)
        return self.async_show_form(
            step_id="api",
            data_schema=_api_form(defaults, kinds=kinds, hass=self.hass),
            errors=errors,
            description_placeholders=_form_placeholders(
                mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
                mcp_auto=mcp_auto,
            ),
        )

    async def async_step_import(self, user_input):
        await self.async_set_unique_id(DOMAIN)
        data = _normalize({**user_input}, hass=self.hass)
        data.setdefault(CONF_MODE, MODE_CURSOR if data.get(CONF_RUNTIME_URL) else MODE_API)
        self._abort_if_unique_id_configured(updates=data)
        return self.async_create_entry(title="AI Workspace", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        if is_provider(config_entry):
            return ProviderOptionsFlow()
        return AiWorkspaceOptionsFlow()


class AiWorkspaceOptionsFlow(config_entries.OptionsFlow):
    def _current(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options}

    def _save(self, updates: dict):
        current = {**self._current(), **updates}
        return self.async_create_entry(title="", data={key: current.get(key) for key in _PARENT_KEYS})

    async def async_step_init(self, user_input=None):
        current = self._current()
        errors = {}
        if user_input is not None:
            sent_mcp = SECTION_MCP in user_input or CONF_MCP_URL in user_input
            flat = _keep_saved_mcp(_normalize(_flatten(user_input), current, self.hass), current, sent_mcp)
            errors = {}
            if not errors:
                return self._save(flat)
            current = {**current, **flat}
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, current)
        return self.async_show_form(
            step_id="init",
            data_schema=await _shared_form(self.hass, defaults, kinds, include_mcp=False),
            errors=errors,
            description_placeholders=_form_placeholders(
                mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
                mcp_auto=mcp_auto,
            ),
        )

    async def async_step_api(self, user_input=None):
        current = self._current()
        errors = {}
        if user_input is not None:
            flat = _normalize(_flatten(user_input), current, self.hass)
            merged = {**current, **flat}
            errors = _api_errors(merged)
            if not errors:
                return self._save({**flat, CONF_MODE: MODE_API})
            current = merged
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, current)
        return self.async_show_form(
            step_id="api",
            data_schema=_api_form(defaults, kinds=kinds, hass=self.hass),
            errors=errors,
            description_placeholders=_form_placeholders(
                mcp_url=str(defaults.get(CONF_MCP_URL) or ""),
                mcp_auto=mcp_auto,
            ),
        )

    async def async_step_cursor(self, user_input=None):
        current = self._current()
        errors = {}
        discovered = hassio_runtime_url(self.hass) or ""
        if user_input is not None:
            flat = _normalize(_flatten(user_input), current, self.hass)
            configured = str(flat.get(CONF_RUNTIME_URL) or discovered or current.get(CONF_RUNTIME_URL) or "").strip()
            runtime = await async_resolve_runtime_url(self.hass, configured)
            if not runtime:
                errors["base"] = "no_runtime"
            else:
                return self._save(
                    {
                        **flat,
                        CONF_MODE: MODE_CURSOR,
                        CONF_MODEL: _cursor_model({**current, **flat, CONF_MODE: MODE_CURSOR}),
                        CONF_RUNTIME_URL: runtime,
                    }
                )
            current = {**current, **flat}
        defaults, mcp_auto, kinds = await _prepare_mcp_form(self.hass, current)
        return self.async_show_form(
            step_id="cursor",
            data_schema=_cursor_form(defaults, kinds=kinds, runtime_url=True, hass=self.hass),
            errors=errors,
            description_placeholders=await _cursor_placeholders(self.hass, defaults, mcp_auto),
        )
