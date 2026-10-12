"""Add and edit one agent row on the AI Workspace entry."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util.ulid import ulid

from .agents import borrow_by_id, borrowed_setups, entry_agents
from .const import (
    API_AZURE,
    API_COMPATIBLE,
    API_OLLAMA,
    API_PROVIDERS,
    API_SHORT_LABELS,
    CONF_AGENT_ID,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_ASSIST,
    CONF_AZURE_API_VERSION,
    CONF_BORROW,
    CONF_CURSOR_API_KEY,
    CONF_EFFORT,
    CONF_LOW_TOKEN,
    CONF_MODE,
    CONF_MODEL,
    CONF_RUNTIME_URL,
    DEFAULT_AZURE_API_VERSION,
    EFFORT_DEFAULT,
    EFFORTS,
    MODE_API,
    MODE_CURSOR,
    assist_enabled,
    default_api_base,
    submitted_model,
)
from .discovery import async_resolve_runtime_url, async_runtime_health

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_DETAIL = {
    MODE_CURSOR: "cursor",
    API_OLLAMA: "ollama",
    API_AZURE: "azure",
    API_COMPATIBLE: "compatible",
}


def _agent_choices() -> dict[str, str]:
    return {MODE_CURSOR: "Cursor", **API_PROVIDERS}


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


def _optional_model(current: dict) -> dict:
    shown = str(current.get(CONF_MODEL) or "")
    return {vol.Optional(CONF_MODEL, default="", description={"suggested_value": shown}): str}


def _fields_schema(step: str, current: dict, borrows: list[dict[str, str]], *, new: bool = False) -> vol.Schema:
    model = str(current.get(CONF_MODEL) or "")
    fields: dict = {}
    if step == "cursor":
        fields[vol.Optional(CONF_CURSOR_API_KEY, default="")] = _PASSWORD
        fields.update(_optional_model(current))
    elif step == "ollama":
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or default_api_base(API_OLLAMA)))] = str
        fields.update(_optional_model(current))
    elif step == "azure":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields[vol.Required(CONF_MODEL, default=model)] = str
        fields[vol.Optional(CONF_AZURE_API_VERSION, default=str(current.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION))] = str
    elif step == "compatible":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields.update(_optional_model(current))
    else:
        if borrows:
            options = [{"value": "", "label": "Enter it here"}]
            options.extend({"value": item["id"], "label": item["label"]} for item in borrows)
            fields[vol.Optional(CONF_BORROW, default="")] = SelectSelector(
                SelectSelectorConfig(options=options, mode="dropdown")
            )
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields.update(_optional_model(current))
    fields.update(_effort_field(current))
    if step != "cursor":
        fields[vol.Optional(CONF_LOW_TOKEN, default=bool(current.get(CONF_LOW_TOKEN, False)))] = cv.boolean
    fields[vol.Optional(CONF_ASSIST, default=assist_enabled(current, new=new))] = cv.boolean
    return vol.Schema(fields)


def _title(provider: str, used: set[str]) -> str:
    base = "Cursor" if provider == MODE_CURSOR else API_SHORT_LABELS.get(provider, "Agent")
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

    async def async_step_provider_cloud(self, user_input=None):
        return await self._async_step_fields("cloud", user_input)

    async def async_step_provider_ollama(self, user_input=None):
        return await self._async_step_fields("ollama", user_input)

    async def async_step_provider_azure(self, user_input=None):
        return await self._async_step_fields("azure", user_input)

    async def async_step_provider_compatible(self, user_input=None):
        return await self._async_step_fields("compatible", user_input)

    async def _cursor_errors(self, cursor_key: str) -> dict[str, str]:
        entry = self._get_entry()
        configured = str({**entry.data, **entry.options}.get(CONF_RUNTIME_URL) or "").strip()
        runtime = await async_resolve_runtime_url(self.hass, configured)
        health = await async_runtime_health(self.hass, runtime) if runtime else None
        if health is None:
            return {"base": "no_runtime"}
        if not cursor_key and not health.get("cursor"):
            return {CONF_CURSOR_API_KEY: "required"}
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
            key = str(merged.get(CONF_API_KEY) or current.get(CONF_API_KEY) or "").strip()
            base = str(merged.get(CONF_API_BASE) or "").strip() or default_api_base(provider)
            version = str(merged.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION)
            model = submitted_model(user_input)
            if borrowed and borrowed.get("provider") == provider and not model:
                model = str(borrowed.get("model") or "").strip()
            if provider == MODE_CURSOR:
                errors = await self._cursor_errors(cursor_key)
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
            if not errors and provider != MODE_CURSOR:
                errors = await self._key_errors(provider, key, base, version)
            if not errors:
                effort = str(merged.get(CONF_EFFORT) or "")
                data = {
                    CONF_MODE: MODE_CURSOR if provider == MODE_CURSOR else MODE_API,
                    CONF_API_PROVIDER: provider,
                    CONF_CURSOR_API_KEY: cursor_key if provider == MODE_CURSOR else "",
                    CONF_API_KEY: "" if provider == MODE_CURSOR else key,
                    CONF_API_BASE: "" if provider == MODE_CURSOR else base,
                    CONF_MODEL: model,
                    CONF_EFFORT: "" if effort == EFFORT_DEFAULT else effort,
                    CONF_LOW_TOKEN: False if provider == MODE_CURSOR else bool(user_input.get(CONF_LOW_TOKEN, False)),
                    CONF_ASSIST: bool(user_input.get(CONF_ASSIST, assist_enabled(current, new=not self._editing))),
                    CONF_AZURE_API_VERSION: version if provider == API_AZURE else "",
                }
                return self._finish(provider, data)
            self._current = merged
        example = "https://YOUR-RESOURCE.openai.azure.com" if step == "azure" else default_api_base(API_OLLAMA)
        return self.async_show_form(
            step_id=f"provider_{step}",
            data_schema=_fields_schema(step, self._current, borrows, new=not self._editing),
            errors=errors,
            description_placeholders={"example_url": example},
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
