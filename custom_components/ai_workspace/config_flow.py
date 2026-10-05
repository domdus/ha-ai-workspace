from __future__ import annotations

from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    API_ANTHROPIC,
    API_COMPATIBLE,
    API_OPENAI,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
    CONF_MCP_KIND,
    CONF_MCP_TOKEN,
    CONF_MCP_URL,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_URL,
    CONF_SYSTEM_PROMPT,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_API_MODEL,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DOMAIN,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_KINDS,
    MODE_API,
    MODE_CURSOR,
)
from .discovery import async_resolve_runtime_url, hassio_runtime_url
from .mcp_resolve import async_resolve_mcp_url, default_mcp_url, mcp_kind_of

_PROVIDERS = {
    API_OPENAI: "OpenAI",
    API_ANTHROPIC: "Claude (Anthropic)",
}
_ADVANCED_PROVIDERS = {
    **_PROVIDERS,
    API_COMPATIBLE: "OpenAI-compatible (custom base URL)",
}

SECTION_PROVIDER = "provider"
SECTION_MCP = "mcp"
SECTION_PROMPT = "prompt"
_OPTION_KEYS = (
    CONF_MODE,
    CONF_API_PROVIDER,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_API_BASE,
    CONF_MCP_KIND,
    CONF_MCP_URL,
    CONF_MCP_TOKEN,
    CONF_SYSTEM_PROMPT,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
)
_MCP_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PROMPT_SELECTOR = TextSelector(TextSelectorConfig(multiline=True))


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
    }


def _provider_schema(defaults: dict | None = None, *, advanced: bool = False):
    current = defaults or {}
    kind = current.get(CONF_API_PROVIDER, API_OPENAI)
    model = str(current.get(CONF_MODEL) or "").strip()
    if model == DEFAULT_MODEL:
        model = ""
    if not model:
        model = DEFAULT_ANTHROPIC_MODEL if kind == API_ANTHROPIC else DEFAULT_API_MODEL
    providers = dict(_ADVANCED_PROVIDERS if advanced else _PROVIDERS)
    if kind == API_COMPATIBLE:
        providers = dict(_ADVANCED_PROVIDERS)
        advanced = True
    schema = {
        vol.Required(
            CONF_API_PROVIDER,
            default=kind if kind in providers else API_OPENAI,
        ): vol.In(providers),
        vol.Optional(CONF_API_KEY, default=current.get(CONF_API_KEY, "")): cv.string,
        vol.Optional(CONF_MODEL, default=model): cv.string,
    }
    if advanced:
        schema[vol.Optional(CONF_API_BASE, default=current.get(CONF_API_BASE, ""))] = cv.string
    return vol.Schema(schema)


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
    return out


def _mcp_schema(defaults: dict | None = None, hass: HomeAssistant | None = None):
    current = defaults or {}
    kind = mcp_kind_of(current)
    return vol.Schema(
        {
            vol.Required(CONF_MCP_KIND, default=kind if kind in MCP_KINDS else "ha_mcp"): vol.In(MCP_KINDS),
            vol.Optional(CONF_MCP_URL, default=_mcp_url_for_form(current, hass)): _MCP_SELECTOR,
            vol.Optional(CONF_MCP_TOKEN, default=""): _TOKEN_SELECTOR,
        }
    )


async def _defaults_with_mcp(hass: HomeAssistant, current: dict) -> dict:
    data = dict(current)
    kind = mcp_kind_of(data)
    found = await async_resolve_mcp_url(
        hass,
        kind,
        str(data.get(CONF_MCP_URL) or "").strip(),
        str(data.get(CONF_MCP_TOKEN) or "").strip(),
    )
    if found:
        data[CONF_MCP_URL] = found
    return data


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
    for key in (SECTION_PROVIDER, SECTION_MCP, SECTION_PROMPT):
        nested = out.pop(key, None)
        if isinstance(nested, dict):
            out.update(nested)
    return out


def _api_form(defaults: dict, *, advanced: bool = False, hass: HomeAssistant | None = None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(SECTION_PROVIDER): section(
                _provider_schema(defaults, advanced=advanced), {"collapsed": False}
            ),
            vol.Required(SECTION_MCP): section(_mcp_schema(defaults, hass), {"collapsed": False}),
            vol.Required(SECTION_PROMPT): section(_prompt_schema(defaults), {"collapsed": False}),
            **_ui_schema(defaults),
        }
    )


def _cursor_form(defaults: dict, *, runtime_url: bool = False, hass: HomeAssistant | None = None) -> vol.Schema:
    schema: dict = {
        vol.Required(SECTION_MCP): section(_mcp_schema(defaults, hass), {"collapsed": False}),
    }
    if runtime_url:
        schema[vol.Optional(CONF_RUNTIME_URL, default=defaults.get(CONF_RUNTIME_URL, ""))] = cv.string
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


class AiWorkspaceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._ui: dict = {}

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        return self.async_show_menu(step_id="user", menu_options=["api", "cursor"])

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
                    CONF_RUNTIME_URL: runtime,
                }
                await self.async_set_unique_id(DOMAIN)
                return self.async_create_entry(title="AI Workspace", data=data)
        defaults = await _defaults_with_mcp(self.hass, self._ui)
        return self.async_show_form(
            step_id="cursor",
            data_schema=_cursor_form(defaults, runtime_url=not discovered, hass=self.hass),
            errors=errors,
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
        defaults = await _defaults_with_mcp(self.hass, user_input or self._ui)
        return self.async_show_form(
            step_id="api",
            data_schema=_api_form(defaults, advanced=self.show_advanced_options, hass=self.hass),
            errors=errors,
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
        return AiWorkspaceOptionsFlow()


class AiWorkspaceOptionsFlow(config_entries.OptionsFlow):
    def _current(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options}

    def _save(self, updates: dict):
        current = {**self._current(), **updates}
        return self.async_create_entry(title="", data={key: current.get(key) for key in _OPTION_KEYS})

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["api", "cursor"])

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
        defaults = await _defaults_with_mcp(self.hass, current)
        return self.async_show_form(
            step_id="api",
            data_schema=_api_form(defaults, advanced=self.show_advanced_options, hass=self.hass),
            errors=errors,
        )

    async def async_step_cursor(self, user_input=None):
        current = self._current()
        if user_input is not None:
            return self._save({**_normalize(_flatten(user_input), current, self.hass), CONF_MODE: MODE_CURSOR})
        defaults = await _defaults_with_mcp(self.hass, current)
        return self.async_show_form(
            step_id="cursor",
            data_schema=_cursor_form(defaults, hass=self.hass),
        )
