"""Extra MCP servers as rows under the AI Workspace service."""

from __future__ import annotations

from types import MappingProxyType

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_MCP_KIND,
    MCP_CONNECTION_TITLES,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_HA_MCP,
    SUBENTRY_MCP,
    mcp_connection_menu,
)
from .mcp_config import server_slug
from .mcp_resolve import async_detect_mcp_kinds, async_resolve_mcp_url, default_mcp_url, infer_mcp_kind

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TOKEN = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class McpConnectionFlow(config_entries.ConfigSubentryFlow):
    """Add or edit one extra MCP server on the AI Workspace service."""

    def __init__(self) -> None:
        self._editing = False
        self._kind = MCP_CUSTOM

    def _host(self):
        """Connections always live on the hub, even if the header picker chose agents."""
        from .agents import hub_entry, is_agents

        entry = self._get_entry()
        if is_agents(entry):
            return hub_entry(self.hass) or entry
        return entry

    def _saved(self) -> tuple[object, dict]:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        current = entry.subentries[subentry.subentry_id]
        return current, dict(current.data)

    def _used_kinds(self, host, current_id: str | None = None) -> set[str]:
        used: set[str] = set()
        for sub in host.subentries.values():
            if getattr(sub, "subentry_type", "") != SUBENTRY_MCP:
                continue
            if current_id and sub.subentry_id == current_id:
                continue
            url = str(sub.data.get("url") or "").strip()
            if not url:
                continue
            kind = infer_mcp_kind(url)
            if kind != MCP_CUSTOM:
                used.add(kind)
        return used

    def _taken(self, host, slug: str, current_id: str | None) -> bool:
        for sub in host.subentries.values():
            if getattr(sub, "subentry_type", "") != SUBENTRY_MCP:
                continue
            if current_id and sub.subentry_id == current_id:
                continue
            if sub.unique_id == slug or str(sub.data.get("name") or "") == slug:
                return True
        return False

    def _schema(self, current: dict) -> vol.Schema:
        kind = self._kind or MCP_CUSTOM
        name = str(current.get("name") or "")
        if not name and kind != MCP_CUSTOM:
            name = MCP_CONNECTION_TITLES.get(kind, "")
        fields: dict = {
            vol.Required("name", default=name): cv.string,
            vol.Required("url", default=str(current.get("url") or "")): _URL,
        }
        if kind in {MCP_CUSTOM, MCP_COOLVER} or str(current.get("token") or "").strip():
            fields[vol.Optional("token", default="")] = _TOKEN
        return vol.Schema(fields)

    async def _defaults(self) -> dict:
        if self._editing:
            current, data = self._saved()
            return {
                "name": current.title,
                "url": data.get("url") or "",
            }
        kind = self._kind or MCP_CUSTOM
        url = ""
        if kind != MCP_CUSTOM:
            url = await async_resolve_mcp_url(self.hass, kind, "", "")
            url = url or default_mcp_url(self.hass, kind)
        return {
            "name": MCP_CONNECTION_TITLES.get(kind, ""),
            "url": url,
        }

    async def async_step_user(self, user_input=None):
        self._editing = False
        host = self._host()
        detected = await async_detect_mcp_kinds(self.hass)
        options = mcp_connection_menu(detected, self._used_kinds(host))
        if options == [MCP_CUSTOM]:
            self._kind = MCP_CUSTOM
            return await self.async_step_connection(user_input)
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_ha(self, user_input=None):
        self._kind = MCP_HA
        return await self.async_step_connection(user_input)

    async def async_step_ha_mcp(self, user_input=None):
        self._kind = MCP_HA_MCP
        return await self.async_step_connection(user_input)

    async def async_step_coolver(self, user_input=None):
        self._kind = MCP_COOLVER
        return await self.async_step_connection(user_input)

    async def async_step_custom(self, user_input=None):
        self._kind = MCP_CUSTOM
        return await self.async_step_connection(user_input)

    async def async_step_reconfigure(self, user_input=None):
        self._editing = True
        _current, data = self._saved()
        self._kind = infer_mcp_kind(str(data.get("url") or ""))
        return await self.async_step_connection(user_input)

    async def async_step_connection(self, user_input=None):
        errors: dict[str, str] = {}
        current_id = None
        previous_token = ""
        host = self._host()
        if self._editing:
            current, data = self._saved()
            current_id = current.subentry_id
            previous_token = str(data.get("token") or "")
            host = self._get_entry()
        if user_input is not None:
            name = str(user_input.get("name") or "").strip()
            url = str(user_input.get("url") or "").strip()
            token = str(user_input.get("token") or "").strip()
            if self._kind != MCP_CUSTOM and not url:
                url = await async_resolve_mcp_url(self.hass, self._kind, "", token)
                url = url or default_mcp_url(self.hass, self._kind)
            if not url.startswith(("http://", "https://")):
                errors["url"] = "required"
            if self._kind == MCP_COOLVER and not token and not previous_token:
                errors["token"] = "required"
            slug = server_slug(name, url)
            if not name or not slug:
                errors["name"] = "required"
            elif self._taken(host, slug, current_id):
                errors["name"] = "already_configured"
            if not errors:
                if self._editing and not token:
                    token = previous_token
                payload = {"name": slug, "url": url, "token": token, CONF_MCP_KIND: self._kind}
                if self._editing:
                    current, data = self._saved()
                    if data.get("primary"):
                        payload["primary"] = True
                    return self.async_update_and_abort(
                        self._get_entry(),
                        current,
                        title=name,
                        unique_id=slug,
                        data=payload,
                    )
                if host.entry_id != self._get_entry().entry_id:
                    self.hass.config_entries.async_add_subentry(
                        host,
                        ConfigSubentry(
                            data=MappingProxyType(payload),
                            subentry_type=SUBENTRY_MCP,
                            title=name,
                            unique_id=slug,
                        ),
                    )
                    self.hass.async_create_task(self.hass.config_entries.async_reload(host.entry_id))
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(title=name, data=payload, unique_id=slug)
        defaults = user_input or await self._defaults()
        return self.async_show_form(
            step_id="connection",
            data_schema=self._schema(defaults),
            errors=errors,
        )
