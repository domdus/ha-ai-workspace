"""Extra MCP servers as rows under the AI Workspace service."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import SUBENTRY_MCP
from .mcp_config import server_slug

_URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TOKEN = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _schema(current: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=str(current.get("name") or "")): cv.string,
            vol.Required("url", default=str(current.get("url") or "")): _URL,
            vol.Optional("token", default=""): _TOKEN,
        }
    )


class McpConnectionFlow(config_entries.ConfigSubentryFlow):
    """Add or edit one extra MCP server on the AI Workspace service."""

    def __init__(self) -> None:
        self._editing = False

    def _saved(self) -> tuple[object, dict]:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        current = entry.subentries[subentry.subentry_id]
        return current, dict(current.data)

    def _defaults(self) -> dict:
        if not self._editing:
            return {}
        current, data = self._saved()
        return {"name": current.title, "url": data.get("url") or ""}

    def _taken(self, slug: str, current_id: str | None) -> bool:
        entry = self._get_entry()
        for sub in entry.subentries.values():
            if getattr(sub, "subentry_type", "") != SUBENTRY_MCP:
                continue
            if current_id and sub.subentry_id == current_id:
                continue
            if sub.unique_id == slug or str(sub.data.get("name") or "") == slug:
                return True
        return False

    async def async_step_user(self, user_input=None):
        self._editing = False
        return await self.async_step_connection(user_input)

    async def async_step_reconfigure(self, user_input=None):
        self._editing = True
        return await self.async_step_connection(user_input)

    async def async_step_connection(self, user_input=None):
        errors: dict[str, str] = {}
        current_id = None
        previous_token = ""
        if self._editing:
            current, data = self._saved()
            current_id = current.subentry_id
            previous_token = str(data.get("token") or "")
        if user_input is not None:
            name = str(user_input.get("name") or "").strip()
            url = str(user_input.get("url") or "").strip()
            token = str(user_input.get("token") or "").strip()
            if not url.startswith(("http://", "https://")):
                errors["url"] = "required"
            slug = server_slug(name, url)
            if not name or not slug:
                errors["name"] = "required"
            elif self._taken(slug, current_id):
                errors["name"] = "already_configured"
            if not errors:
                if self._editing and not token:
                    token = previous_token
                payload = {"name": slug, "url": url, "token": token}
                if self._editing:
                    current, _data = self._saved()
                    return self.async_update_and_abort(
                        self._get_entry(),
                        current,
                        title=name,
                        unique_id=slug,
                        data=payload,
                    )
                return self.async_create_entry(title=name, data=payload, unique_id=slug)
        return self.async_show_form(
            step_id="connection",
            data_schema=_schema(user_input or self._defaults()),
            errors=errors,
        )
