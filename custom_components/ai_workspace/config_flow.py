from __future__ import annotations

from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    API_COMPATIBLE,
    API_OPENAI,
    API_PROVIDERS,
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
    CLOUD_ONLY_MODELS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DOMAIN,
    HOST_RUNTIME_URL,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_KINDS,
    MODE_API,
    MODE_CURSOR,
    default_api_model,
    mcp_kind_options,
)
from .discovery import async_probe_runtime, async_resolve_runtime_url, hassio_runtime_url
from .mcp_resolve import async_detect_mcp_kinds, async_probe_mcp, async_resolve_mcp_url, default_mcp_url, mcp_kind_of

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
    CONF_RUNTIME_URL,
    CONF_ENABLE_OVERLAY,
    CONF_ENABLE_SIDEBAR,
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
    for key in (SECTION_PROVIDER, SECTION_MCP, SECTION_PROMPT):
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
