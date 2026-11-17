"""Add and edit one agent row on the AI Workspace entry."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
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
    API_OPENAI,
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
    CONF_USE_CLAUDE_RUNTIME,
    CONF_CODEX_API_KEY,
    CONF_USE_CODEX_RUNTIME,
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
    MODE_CODEX,
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
    API_OLLAMA: "ollama",
    API_AZURE: "azure",
    API_COMPATIBLE: "compatible",
}

SECTION_CLAUDE_RUNTIME = "claude_runtime"
SECTION_CODEX_RUNTIME = "codex_runtime"
# Engine name in the Runtime's sign-in API (/api/auth/{engine}).
ENGINE_CLAUDE = "claude"
ENGINE_CODEX = "codex"
# Cloud providers that can run on the AI Workspace Runtime instead (Advanced switch), per provider.
RUNTIME_SWITCH = {API_ANTHROPIC: CONF_USE_CLAUDE_RUNTIME, API_OPENAI: CONF_USE_CODEX_RUNTIME}
RUNTIME_SECTION = {API_ANTHROPIC: SECTION_CLAUDE_RUNTIME, API_OPENAI: SECTION_CODEX_RUNTIME}
RUNTIME_KEY = {API_ANTHROPIC: CONF_CLAUDE_API_KEY, API_OPENAI: CONF_CODEX_API_KEY}
RUNTIME_MODE = {API_ANTHROPIC: MODE_CLAUDE, API_OPENAI: MODE_CODEX}
RUNTIME_ENGINE = {API_ANTHROPIC: ENGINE_CLAUDE, API_OPENAI: ENGINE_CODEX}
# A device-code sign-in (Codex) is checked this long each time the user says the code is entered.
_DEVICE_WAIT = 20
CONF_LOGIN_CODE = "code"
# Codes that only need typing again; anything else ended that sign-in on the Runtime.
_RETYPE = frozenset({"bad_code"})


def uses_claude_runtime(current: dict, provider: str = "") -> bool:
    """Anthropic cloud API vs Claude Agent SDK on the AI Workspace Runtime."""
    kind = provider or str(current.get(CONF_API_PROVIDER) or "")
    if kind not in {API_ANTHROPIC, MODE_CLAUDE}:
        return False
    if CONF_USE_CLAUDE_RUNTIME in current:
        return bool(current.get(CONF_USE_CLAUDE_RUNTIME))
    if str(current.get(CONF_MODE) or "") == MODE_CLAUDE:
        return True
    return str(current.get(CONF_API_PROVIDER) or "") == MODE_CLAUDE


def uses_codex_runtime(current: dict, provider: str = "") -> bool:
    """OpenAI cloud API vs OpenAI Codex on the AI Workspace Runtime."""
    kind = provider or str(current.get(CONF_API_PROVIDER) or "")
    if kind not in {API_OPENAI, MODE_CODEX}:
        return False
    if CONF_USE_CODEX_RUNTIME in current:
        return bool(current.get(CONF_USE_CODEX_RUNTIME))
    return str(current.get(CONF_MODE) or "") == MODE_CODEX or kind == MODE_CODEX


def uses_runtime(current: dict, provider: str = "") -> bool:
    """This cloud provider's agent runs on the AI Workspace Runtime (Claude SDK or Codex)."""
    kind = provider or str(current.get(CONF_API_PROVIDER) or "")
    if kind == API_OPENAI:
        return uses_codex_runtime(current, kind)
    return uses_claude_runtime(current, kind)


def _runtime_section_errors(errors: dict[str, str], provider: str = API_ANTHROPIC) -> dict[str, str]:
    """Home Assistant shows no errors on fields inside a section, so these go to the top of the form."""
    key_field = RUNTIME_KEY.get(provider, CONF_CLAUDE_API_KEY)
    out = {key: value for key, value in errors.items() if key not in {CONF_RUNTIME_URL, key_field}}
    for key in (CONF_RUNTIME_URL, key_field):
        code = errors.get(key)
        if code:
            out["base"] = f"{RUNTIME_ENGINE.get(provider, ENGINE_CLAUDE)}_key_required" if code == "required" else code
    return out


def _agent_choices() -> dict[str, str]:
    return {MODE_CURSOR: "Cursor", **API_PROVIDERS}


def _runtime_section(user_input: dict | None, provider: str = API_ANTHROPIC) -> dict:
    folded = (user_input or {}).get(RUNTIME_SECTION.get(provider, SECTION_CLAUDE_RUNTIME))
    return folded if isinstance(folded, dict) else {}


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
        runtime = provider in RUNTIME_SWITCH and uses_runtime(current, provider)
        if not runtime:
            if borrows:
                options = [{"value": "", "label": "Enter it here"}]
                options.extend({"value": item["id"], "label": item["label"]} for item in borrows)
                fields[vol.Optional(CONF_BORROW, default="")] = SelectSelector(
                    SelectSelectorConfig(options=options, mode="dropdown")
                )
            fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        if runtime:
            inner = {
                vol.Optional(CONF_RUNTIME_URL, default=str(current.get(CONF_RUNTIME_URL) or "")): _URL,
                vol.Optional(CONF_RUNTIME_TOKEN, default=""): _PASSWORD,
                vol.Optional(RUNTIME_KEY[provider], default=""): _PASSWORD,
            }
            # Open, so the key field is visible right after the switch is turned on.
            fields[vol.Required(RUNTIME_SECTION[provider])] = section(vol.Schema(inner), {"collapsed": False})
        model_kind = RUNTIME_MODE[provider] if runtime else provider
        fields.update(_model_field(model_kind, current, choices=models))
    fields.update(_models_section(current))
    fields.update(_effort_field(current))
    fields[vol.Optional(CONF_ALLOW_INTERNET, default=bool(current.get(CONF_ALLOW_INTERNET, False)))] = cv.boolean
    fields[vol.Optional(CONF_ASSIST, default=assist_enabled(current, new=new))] = cv.boolean
    # A Codex agent on the Runtime has no OpenAI API key for speech.
    speech = not (provider in RUNTIME_SWITCH and uses_runtime(current, provider))
    if speech and provider_supports_stt(provider):
        fields[vol.Optional(CONF_ASSIST_STT, default=assist_stt_enabled(current, provider, new=new))] = cv.boolean
        fields.update(_stt_model_field(provider, current))
    if speech and provider_supports_tts(provider):
        fields[vol.Optional(CONF_ASSIST_TTS, default=assist_tts_enabled(current, provider, new=new))] = cv.boolean
        if provider_has_tts_model(provider):
            fields.update(_tts_model_field(provider, current))
        fields.update(_tts_voice_field(provider, current))
        if provider_supports_tts_speed(provider):
            fields.update(_tts_speed_field(current, provider))
    # Rarely needed, so it stays folded away.
    advanced = {vol.Optional(CONF_SAVE_TOKENS, default=saves_tokens(current)): cv.boolean}
    if step == "cloud" and provider == API_ANTHROPIC and not uses_claude_runtime(current, provider):
        advanced[vol.Optional(CONF_CACHE_1H, default=caches_an_hour(current))] = cv.boolean
    if step == "cloud" and provider in RUNTIME_SWITCH:
        # Experimental, so it sits under Advanced; OK then shows the fields that belong to it.
        advanced[vol.Optional(RUNTIME_SWITCH[provider], default=uses_runtime(current, provider))] = cv.boolean
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


def runtime_switch(user_input: dict, provider: str = API_ANTHROPIC) -> bool:
    """Use Claude SDK / Codex (runtime), from the Advanced section of the submitted form."""
    key = RUNTIME_SWITCH.get(provider, CONF_USE_CLAUDE_RUNTIME)
    advanced = user_input.get(SECTION_ADVANCED)
    if isinstance(advanced, dict) and key in advanced:
        return bool(advanced[key])
    return bool(user_input.get(key))


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


def _title(provider: str, used: set[str], mode: str = "") -> str:
    if provider == MODE_CURSOR:
        base = "Cursor"
    elif mode == MODE_CODEX:
        base = "Codex"
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
        # Claude SDK agents: the checked agent waits here while the Runtime signs in.
        self._pending: tuple[str, dict[str, Any]] | None = None
        self._target: tuple[str, str] = ("", "")
        self._login: dict[str, Any] | None = None
        self._login_error = ""
        self._auth: dict[str, Any] | None = None
        # Which Runtime engine the account steps are about (claude or codex).
        self._engine = ENGINE_CLAUDE

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
        if self._provider == MODE_CLAUDE:
            self._provider = API_ANTHROPIC
            self._current = {
                **self._current,
                CONF_API_PROVIDER: API_ANTHROPIC,
                CONF_USE_CLAUDE_RUNTIME: True,
            }
        elif self._provider == MODE_CODEX:
            self._provider = API_OPENAI
            self._current = {**self._current, CONF_API_PROVIDER: API_OPENAI, CONF_USE_CODEX_RUNTIME: True}
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
            if ENGINE_CLAUDE in (health.get("login") or []):
                # No credential yet: the next step offers "Sign in with Claude plan".
                return {}
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

    async def _codex_errors(self, codex_key: str, runtime_url: str) -> dict[str, str]:
        runtime = await async_resolve_runtime_url(self.hass, runtime_url)
        health = await async_runtime_health(self.hass, runtime) if runtime else None
        if health is None:
            return {CONF_RUNTIME_URL: "no_runtime"}
        if "codex" not in health:
            return {CONF_RUNTIME_URL: "codex_runtime_old"}
        if not codex_key and not health.get("codex"):
            if ENGINE_CODEX in (health.get("login") or []):
                # No credential yet: the next step offers "Sign in with ChatGPT".
                return {}
            return {CONF_CODEX_API_KEY: "required"}
        if codex_key:
            from .api_provider import async_check_api_key

            problem = await async_check_api_key(
                self.hass, API_OPENAI, codex_key, default_api_base(API_OPENAI), DEFAULT_AZURE_API_VERSION
            )
            if problem == "invalid_auth":
                return {CONF_CODEX_API_KEY: "invalid_auth"}
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
        elif provider == API_ANTHROPIC and uses_claude_runtime(current, provider):
            return api_model_choices(MODE_CLAUDE)
        elif provider == API_OPENAI and uses_codex_runtime(current, provider):
            # Codex offers what the signed-in account may use; empty is Codex's own default.
            return []
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
            if provider in RUNTIME_SWITCH:
                use_runtime = runtime_switch(user_input, provider)
                merged[RUNTIME_SWITCH[provider]] = use_runtime
                if use_runtime:
                    merged.update(_runtime_section(user_input, provider))
            borrowed = borrow_by_id(self.hass, str(user_input.get(CONF_BORROW) or ""))
            if borrowed and borrowed.get("provider") == provider and not str(user_input.get(CONF_API_KEY) or "").strip():
                merged[CONF_API_KEY] = borrowed["api_key"]
                merged[CONF_API_BASE] = borrowed["api_base"]
                merged[CONF_AZURE_API_VERSION] = borrowed.get("azure_api_version") or DEFAULT_AZURE_API_VERSION
            cursor_key = str(merged.get(CONF_CURSOR_API_KEY) or current.get(CONF_CURSOR_API_KEY) or "").strip()
            claude_key = str(merged.get(CONF_CLAUDE_API_KEY) or current.get(CONF_CLAUDE_API_KEY) or "").strip()
            codex_key = str(merged.get(CONF_CODEX_API_KEY) or current.get(CONF_CODEX_API_KEY) or "").strip()
            key = str(merged.get(CONF_API_KEY) or current.get(CONF_API_KEY) or "").strip()
            base = str(merged.get(CONF_API_BASE) or "").strip() or default_api_base(provider)
            version = str(merged.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION)
            model = submitted_model(user_input)
            if borrowed and borrowed.get("provider") == provider and not model:
                model = str(borrowed.get("model") or "").strip()
            stored_model = str(current.get(CONF_MODEL) or "")
            own_list = submitted_models(user_input)
            model_kind = (
                RUNTIME_MODE[provider]
                if provider in RUNTIME_SWITCH and uses_runtime(merged, provider)
                else provider
            )
            model, own_list = model_with_list(model, own_list, stored_model, default_api_model(model_kind))
            merged[CONF_MODELS] = own_list
            use_runtime = provider in RUNTIME_SWITCH and uses_runtime(merged, provider)
            # The switch changed which fields belong on the form (runtime section or cloud API key):
            # show the form again with the right fields instead of saving or failing on fields not shown.
            switched = provider in RUNTIME_SWITCH and use_runtime != (RUNTIME_SECTION[provider] in user_input)
            # Not checked or saved yet: the form comes back with the other fields.
            hold = switched
            if hold:
                pass
            elif provider == MODE_CURSOR:
                errors = await self._cursor_errors(
                    cursor_key, str(merged.get(CONF_RUNTIME_URL) or "")
                )
            elif use_runtime and provider == API_OPENAI:
                errors = _runtime_section_errors(
                    await self._codex_errors(codex_key, str(merged.get(CONF_RUNTIME_URL) or "")), provider
                )
            elif use_runtime:
                errors = _runtime_section_errors(
                    await self._claude_errors(claude_key, str(merged.get(CONF_RUNTIME_URL) or ""))
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
            if not errors and not hold and provider not in {MODE_CURSOR, MODE_CLAUDE} and not use_runtime:
                errors = await self._key_errors(provider, key, base, version)
            if not errors and provider == API_OLLAMA:
                errors = await self._ollama_model_errors(base, model or default_api_model(API_OLLAMA))
            if not errors and not hold and provider in _TEST_MODEL:
                errors = await self._gateway_model_errors(provider, key, base, model, stored_model, own_list)
                if errors.get(CONF_MODEL) == "pick_model":
                    merged[CONF_MODEL] = self._suggested_model
            if not errors and not hold:
                runtime_token = str(
                    (user_input.get(CONF_RUNTIME_TOKEN) if step == "cursor" else _runtime_section(user_input, provider).get(CONF_RUNTIME_TOKEN))
                    or user_input.get(CONF_RUNTIME_TOKEN)
                    or ""
                )
                if provider == MODE_CURSOR or use_runtime:
                    await self._store_runtime(str(merged.get(CONF_RUNTIME_URL) or ""), runtime_token)
                effort = str(merged.get(CONF_EFFORT) or "")
                if provider == MODE_CURSOR:
                    mode = MODE_CURSOR
                elif use_runtime:
                    mode = RUNTIME_MODE[provider]
                else:
                    mode = MODE_API
                data = {
                    CONF_MODE: mode,
                    CONF_API_PROVIDER: provider,
                    CONF_USE_CLAUDE_RUNTIME: use_runtime and provider == API_ANTHROPIC,
                    CONF_USE_CODEX_RUNTIME: use_runtime and provider == API_OPENAI,
                    CONF_CURSOR_API_KEY: cursor_key if provider == MODE_CURSOR else "",
                    CONF_CLAUDE_API_KEY: claude_key if use_runtime and provider == API_ANTHROPIC else "",
                    CONF_CODEX_API_KEY: codex_key if use_runtime and provider == API_OPENAI else "",
                    CONF_API_KEY: "" if provider == MODE_CURSOR or use_runtime else key,
                    CONF_API_BASE: "" if provider == MODE_CURSOR or use_runtime else base,
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
                    if provider_supports_stt(provider) and not use_runtime
                    else False,
                    CONF_STT_MODEL: str(user_input.get(CONF_STT_MODEL) or "").strip()
                    if provider_supports_stt(provider) and not use_runtime
                    else "",
                    CONF_ASSIST_TTS: bool(
                        user_input.get(
                            CONF_ASSIST_TTS,
                            assist_tts_enabled(current, provider, new=not self._editing),
                        )
                    )
                    if provider_supports_tts(provider) and not use_runtime
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
                if provider == API_ANTHROPIC and not use_runtime:
                    data[CONF_CACHE_1H] = caches_an_hour(merged)
                if provider != MODE_CURSOR and not use_runtime and CONF_PROMPT_CACHE in current:
                    data[CONF_PROMPT_CACHE] = bool(current.get(CONF_PROMPT_CACHE))
                if use_runtime:
                    # Claude SDK / Codex: show the Runtime's sign-in state (and the sign-in button) before saving.
                    self._current = merged
                    self._pending = (provider, data)
                    self._engine = RUNTIME_ENGINE[provider]
                    if self._engine == ENGINE_CODEX:
                        return await self.async_step_codex_account()
                    return await self.async_step_claude_account()
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
        if user_input and provider in RUNTIME_SWITCH:
            schema_current[RUNTIME_SWITCH[provider]] = runtime_switch(user_input, provider)
        if step == "ollama":
            from .ollama_info import async_ollama_server, ollama_form_note

            url = str(schema_current.get(CONF_API_BASE) or default_api_base(API_OLLAMA))
            placeholders["ollama_note"] = ollama_form_note(
                await async_ollama_server(self.hass, url), example, self.hass.config.language
            )
        if step == "cursor" or (step == "cloud" and provider in RUNTIME_SWITCH and uses_runtime(schema_current, provider)):
            entry = self._get_entry()
            saved = str({**entry.data, **entry.options}.get(CONF_RUNTIME_URL) or "")
            rt = _runtime_section(user_input, provider) if step == "cloud" else (user_input or {})
            typed = str(rt.get(CONF_RUNTIME_URL) or (user_input or {}).get(CONF_RUNTIME_URL) or "")
            if typed:
                shown = typed.strip().rstrip("/")
                live = await async_probe_runtime(self.hass, shown)
                auto = False
            else:
                shown, live, auto = await async_runtime_form_url(self.hass, saved)
            schema_current[CONF_RUNTIME_URL] = shown
            placeholders.update(runtime_form_placeholders(live=live, auto=auto, language=self.hass.config.language))
            if step == "cursor":
                from .local_text import cursor_key_note

                health = await async_runtime_health(self.hass, shown) if live and shown else None
                placeholders["cursor_key_note"] = cursor_key_note(
                    bool(health and health.get("cursor")), self.hass.config.language
                )
            if step == "cloud" and provider == API_ANTHROPIC:
                placeholders["api_key_url"] = api_key_url(MODE_CLAUDE)
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

    # ---- Claude SDK: sign in on the Runtime -------------------------------------------------------

    async def _runtime_target(self) -> tuple[str, str]:
        """Runtime URL and token as saved by the form (the same ones the chat uses)."""
        entry = self._get_entry()
        blob = {**entry.data, **entry.options}
        base = await async_resolve_runtime_url(self.hass, str(blob.get(CONF_RUNTIME_URL) or ""))
        self._target = (base, str(blob.get(CONF_RUNTIME_TOKEN) or ""))
        return self._target

    def _own_key(self) -> bool:
        return bool(self._pending and str(self._pending[1].get(CONF_CLAUDE_API_KEY) or "").strip())

    async def async_step_claude_account(self, user_input=None):
        """Menu: the Runtime's Claude credential, with Sign in / Sign out / Save / Back."""
        del user_input
        from .local_text import claude_signin_text
        from .runtime_auth import RuntimeAuthError, async_auth_status

        if self._pending is None:
            return await self.async_step_provider()
        base, token = await self._runtime_target()
        problem = ""
        try:
            self._auth = await async_auth_status(self.hass, base, token, ENGINE_CLAUDE)
        except RuntimeAuthError as exc:
            self._auth = None
            problem = exc.key
        status = self._auth
        own_key = self._own_key()
        options: list[str] = []
        if own_key:
            options.append("claude_save")
        elif status and status.get("ready"):
            # The Runtime already has Claude access (its options, environment or an earlier sign-in).
            options.append("claude_use_runtime")
        if status and (status.get("login") or {}).get("supported"):
            options.append("claude_login")
        if status and status.get("signed_in"):
            options.append("claude_logout")
        options.append("claude_back")
        return self.async_show_menu(
            step_id="claude_account",
            menu_options=options,
            description_placeholders={
                "status": claude_signin_text(status, own_key, self.hass.config.language, problem),
            },
        )

    async def async_step_claude_save(self, user_input=None):
        del user_input
        if self._pending is None:
            return await self.async_step_provider()
        return self._finish(*self._pending)

    async def async_step_claude_use_runtime(self, user_input=None):
        return await self.async_step_claude_save(user_input)

    async def async_step_claude_back(self, user_input=None):
        del user_input
        await self._cancel_login()
        self._pending = None
        return await self._async_step_fields("cloud", None)

    async def async_step_claude_logout(self, user_input=None):
        del user_input
        from .runtime_auth import RuntimeAuthError, async_logout

        base, token = await self._runtime_target()
        try:
            await async_logout(self.hass, base, token, ENGINE_CLAUDE)
        except RuntimeAuthError as exc:
            self._login_error = exc.key
            return await self.async_step_claude_login_error()
        return await self.async_step_claude_account()

    async def _cancel_login(self) -> None:
        from .runtime_auth import async_login_cancel

        login, self._login = self._login, None
        if login and login.get("id"):
            base, token = self._target
            await async_login_cancel(self.hass, base, token, self._engine, str(login["id"]))

    async def _fresh_login(self) -> dict[str, Any] | None:
        """The sign-in that still waits for its code, or a new one. None when it could not start."""
        from .runtime_auth import RuntimeAuthError, async_login_start, async_login_state

        base, token = await self._runtime_target()
        if self._login is not None:
            try:
                state = await async_login_state(self.hass, base, token, ENGINE_CLAUDE, str(self._login.get("id")))
            except RuntimeAuthError:
                state = {}
            if state.get("status") == "awaiting_code":
                return self._login
            self._login = None
        try:
            self._login = await async_login_start(self.hass, base, token, ENGINE_CLAUDE)
        except RuntimeAuthError as exc:
            self._login_error = exc.key
            return None
        return self._login

    async def async_step_claude_login(self, user_input=None):
        """Show the sign-in link; the code Anthropic shows afterwards is pasted back here."""
        from .runtime_auth import RuntimeAuthError, async_login_code

        if self._pending is None:
            return await self.async_step_provider()
        errors: dict[str, str] = {}
        if user_input is not None and self._login is not None:
            base, token = self._target
            code = str(user_input.get(CONF_LOGIN_CODE) or "").strip()
            try:
                body = await async_login_code(self.hass, base, token, ENGINE_CLAUDE, str(self._login.get("id")), code)
            except RuntimeAuthError as exc:
                if exc.key in _RETYPE:
                    errors[CONF_LOGIN_CODE] = exc.key
                else:
                    # That sign-in is over on the Runtime; the form comes back with a new link.
                    errors["base"] = exc.key
                    self._login = None
            else:
                self._login = None
                self._auth = body.get("auth") if isinstance(body.get("auth"), dict) else None
                provider, data = self._pending
                # The sign-in is meant to be used: an older token on this agent would win over it.
                self._pending = (provider, {**data, CONF_CLAUDE_API_KEY: ""})
                return await self.async_step_claude_signed_in()
        login = self._login if errors.get(CONF_LOGIN_CODE) else await self._fresh_login()
        if login is None:
            return await self.async_step_claude_login_error()
        return self.async_show_form(
            step_id="claude_login",
            data_schema=vol.Schema({vol.Required(CONF_LOGIN_CODE): TextSelector(TextSelectorConfig())}),
            errors=errors,
            description_placeholders={"url": str(login.get("url") or "")},
        )

    async def async_step_claude_signed_in(self, user_input=None):
        """Signed in: say so (no secrets), then save the agent."""
        from .local_text import claude_signin_text

        if self._pending is None:
            return await self.async_step_provider()
        if user_input is not None:
            return self._finish(*self._pending)
        return self.async_show_form(
            step_id="claude_signed_in",
            data_schema=vol.Schema({}),
            description_placeholders={
                "status": claude_signin_text(self._auth, self._own_key(), self.hass.config.language),
            },
        )

    async def async_step_claude_login_error(self, user_input=None):
        """The Runtime could not start (or end) the sign-in; submit goes back to the menu."""
        if user_input is not None:
            self._login_error = ""
            return await self.async_step_claude_account()
        from .runtime_auth import KNOWN_ERRORS

        key = self._login_error if self._login_error in KNOWN_ERRORS else "login_failed"
        return self.async_show_form(step_id="claude_login_error", data_schema=vol.Schema({}), errors={"base": key})

    # ---- Codex: sign in with ChatGPT on the Runtime (device code) ---------------------------------

    def _own_codex_key(self) -> bool:
        return bool(self._pending and str(self._pending[1].get(CONF_CODEX_API_KEY) or "").strip())

    async def async_step_codex_account(self, user_input=None):
        """Menu: the Runtime's Codex credential, with Sign in / Sign out / Save / Back."""
        del user_input
        from .local_text import codex_signin_text
        from .runtime_auth import RuntimeAuthError, async_auth_status

        if self._pending is None:
            return await self.async_step_provider()
        self._engine = ENGINE_CODEX
        base, token = await self._runtime_target()
        problem = ""
        try:
            self._auth = await async_auth_status(self.hass, base, token, ENGINE_CODEX)
        except RuntimeAuthError as exc:
            self._auth = None
            problem = exc.key
        status = self._auth
        own_key = self._own_codex_key()
        options: list[str] = []
        if own_key:
            options.append("codex_save")
        elif status and status.get("ready"):
            options.append("codex_use_runtime")
        if status and (status.get("login") or {}).get("supported"):
            options.append("codex_login")
        if status and status.get("signed_in"):
            options.append("codex_logout")
        options.append("codex_back")
        return self.async_show_menu(
            step_id="codex_account",
            menu_options=options,
            description_placeholders={"status": codex_signin_text(status, own_key, self.hass.config.language, problem)},
        )

    async def async_step_codex_save(self, user_input=None):
        return await self.async_step_claude_save(user_input)

    async def async_step_codex_use_runtime(self, user_input=None):
        return await self.async_step_claude_save(user_input)

    async def async_step_codex_back(self, user_input=None):
        return await self.async_step_claude_back(user_input)

    async def async_step_codex_logout(self, user_input=None):
        del user_input
        from .runtime_auth import RuntimeAuthError, async_logout

        base, token = await self._runtime_target()
        try:
            await async_logout(self.hass, base, token, ENGINE_CODEX)
        except RuntimeAuthError as exc:
            self._login_error = exc.key
            return await self.async_step_codex_login_error()
        return await self.async_step_codex_account()

    async def async_step_codex_login(self, user_input=None):
        """Show OpenAI's link and one-time code; submit once the code is entered there."""
        from .runtime_auth import RuntimeAuthError, async_login_start, async_login_state

        if self._pending is None:
            return await self.async_step_provider()
        errors: dict[str, str] = {}
        base, token = self._target if user_input is not None else await self._runtime_target()
        if user_input is not None and self._login is not None:
            try:
                state = await async_login_state(
                    self.hass, base, token, ENGINE_CODEX, str(self._login.get("id")), wait=_DEVICE_WAIT
                )
            except RuntimeAuthError as exc:
                state = {"status": "failed", "error": exc.key}
            status = str(state.get("status") or "")
            if status == "succeeded":
                self._login = None
                self._auth = state.get("auth") if isinstance(state.get("auth"), dict) else None
                provider, data = self._pending
                # The sign-in is meant to be used: an API key on this agent would win over it.
                self._pending = (provider, {**data, CONF_CODEX_API_KEY: ""})
                return await self.async_step_codex_signed_in()
            if status in {"starting", "awaiting_code"}:
                errors["base"] = "not_signed_in_yet"
            else:
                self._login = None
                self._login_error = str(state.get("error") or ("expired" if status == "expired" else "login_failed"))
                return await self.async_step_codex_login_error()
        if self._login is None:
            try:
                self._login = await async_login_start(self.hass, base, token, ENGINE_CODEX)
            except RuntimeAuthError as exc:
                self._login_error = exc.key
                return await self.async_step_codex_login_error()
        return self.async_show_form(
            step_id="codex_login",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "url": str(self._login.get("url") or ""),
                "code": str(self._login.get("user_code") or ""),
            },
        )

    async def async_step_codex_signed_in(self, user_input=None):
        from .local_text import codex_signin_text

        if self._pending is None:
            return await self.async_step_provider()
        if user_input is not None:
            return self._finish(*self._pending)
        return self.async_show_form(
            step_id="codex_signed_in",
            data_schema=vol.Schema({}),
            description_placeholders={
                "status": codex_signin_text(self._auth, self._own_codex_key(), self.hass.config.language),
            },
        )

    async def async_step_codex_login_error(self, user_input=None):
        if user_input is not None:
            self._login_error = ""
            return await self.async_step_codex_account()
        from .runtime_auth import KNOWN_ERRORS

        key = self._login_error if self._login_error in KNOWN_ERRORS else "login_failed"
        return self.async_show_form(step_id="codex_login_error", data_schema=vol.Schema({}), errors={"base": key})

    @callback
    def async_remove(self) -> None:
        """Dialog closed: stop a sign-in that still waits for its code."""
        if self._login and self._login.get("id") and self.hass is not None:
            self.hass.async_create_task(self._cancel_login())

    def _finish(self, provider: str, data: dict[str, Any]):
        entry = self._get_entry()
        titles = {agent.title for agent in entry_agents(entry)}
        if self._editing:
            sub = self._get_reconfigure_subentry()
            titles.discard(sub.title)
            same = str(sub.data.get(CONF_API_PROVIDER) or "") == provider
            title = sub.title if same else _title(provider, titles, str(data.get(CONF_MODE) or ""))
            data[CONF_AGENT_ID] = str(sub.data.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)
            return self.async_update_and_abort(entry, sub, title=title, data=data, unique_id=data[CONF_AGENT_ID])
        data[CONF_AGENT_ID] = ulid()
        return self.async_create_entry(title=_title(provider, titles, str(data.get(CONF_MODE) or "")), data=data, unique_id=data[CONF_AGENT_ID])
