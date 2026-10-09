"""Add and edit one agent row on the AI Workspace entry."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig, TextSelectorType

from .agents import borrow_by_id, borrowed_setups

from .const import (
    API_AZURE,
    API_COMPATIBLE,
    API_OLLAMA,
    API_PROVIDERS,
    API_SHORT_LABELS,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_API_PROVIDER,
    CONF_AZURE_API_VERSION,
    CONF_BORROW,
    CONF_CURSOR_API_KEY,
    CONF_AGENT_ID,
    CONF_EFFORT,
    CONF_HUB_ID,
    CONF_MODE,
    CONF_ROLE,
    CONF_MODEL,
    DEFAULT_AZURE_API_VERSION,
    EFFORTS,
    MODE_API,
    MODE_CURSOR,
    ROLE_PROVIDER,
    default_api_base,
    default_api_model,
)
from .discovery import async_probe_runtime, async_resolve_runtime_url, hassio_runtime_url

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
        vol.Optional(CONF_EFFORT, default=str(current.get(CONF_EFFORT) or "")): SelectSelector(
            SelectSelectorConfig(options=list(EFFORTS), mode="dropdown", translation_key="effort")
        ),
    }


def _fields_schema(step: str, current: dict, borrows: list[dict[str, str]]) -> vol.Schema:
    model = str(current.get(CONF_MODEL) or "")
    fields: dict = {}
    if step == "cursor":
        fields[vol.Optional(CONF_CURSOR_API_KEY, default="")] = _PASSWORD
        fields[vol.Optional(CONF_MODEL, default=model)] = str
    elif step == "ollama":
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or default_api_base(API_OLLAMA)))] = str
        fields[vol.Optional(CONF_MODEL, default=model)] = str
    elif step == "azure":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields[vol.Required(CONF_MODEL, default=model)] = str
        fields[vol.Optional(CONF_AZURE_API_VERSION, default=str(current.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION))] = str
    elif step == "compatible":
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Required(CONF_API_BASE, default=str(current.get(CONF_API_BASE) or ""))] = str
        fields[vol.Optional(CONF_MODEL, default=model)] = str
    else:
        if borrows:
            options = [{"value": "", "label": "Enter it here"}]
            options.extend({"value": item["id"], "label": item["label"]} for item in borrows)
            fields[vol.Optional(CONF_BORROW, default="")] = SelectSelector(
                SelectSelectorConfig(options=options, mode="dropdown")
            )
        fields[vol.Optional(CONF_API_KEY, default="")] = _PASSWORD
        fields[vol.Optional(CONF_MODEL, default=model)] = str
    fields.update(_effort_field(current))
    return vol.Schema(fields)


def _title(provider: str, used: set[str]) -> str:
    base = "Cursor" if provider == MODE_CURSOR else API_SHORT_LABELS.get(provider, "Agent")
    if base not in used:
        return base
    number = 2
    while f"{base} {number}" in used:
        number += 1
    return f"{base} {number}"


def _unique(provider: str, used: set[str]) -> str:
    if provider not in used:
        return provider
    number = 2
    while f"{provider}-{number}" in used:
        number += 1
    return f"{provider}-{number}"


def _detail_step(provider: str) -> str:
    return _DETAIL.get(provider, "cloud")


def _hub_entry(flow):
    from .agents import hub_entry, is_provider

    hub_id = str(getattr(flow, "_hub_id", "") or "")
    if hub_id:
        get = getattr(getattr(flow.hass, "config_entries", None), "async_get_entry", None)
        if callable(get):
            found = get(hub_id)
            if found is not None:
                return found
    current = getattr(flow, "config_entry", None)
    if current is not None and not is_provider(current):
        return current
    return hub_entry(flow.hass)


def _hub_cursor_key(flow) -> str:
    hub = _hub_entry(flow)
    if hub is None:
        return ""
    return str({**hub.data, **hub.options}.get(CONF_CURSOR_API_KEY) or "").strip()


def _provider_names(flow) -> tuple[set[str], set[str]]:
    from .agents import agents_entry, entry_agents, is_agents, provider_entries

    titles: set[str] = set()
    uniques: set[str] = set()
    for entry in provider_entries(flow.hass):
        titles.add(entry.title)
        if entry.unique_id:
            uniques.add(entry.unique_id)
    parent = None
    getter = getattr(flow, "_get_entry", None)
    if callable(getter):
        try:
            parent = getter()
        except Exception:
            parent = None
    if parent is None or not is_agents(parent):
        parent = agents_entry(flow.hass)
    if parent is not None:
        for agent in entry_agents(parent):
            titles.add(agent.title)
            uniques.add(agent.id)
    return titles, uniques


class ProviderSteps:
    """Provider picker and fields, shared by the config flow and the options flow."""

    async def async_step_provider(self, user_input: dict[str, Any] | None = None):
        current = getattr(self, "_current", {})
        if user_input is not None:
            provider = str(user_input.get(CONF_API_PROVIDER) or MODE_CURSOR)
            if provider not in _agent_choices():
                provider = MODE_CURSOR
            self._provider = provider
            self._current = {**current, CONF_API_PROVIDER: provider}
            return await getattr(self, f"async_step_provider_{_detail_step(provider)}")()
        return self.async_show_form(step_id="provider", data_schema=_provider_schema(current))

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

    async def _async_step_fields(self, step: str, user_input: dict[str, Any] | None):
        current = getattr(self, "_current", {})
        provider = str(getattr(self, "_provider", "") or current.get(CONF_API_PROVIDER) or MODE_CURSOR)
        borrows = [item for item in borrowed_setups(self.hass) if item.get("provider") == provider]
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**current, **user_input, CONF_API_PROVIDER: provider}
            borrowed = borrow_by_id(self.hass, str(user_input.get(CONF_BORROW) or ""))
            if borrowed and borrowed.get("provider") == provider and not str(merged.get(CONF_API_KEY) or "").strip():
                merged[CONF_API_KEY] = borrowed["api_key"]
                merged[CONF_API_BASE] = borrowed["api_base"]
                if not str(merged.get(CONF_MODEL) or "").strip():
                    merged[CONF_MODEL] = borrowed["model"]
                merged[CONF_AZURE_API_VERSION] = borrowed.get("azure_api_version") or DEFAULT_AZURE_API_VERSION
            cursor_key = str(merged.get(CONF_CURSOR_API_KEY) or current.get(CONF_CURSOR_API_KEY) or "").strip()
            if provider == MODE_CURSOR and not cursor_key:
                cursor_key = _hub_cursor_key(self)
            key = str(merged.get(CONF_API_KEY) or current.get(CONF_API_KEY) or "").strip()
            base = str(merged.get(CONF_API_BASE) or "").strip() or default_api_base(provider)
            model = str(merged.get(CONF_MODEL) or "").strip() or default_api_model(provider)
            if provider == MODE_CURSOR:
                if not cursor_key:
                    errors[CONF_CURSOR_API_KEY] = "required"
                discovered = hassio_runtime_url(self.hass) or ""
                parent = _hub_entry(self)
                merged_hub = {**parent.data, **parent.options} if parent is not None else {}
                configured = str(merged_hub.get("runtime_url") or discovered).strip()
                runtime = await async_resolve_runtime_url(self.hass, configured)
                if not runtime or not await async_probe_runtime(self.hass, runtime):
                    errors["base"] = "no_runtime"
            elif provider == API_OLLAMA:
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
            elif provider == API_AZURE:
                if not key:
                    errors[CONF_API_KEY] = "required"
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
                if not str(merged.get(CONF_MODEL) or "").strip():
                    errors[CONF_MODEL] = "required"
            elif provider == API_COMPATIBLE:
                if not key:
                    errors[CONF_API_KEY] = "required"
                if not str(merged.get(CONF_API_BASE) or "").strip():
                    errors[CONF_API_BASE] = "required"
            elif not key:
                errors[CONF_API_KEY] = "required"
            if not errors:
                data = {
                    CONF_MODE: MODE_CURSOR if provider == MODE_CURSOR else MODE_API,
                    CONF_API_PROVIDER: provider,
                    CONF_CURSOR_API_KEY: cursor_key if provider == MODE_CURSOR else "",
                    CONF_API_KEY: "" if provider == MODE_CURSOR else key,
                    CONF_API_BASE: "" if provider == MODE_CURSOR else base,
                    CONF_MODEL: str(merged.get(CONF_MODEL) or "").strip() if provider == MODE_CURSOR else model,
                    CONF_EFFORT: str(merged.get(CONF_EFFORT) or ""),
                    CONF_AZURE_API_VERSION: (
                        str(merged.get(CONF_AZURE_API_VERSION) or DEFAULT_AZURE_API_VERSION)
                        if provider == API_AZURE
                        else ""
                    ),
                    CONF_ROLE: ROLE_PROVIDER,
                    CONF_HUB_ID: str(getattr(self, "_hub_id", "") or ""),
                    CONF_AGENT_ID: str(getattr(self, "_agent_id", "") or ""),
                }
                return await self._finish_provider(provider, data)
            current = merged
        return self.async_show_form(
            step_id=f"provider_{step}",
            data_schema=_fields_schema(step, current, borrows),
            errors=errors,
        )

    async def _finish_provider(self, provider: str, data: dict[str, Any]):
        raise NotImplementedError


class AgentSubentryFlow(ProviderSteps, config_entries.ConfigSubentryFlow):
    """One agent under AI Agents. The form asks only for that provider."""

    def _host(self):
        """Agents always live on the agents entry, even if the header picker chose the hub."""
        from .agents import agents_entry, is_agents

        entry = self._get_entry()
        if is_agents(entry):
            return entry
        return agents_entry(self.hass) or entry

    async def async_step_user(self, user_input=None):
        del user_input
        self._editing = False
        self._current = {}
        self._provider = MODE_CURSOR
        self._agent_id = ""
        parent = self._host()
        self._hub_id = str(parent.data.get("hub_id") or "")
        return await self.async_step_provider()

    async def async_step_reconfigure(self, user_input=None):
        del user_input
        self._editing = True
        sub = self._get_reconfigure_subentry()
        raw = dict(sub.data)
        self._current = raw
        self._provider = str(raw.get(CONF_API_PROVIDER) or MODE_CURSOR)
        self._agent_id = str(raw.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)
        self._hub_id = str(self._get_entry().data.get("hub_id") or "")
        return await self.async_step_provider()

    async def _finish_provider(self, provider: str, data: dict[str, Any]):
        from types import MappingProxyType

        from homeassistant.config_entries import ConfigSubentry
        from homeassistant.util.ulid import ulid

        from .const import SUBENTRY_AGENT

        data.pop(CONF_ROLE, None)
        data.pop(CONF_HUB_ID, None)
        titles, _uniques = _provider_names(self)
        if getattr(self, "_editing", False):
            sub = self._get_reconfigure_subentry()
            titles.discard(sub.title)
            same = str(sub.data.get(CONF_API_PROVIDER) or "") == provider
            title = sub.title if same else _title(provider, titles)
            data[CONF_AGENT_ID] = self._agent_id or str(sub.data.get(CONF_AGENT_ID) or sub.unique_id or sub.subentry_id)
            # Entry has update listeners — reload_and_abort is forbidden; update
            # fires _reload the same way MCP connection edits do.
            return self.async_update_and_abort(
                self._get_entry(),
                sub,
                title=title,
                data=data,
                unique_id=data[CONF_AGENT_ID],
            )
        titles.discard("")
        agent_id = ulid()
        data[CONF_AGENT_ID] = agent_id
        title = _title(provider, titles)
        host = self._host()
        if host.entry_id != self._get_entry().entry_id:
            self.hass.config_entries.async_add_subentry(
                host,
                ConfigSubentry(
                    data=MappingProxyType(data),
                    subentry_type=SUBENTRY_AGENT,
                    title=title,
                    unique_id=agent_id,
                ),
            )
            self.hass.async_create_task(self.hass.config_entries.async_reload(host.entry_id))
            return self.async_abort(reason="reconfigure_successful")
        return self.async_create_entry(title=title, data=data, unique_id=agent_id)


class ProviderOptionsFlow(ProviderSteps, config_entries.OptionsFlow):
    """Edit a provider that has not been folded into AI Agents yet."""

    async def async_step_init(self, user_input=None):
        del user_input
        entry = self.config_entry
        raw = {**entry.data, **entry.options}
        self._hub_id = str(raw.get(CONF_HUB_ID) or "")
        self._current = raw
        self._provider = str(raw.get(CONF_API_PROVIDER) or MODE_CURSOR)
        self._agent_id = str(raw.get(CONF_AGENT_ID) or entry.entry_id)
        return await self.async_step_provider()

    async def _finish_provider(self, provider: str, data: dict[str, Any]):
        entry = self.config_entry
        titles, _uniques = _provider_names(self)
        titles.discard(entry.title)
        title = entry.title
        if str(entry.data.get(CONF_API_PROVIDER) or "") != provider:
            title = _title(provider, titles)
            self.hass.config_entries.async_update_entry(entry, title=title)
        data[CONF_AGENT_ID] = str(data.get(CONF_AGENT_ID) or entry.data.get(CONF_AGENT_ID) or entry.entry_id)
        data[CONF_HUB_ID] = str(data.get(CONF_HUB_ID) or entry.data.get(CONF_HUB_ID) or "")
        return self.async_create_entry(title="", data=data)
