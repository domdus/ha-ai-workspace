"""Add and edit one agent row on the AI Workspace entry."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util.ulid import ulid

from .agents import borrow_by_id, borrowed_setups, entry_agents
from .const import (
    API_OPENROUTER,
    CONF_MODELS,
    parse_model_list,
    CONF_SAVE_TOKENS,
    SECTION_ADVANCED,
    API_ANTHROPIC,
    API_AZURE,
    API_COMPATIBLE,
    API_OLLAMA,
    API_PROVIDERS,
    API_SHORT_LABELS,
    CONF_AGENT_ID,
    CONF_ALLOW_INTERNET,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_ASSIST,
    CONF_ASSIST_STT,
    CONF_ASSIST_TTS,
    CONF_STT_MODEL,
    CONF_TTS_MODEL,
    CONF_TTS_SPEED,
    CONF_TTS_VOICE,
    CONF_AZURE_API_VERSION,
    CONF_BORROW,
    CONF_CLAUDE_API_KEY,
    CONF_CURSOR_API_KEY,
    CONF_EFFORT,
    CONF_LOW_TOKEN,
    CONF_CACHE_1H,
    CONF_PROMPT_CACHE,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_TOKEN,
    CONF_RUNTIME_URL,
    DEFAULT_AZURE_API_VERSION,
    EFFORT_DEFAULT,
    EFFORTS,
    MODE_API,
    MODE_CLAUDE,
    MODE_CURSOR,
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
    assist_enabled,
    assist_stt_enabled,
    assist_tts_enabled,
    provider_supports_stt,
    provider_supports_tts,
    provider_supports_tts_speed,
    provider_has_tts_model,
    api_key_url,
    api_model_choices,
    default_api_base,
    default_api_model,
    default_stt_model,
    default_tts_model,
    resolved_tts_speed,
    resolved_tts_voice,
    tts_speed_choice,
    stt_model_choices,
    tts_model_choices,
    tts_speeds,
    tts_voices,
    submitted_model,
    token_mode_of,
)
from .discovery import (
    async_detect_runtime_url,
    async_probe_runtime,
    async_resolve_runtime_url,
    async_runtime_form_url,
    async_runtime_health,
    runtime_form_placeholders,
)

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_DETAIL = {
    MODE_CURSOR: "cursor",
    MODE_CLAUDE: "claude",
    API_OLLAMA: "ollama",
    API_AZURE: "azure",
    API_COMPATIBLE: "compatible",
}


def _agent_choices() -> dict[str, str]:
    return {MODE_CURSOR: "Cursor", MODE_CLAUDE: "Claude SDK", **API_PROVIDERS}


def _provider_schema(current: dict) -> vol.Schema:
    provider = str(current.get(CONF_API_PROVIDER) or MODE_CURSOR)
    if provider not in _agent_choices():
        provider = MODE_CURSOR
    return vol.Schema(
        {
            vol.Required(CONF_API_PROVIDER, default=provider): SelectSelector(
                SelectSelectorConfig(options=list(_agent_choices()), mode="dropdown", translation_key="agent_provider")
            ),
        }
    )


def _effort_field(current: dict) -> dict:
    return {
        vol.Optional(CONF_EFFORT, default=str(current.get(CONF_EFFORT) or EFFORT_DEFAULT)): SelectSelector(
            SelectSelectorConfig(options=list(EFFORTS), mode="dropdown", translation_key="effort")
        ),
    }


def _model_field(provider: str, current: dict, *, required: bool = False, choices: list[str] | None = None) -> dict:
    stored = str(current.get(CONF_MODEL) or "").strip()
    fallback = default_api_model(provider)
    if choices is None:
        choices = api_model_choices(provider)
    if choices:
        options = list(choices)
        if stored and stored not in options:
            options.insert(0, stored)
        shown = stored or fallback
        selector = SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, mode="dropdown")
        )
        key = vol.Required(CONF_MODEL, default=shown) if required else vol.Optional(CONF_MODEL, default=shown)
        return {key: selector}
    suggested = stored or fallback
    if required:
        return {vol.Required(CONF_MODEL, default=stored, description={"suggested_value": suggested}): str}
    return {vol.Optional(CONF_MODEL, default="", description={"suggested_value": suggested}): str}


_MODEL_LIST = TextSelector(TextSelectorConfig(multiline=True))
# Every agent can have its own model list, in a folded section below the model field.
SECTION_MODEL_LIST = "model_list"
# Gateways often limit which models a key may use; one tiny chat turn on save shows their reason.
_TEST_MODEL = {API_COMPATIBLE, API_OPENROUTER}


def submitted_models(user_input: dict | None) -> list[str]:
    if not user_input:
        return []
    if CONF_MODELS in user_input:
        return parse_model_list(user_input.get(CONF_MODELS))
    folded = user_input.get(SECTION_MODEL_LIST)
    return parse_model_list(folded.get(CONF_MODELS)) if isinstance(folded, dict) else []


def _models_section(current: dict) -> dict:
    stored = parse_model_list(current.get(CONF_MODELS))
    inner = {vol.Optional(CONF_MODELS, description={"suggested_value": "\n".join(stored)}): _MODEL_LIST}
    return {vol.Required(SECTION_MODEL_LIST): section(vol.Schema(inner), {"collapsed": True})}


def model_with_list(model: str, models: list[str], stored_model: str, default_model: str) -> tuple[str, list[str]]:
    """Fit the chosen model to a pasted list.

    The form's untouched default is not a real choice, so the list's first entry wins. A model the
    user typed themselves stays and is added to the list.
    """
    if not models or model in models:
        return model, models
    if not model or (model == default_model and model != stored_model):
        return models[0], models
    return model, [model, *models]


def _stt_model_field(provider: str, current: dict) -> dict:
    stored = str(current.get(CONF_STT_MODEL) or "").strip()
    fallback = default_stt_model(provider)
    choices = stt_model_choices(provider)
    shown = stored or fallback
    if not choices:
        return {vol.Optional(CONF_STT_MODEL, default="", description={"suggested_value": shown}): str}
    options = list(choices)
    if stored and stored not in options:
        options.insert(0, stored)
    return {
        vol.Optional(CONF_STT_MODEL, default=shown): SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, mode="dropdown")
        )
    }


def _tts_model_field(provider: str, current: dict) -> dict:
    stored = str(current.get(CONF_TTS_MODEL) or "").strip()
    fallback = default_tts_model(provider)
    choices = tts_model_choices(provider)
    shown = stored or fallback
    if not choices:
        return {vol.Optional(CONF_TTS_MODEL, default="", description={"suggested_value": shown}): str}
    options = list(choices)
    if stored and stored not in options:
        options.insert(0, stored)
    return {
        vol.Optional(CONF_TTS_MODEL, default=shown): SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, mode="dropdown")
        )
    }


def _tts_voice_field(provider: str, current: dict) -> dict:
    shown = resolved_tts_voice(current, provider)
    options = list(tts_voices(provider))
    if shown and shown not in options:
        options.insert(0, shown)
    return {
        vol.Optional(CONF_TTS_VOICE, default=shown): SelectSelector(
            SelectSelectorConfig(options=options, custom_value=True, mode="dropdown")
        )
    }


def _tts_speed_field(current: dict, provider: str = "") -> dict:
    shown = tts_speed_choice(resolved_tts_speed(current, provider))
    options = [{"value": tts_speed_choice(item), "label": f"{tts_speed_choice(item)}×"} for item in tts_speeds(provider)]
    if shown and shown not in {item["value"] for item in options}:
        options.insert(0, {"value": shown, "label": f"{shown}×"})
    return {
        vol.Optional(CONF_TTS_SPEED, default=shown): SelectSelector(
            SelectSelectorConfig(options=options, mode="dropdown")
        )
    }


def _fields_schema(
    step: str,
    current: dict,
    borrows: list[dict[str, str]],
    *,
    new: bool = False,
    models: list[str] | None = None,
) -> vol.Schema:
    provider = str(current.get(CONF_API_PROVIDER) or MODE_CURSOR)
    fields: dict = {}
    if step == "cursor":
        fields[vol.Optional(CONF_RUNTIME_URL, default=str(current.get(CONF_RUNTIME_URL) or ""))] = _URL
        fields[vol.Optional(CONF_RUNTIME_TOKEN, default="")] = _PASSWORD
        fields[vol.Optional(CONF_CURSOR_API_KEY, default="")] = _PASSWORD
        fields.update(_model_field(MODE_CURSOR, current, choices=models))
    elif step == "claude":
        fields[vol.Optional(CONF_RUNTIME_URL, default=str(current.get(CONF_RUNTIME_URL) or ""))] = _URL
        fields[vol.Optional(CONF_RUNTIME_TOKEN, default="")] = _PASSWORD
        fields[vol.Optional(CONF_CLAUDE_API_KEY, default="")] = _PASSWORD
        fields.update(_model_field(MODE_CLAUDE, current, choices=models))
    elif step == "ollama":
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or default_api_base(API_OLLAMA)))] = str
        fields.update(_model_field(API_OLLAMA, current, choices=models))
    elif step == "azure":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields.update(_model_field(API_AZURE, current, required=True, choices=models))
        fields[vol.Optional(CONF_AZURE_API_VERSION, default=str(current.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION))] = str
    elif step == "compatible":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields.update(_model_field(API_COMPATIBLE, current, choices=models))
    else:
        if borrows:
            options = [{"value": "", "label": "Enter it here"}]
            options.extend({"value": item["id"], "label": item["label"]} for item in borrows)
            fields[vol.Optional(CONF_BORROW, default="")] = SelectSelector(
                SelectSelectorConfig(options=options, mode="dropdown")
            )
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields.update(_model_field(provider, current, choices=models))
    fields.update(_models_section(current))
    fields.update(_effort_field(current))
    fields[vol.Optional(CONF_ALLOW_INTERNET, default=bool(current.get(CONF_ALLOW_INTERNET, False)))] = cv.boolean
    fields[vol.Optional(CONF_ASSIST, default=assist_enabled(current, new=new))] = cv.boolean
    if provider_supports_stt(provider):
        fields[vol.Optional(CONF_ASSIST_STT, default=assist_stt_enabled(current, provider, new=new))] = cv.boolean
        fields.update(_stt_model_field(provider, current))
    if provider_supports_tts(provider):
        fields[vol.Optional(CONF_ASSIST_TTS, default=assist_tts_enabled(current, provider, new=new))] = cv.boolean
        if provider_has_tts_model(provider):
            fields.update(_tts_model_field(provider, current))
        fields.update(_tts_voice_field(provider, current))
        if provider_supports_tts_speed(provider):
            fields.update(_tts_speed_field(current, provider))
    # Rarely needed, so it stays folded away.
    advanced = {vol.Optional(CONF_SAVE_TOKENS, default=saves_tokens(current)): cv.boolean}
    if step == "cloud" and provider == API_ANTHROPIC:
        advanced[vol.Optional(CONF_CACHE_1H, default=caches_an_hour(current))] = cv.boolean
    fields[vol.Required(SECTION_ADVANCED)] = section(vol.Schema(advanced), {"collapsed": True})
    return vol.Schema(fields)


def ollama_has_model(installed: list[str], model: str) -> bool:
    def tagged(name: str) -> str:
        name = str(name or "").strip()
        return name if ":" in name else f"{name}:latest"

    return tagged(model) in {tagged(name) for name in installed}


def saves_tokens(current: dict) -> bool:
    """Checkbox state: from the form when it was shown again, else from the stored level."""
    advanced = current.get(SECTION_ADVANCED)
    if isinstance(advanced, dict) and CONF_SAVE_TOKENS in advanced:
        return bool(advanced[CONF_SAVE_TOKENS])
    return token_mode_of(current.get(CONF_LOW_TOKEN, TOKEN_MODE_OFF)) in {TOKEN_MODE_MEDIUM, TOKEN_MODE_EXTREME}


def caches_an_hour(current: dict) -> bool:
    """1-hour cache checkbox: from the form when it was shown again, else from the stored agent."""
    advanced = current.get(SECTION_ADVANCED)
    if isinstance(advanced, dict) and CONF_CACHE_1H in advanced:
        return bool(advanced[CONF_CACHE_1H])
    return bool(current.get(CONF_CACHE_1H, False))


def stored_token_mode(current: dict, save: bool) -> str:
    """Save tokens is Medium. A chat-only (Extreme) agent stays chat only while the box stays on."""
    if not save:
        return TOKEN_MODE_OFF
    if token_mode_of(current.get(CONF_LOW_TOKEN, TOKEN_MODE_OFF)) == TOKEN_MODE_EXTREME:
        return TOKEN_MODE_EXTREME
    return TOKEN_MODE_MEDIUM


def _title(provider: str, used: set[str]) -> str:
    if provider == MODE_CURSOR:
        base = "Cursor"
    elif provider == MODE_CLAUDE:
        base = "Claude SDK"
    else:
        base = API_SHORT_LABELS.get(provider, "Agent")
    if base not in used:
        return base
    number = 2
    while f"{base} {number}" in used:
        number += 1
    return f"{base} {number}"


class AgentSubentryFlow(config_entries.ConfigSubentryFlow):
    """One agent on AI Workspace. The form asks only for that provider."""

    def __init__(self) -> None:
        self._editing = False
        self._current: dict[str, Any] = {}
        self._provider = MODE_CURSOR

    async def async_step_user(self, user_input=None):
        del user_input
        self._editing = False
        self._current = {}
        self._provider = MODE_CURSOR
        return await self.async_step_provider()

    async def async_step_reconfigure(self, user_input=None):
        del user_input
        self._editing = True
        self._current = dict(self._get_reconfigure_subentry().data)
        self._provider = str(self._current.get(CONF_API_PROVIDER) or MODE_CURSOR)
        return await self.async_step_provider()

    async def async_step_provider(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            provider = str(user_input.get(CONF_API_PROVIDER) or MODE_CURSOR)
            if provider not in _agent_choices():
                provider = MODE_CURSOR
            self._provider = provider
            self._current = {**self._current, CONF_API_PROVIDER: provider}
            return await getattr(self, f"async_step_provider_{_DETAIL.get(provider, 'cloud')}")()
        return self.async_show_form(step_id="provider", data_schema=_provider_schema(self._current))

    async def async_step_provider_cursor(self, user_input=None):
        return await self._async_step_fields("cursor", user_input)

    async def async_step_provider_claude(self, user_input=None):
        return await self._async_step_fields("claude", user_input)

    async def async_step_provider_cloud(self, user_input=None):
        return await self._async_step_fields("cloud", user_input)

    async def async_step_provider_ollama(self, user_input=None):
        return await self._async_step_fields("ollama", user_input)

    async def async_step_provider_azure(self, user_input=None):
        return await self._async_step_fields("azure", user_input)

    async def async_step_provider_compatible(self, user_input=None):
        return await self._async_step_fields("compatible", user_input)

    async def _cursor_errors(self, cursor_key: str, runtime_url: str) -> dict[str, str]:
        runtime = await async_resolve_runtime_url(self.hass, runtime_url)
        health = await async_runtime_health(self.hass, runtime) if runtime else None
        if health is None:
            return {CONF_RUNTIME_URL: "no_runtime"}
        if not cursor_key and not health.get("cursor"):
            return {CONF_CURSOR_API_KEY: "required"}
        return {}

    async def _claude_errors(self, claude_key: str, runtime_url: str) -> dict[str, str]:
        runtime = await async_resolve_runtime_url(self.hass, runtime_url)
        health = await async_runtime_health(self.hass, runtime) if runtime else None
        if health is None:
            return {CONF_RUNTIME_URL: "no_runtime"}
        if "claude" not in health:
            return {CONF_RUNTIME_URL: "claude_runtime_old"}
        if not claude_key and not health.get("claude"):
            return {CONF_CLAUDE_API_KEY: "required"}
        # A Claude Plan token (claude setup-token) signs in through Claude Code; only API keys
        # can be checked against Anthropic's key endpoint here.
        if claude_key and not claude_key.startswith("sk-ant-oat"):
            from .api_provider import async_check_api_key

            problem = await async_check_api_key(
                self.hass, API_ANTHROPIC, claude_key, default_api_base(API_ANTHROPIC), DEFAULT_AZURE_API_VERSION
            )
            if problem == "invalid_auth":
                return {CONF_CLAUDE_API_KEY: "invalid_auth"}
            if problem:
                return {"base": problem}
        return {}

    async def _store_runtime(self, submitted_url: str, submitted_token: str) -> None:
        entry = self._get_entry()
        detected = await async_detect_runtime_url(self.hass)
        url = str(submitted_url or "").strip().rstrip("/")
        if not url or (detected and url.rstrip("/") == detected.rstrip("/")):
            url = ""
        token = str(submitted_token or "").strip()
        current = {**entry.data, **entry.options}
        if not token:
            token = str(current.get(CONF_RUNTIME_TOKEN) or "")
        options = dict(entry.options)
        if str(options.get(CONF_RUNTIME_URL) or "") == url and str(options.get(CONF_RUNTIME_TOKEN) or "") == token:
            return
        options[CONF_RUNTIME_URL] = url
        options[CONF_RUNTIME_TOKEN] = token
        self.hass.config_entries.async_update_entry(entry, options=options)

    async def _model_choices(self, provider: str, current: dict) -> list[str] | None:
        """The provider's own model list with the key on this agent; None keeps the bundled list."""
        from .model_list import async_cursor_models, async_provider_models, merge_models, own_models

        own = parse_model_list(current.get(CONF_MODELS))
        if own:
            return own_models(str(current.get(CONF_MODEL) or ""), own)
        if provider == API_AZURE:
            return None
        if provider == MODE_CURSOR:
            live = await async_cursor_models(self.hass, str(current.get(CONF_CURSOR_API_KEY) or ""))
        elif provider == MODE_CLAUDE:
            from .const import api_model_choices

            return api_model_choices(MODE_CLAUDE)
        else:
            live = await async_provider_models(
                self.hass, provider, str(current.get(CONF_API_KEY) or ""), str(current.get(CONF_API_BASE) or "")
            )
        if not live:
            return None
        return merge_models(provider, str(current.get(CONF_MODEL) or ""), live)

    async def _ollama_model_errors(self, base: str, model: str) -> dict[str, str]:
        """Catch a model name Ollama does not have, such as a family name without its size tag."""
        from .model_list import async_provider_models, forget_provider_models

        installed = await async_provider_models(self.hass, API_OLLAMA, "", base)
        if installed and not ollama_has_model(installed, model):
            # The list is cached for an hour; the model may have been pulled just now.
            forget_provider_models(self.hass, API_OLLAMA, "", base)
            installed = await async_provider_models(self.hass, API_OLLAMA, "", base)
        if not installed or ollama_has_model(installed, model):
            return {}
        self._installed = ", ".join(installed[:12])
        return {CONF_MODEL: "model_not_installed"}

    async def _gateway_model_errors(
        self, provider: str, key: str, base: str, model: str, stored_model: str, own_list: list[str]
    ) -> dict[str, str]:
        """Before saving: offer the server's list, then let the server say whether this key may use the model."""
        from .api_provider import async_check_model
        from .model_list import async_provider_models

        untouched = not model or (model == default_api_model(provider) and model != stored_model)
        if untouched and not own_list:
            live = await async_provider_models(self.hass, provider, key, base)
            if live and (model or default_api_model(provider)) not in live:
                # The form comes back with the server's list in the model dropdown.
                self._suggested_model = live[0]
                return {CONF_MODEL: "pick_model"}
        problem = await async_check_model(self.hass, provider, key, base, model or default_api_model(provider))
        if problem:
            self._server_message = problem
            return {CONF_MODEL: "model_rejected"}
        return {}

    async def _key_errors(self, provider: str, key: str, base: str, version: str) -> dict[str, str]:
        from .api_provider import async_check_api_key

        problem = await async_check_api_key(self.hass, provider, key, base, version)
        if problem is None:
            return {}
        field = CONF_API_BASE if problem == "cannot_connect" and provider in _DETAIL else "base"
        if problem == "invalid_auth":
            field = CONF_API_KEY
        return {field: problem}

    async def _async_step_fields(self, step: str, user_input: dict[str, Any] | None):
        current = self._current
        provider = self._provider
        borrows = [item for item in borrowed_setups(self.hass) if item.get("provider") == provider]
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**current, **user_input, CONF_API_PROVIDER: provider}
            borrowed = borrow_by_id(self.hass, str(user_input.get(CONF_BORROW) or ""))
            if borrowed and borrowed.get("provider") == provider and not str(user_input.get(CONF_API_KEY) or "").strip():
                merged[CONF_API_KEY] = borrowed["api_key"]
                merged[CONF_API_BASE] = borrowed["api_base"]
                merged[CONF_AZURE_API_VERSION] = borrowed.get("azure_api_version") or DEFAULT_AZURE_API_VERSION
            cursor_key = str(merged.get(CONF_CURSOR_API_KEY) or current.get(CONF_CURSOR_API_KEY) or "").strip()
            claude_key = str(merged.get(CONF_CLAUDE_API_KEY) or current.get(CONF_CLAUDE_API_KEY) or "").strip()
            key = str(merged.get(CONF_API_KEY) or current.get(CONF_API_KEY) or "").strip()
            base = str(merged.get(CONF_API_BASE) or "").strip() or default_api_base(provider)
            version = str(merged.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION)
            model = submitted_model(user_input)
            if borrowed and borrowed.get("provider") == provider and not model:
                model = str(borrowed.get("model") or "").strip()
            stored_model = str(current.get(CONF_MODEL) or "")
            own_list = submitted_models(user_input)
            model, own_list = model_with_list(model, own_list, stored_model, default_api_model(provider))
            merged[CONF_MODELS] = own_list
            if provider == MODE_CURSOR:
                errors = await self._cursor_errors(
                    cursor_key, str(merged.get(CONF_RUNTIME_URL) or "")
                )
            elif provider == MODE_CLAUDE:
                errors = await self._claude_errors(
                    claude_key, str(merged.get(CONF_RUNTIME_URL) or "")
                )
            elif provider == API_OLLAMA:
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
            elif provider == API_AZURE:
                if not key:
                    errors[CONF_API_KEY] = "required"
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
                if not model:
                    errors[CONF_MODEL] = "required"
            elif provider == API_COMPATIBLE:
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
            elif not key:
                errors[CONF_API_KEY] = "required"
            if not errors and provider not in {MODE_CURSOR, MODE_CLAUDE}:
                errors = await self._key_errors(provider, key, base, version)
            if not errors and provider == API_OLLAMA:
                errors = await self._ollama_model_errors(base, model or default_api_model(API_OLLAMA))
            if not errors and provider in _TEST_MODEL:
                errors = await self._gateway_model_errors(provider, key, base, model, stored_model, own_list)
                if errors.get(CONF_MODEL) == "pick_model":
                    merged[CONF_MODEL] = self._suggested_model
            if not errors:
                if provider in {MODE_CURSOR, MODE_CLAUDE}:
                    await self._store_runtime(
                        str(merged.get(CONF_RUNTIME_URL) or ""),
                        str(user_input.get(CONF_RUNTIME_TOKEN) or ""),
                    )
                effort = str(merged.get(CONF_EFFORT) or "")
                data = {
                    CONF_MODE: provider
                    if provider in {MODE_CURSOR, MODE_CLAUDE}
                    else MODE_API,
                    CONF_API_PROVIDER: provider,
                    CONF_CURSOR_API_KEY: cursor_key if provider == MODE_CURSOR else "",
                    CONF_CLAUDE_API_KEY: claude_key if provider == MODE_CLAUDE else "",
                    CONF_API_KEY: "" if provider in {MODE_CURSOR, MODE_CLAUDE} else key,
                    CONF_API_BASE: "" if provider in {MODE_CURSOR, MODE_CLAUDE} else base,
                    CONF_MODEL: model,
                    CONF_EFFORT: "" if effort == EFFORT_DEFAULT else effort,
                    CONF_LOW_TOKEN: stored_token_mode(current, saves_tokens(merged)),
                    CONF_ALLOW_INTERNET: bool(merged.get(CONF_ALLOW_INTERNET, False)),
                    CONF_ASSIST: bool(user_input.get(CONF_ASSIST, assist_enabled(current, new=not self._editing))),
                    CONF_ASSIST_STT: bool(
                        user_input.get(
                            CONF_ASSIST_STT,
                            assist_stt_enabled(current, provider, new=not self._editing),
                        )
                    )
                    if provider_supports_stt(provider)
                    else False,
                    CONF_STT_MODEL: str(user_input.get(CONF_STT_MODEL) or "").strip()
                    if provider_supports_stt(provider)
                    else "",
                    CONF_ASSIST_TTS: bool(
                        user_input.get(
                            CONF_ASSIST_TTS,
                            assist_tts_enabled(current, provider, new=not self._editing),
                        )
                    )
                    if provider_supports_tts(provider)
                    else False,
                    CONF_TTS_MODEL: str(user_input.get(CONF_TTS_MODEL) or "").strip()
                    if provider_has_tts_model(provider)
                    else "",
                    CONF_TTS_VOICE: str(user_input.get(CONF_TTS_VOICE) or "").strip()
                    if provider_supports_tts(provider)
                    else "",
                    CONF_TTS_SPEED: tts_speed_choice(
                        resolved_tts_speed(user_input if provider_supports_tts_speed(provider) else {}, provider)
                    )
                    if provider_supports_tts_speed(provider)
                    else "",
                    CONF_AZURE_API_VERSION: version if provider == API_AZURE else "",
                }
                data[CONF_MODELS] = own_list
                if provider == API_ANTHROPIC:
                    data[CONF_CACHE_1H] = caches_an_hour(merged)
                if provider not in {MODE_CURSOR, MODE_CLAUDE} and CONF_PROMPT_CACHE in current:
                    data[CONF_PROMPT_CACHE] = bool(current.get(CONF_PROMPT_CACHE))
                return self._finish(provider, data)
            self._current = merged
        example = "https://YOUR-RESOURCE.openai.azure.com" if step == "azure" else default_api_base(API_OLLAMA)
        placeholders = {
            "example_url": example,
            "api_key_url": api_key_url(provider),
            "installed": getattr(self, "_installed", "") or "-",
            "server_message": getattr(self, "_server_message", "") or "-",
        }
        schema_current = dict(self._current)
        if step == "ollama":
            from .ollama_info import async_ollama_server, ollama_form_note

            url = str(schema_current.get(CONF_API_BASE) or default_api_base(API_OLLAMA))
            placeholders["ollama_note"] = ollama_form_note(
                await async_ollama_server(self.hass, url), example, self.hass.config.language
            )
        if step in {"cursor", "claude"}:
            entry = self._get_entry()
            saved = str({**entry.data, **entry.options}.get(CONF_RUNTIME_URL) or "")
            typed = str((user_input or {}).get(CONF_RUNTIME_URL) or "")
            if typed:
                shown = typed.strip().rstrip("/")
                live = await async_probe_runtime(self.hass, shown)
                auto = False
            else:
                shown, live, auto = await async_runtime_form_url(self.hass, saved)
            schema_current[CONF_RUNTIME_URL] = shown
            placeholders.update(runtime_form_placeholders(live=live, auto=auto, language=self.hass.config.language))
        return self.async_show_form(
            step_id=f"provider_{step}",
            data_schema=_fields_schema(
                step,
                schema_current,
                borrows,
                new=not self._editing,
                models=await self._model_choices(provider, schema_current),
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    def _finish(self, provider: str, data: dict[str, Any]):
        entry = self._get_entry()
        titles = {agent.title for agent in entry_agents(entry)}
        if self._editing:
            sub = self._get_reconfigure_subentry()
            titles.discard(sub.title)
            same = str(sub.data.get(CONF_API_PROVIDER) or "") == provider
            title = sub.title if same else _title(provider, titles)
            data[CONF_AGENT_ID] = str(sub.data.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)
            return self.async_update_and_abort(entry, sub, title=title, data=data, unique_id=data[CONF_AGENT_ID])
        data[CONF_AGENT_ID] = ulid()
        return self.async_create_entry(title=_title(provider, titles), data=data, unique_id=data[CONF_AGENT_ID])
