"""Optional local index of entities, areas, automations, and dashboards."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .const import DOMAIN
from .mcp_client import McpError
from .store import Store

_LOGGER = logging.getLogger(__name__)

TOOL_NAME = "search_house_map"
TOOL_DESCRIPTION = (
    "Search a local cache of this Home Assistant for entity ids, areas, automations, "
    "and dashboards by name. Use this before broad MCP listings when you need ids. "
    "It is not live state — call MCP after this for current state or to change anything."
)
HOUSE_MAP_INSTRUCTIONS = (
    "A local tool search_house_map looks up entity ids, areas, automations, and dashboards "
    "from a cached index. For naming questions on a new chat, call search_house_map first, "
    "then MCP for live state or changes. The map is not live state."
)

_REFRESH_SECONDS = 15 * 60


def tool_definition() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words to match against names and ids, such as living room lights.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["any", "entity", "area", "automation", "dashboard"],
                    "description": "Limit to one kind of row. Default any.",
                },
            },
            "required": ["query"],
        },
    }


def collect_rows(hass: HomeAssistant) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    areas = ar.async_get(hass)
    area_names = {area.id: area.name for area in areas.async_list_areas()}
    for area_id, name in area_names.items():
        rows.append(("area", area_id, name or area_id, area_id, "", ""))

    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.disabled_by is not None:
            continue
        name = (entry.name or entry.original_name or entry.entity_id or "").strip()
        area_id = entry.area_id or ""
        if area_id and area_id in area_names:
            label = f"{name} ({area_names[area_id]})"
        else:
            label = name
        kind = "automation" if entry.domain == "automation" else "entity"
        extra = ""
        if kind == "automation":
            state = hass.states.get(entry.entity_id)
            auto_id = ""
            if state is not None:
                auto_id = str(state.attributes.get("id") or "").strip()
            extra = json.dumps({"entity_id": entry.entity_id, "config_id": auto_id}, ensure_ascii=False)
        rows.append((kind, entry.entity_id, label or entry.entity_id, area_id, entry.domain or "", extra))

    for state in hass.states.async_all("automation"):
        entity_id = state.entity_id
        if any(row[1] == entity_id for row in rows):
            continue
        config_id = str(state.attributes.get("id") or "").strip()
        name = str(state.attributes.get("friendly_name") or entity_id).strip()
        rows.append(
            (
                "automation",
                entity_id,
                name,
                "",
                "automation",
                json.dumps({"entity_id": entity_id, "config_id": config_id}, ensure_ascii=False),
            )
        )

    lovelace = hass.data.get("lovelace")
    dashboards = getattr(lovelace, "dashboards", None) if lovelace is not None else None
    if isinstance(dashboards, dict):
        for path, conf in dashboards.items():
            url_path = "lovelace" if path in (None, "") else str(path)
            title = str(getattr(conf, "title", None) or url_path).strip() or url_path
            rows.append(
                (
                    "dashboard",
                    url_path,
                    title,
                    "",
                    "lovelace",
                    json.dumps({"path": f"/{url_path}" if url_path != "lovelace" else "/lovelace"}, ensure_ascii=False),
                )
            )
    return rows


async def refresh_house_map(hass: HomeAssistant, store: Store) -> int:
    rows = collect_rows(hass)
    await hass.async_add_executor_job(store.replace_house_map, rows)
    _LOGGER.debug("house map refreshed rows=%s", len(rows))
    return len(rows)


def search_house_map(store: Store, query: str, kind: str = "any", limit: int = 24) -> list[dict[str, Any]]:
    return store.search_house_map(query, kind=kind, limit=limit)


class HouseMapClient:
    """In-process tool client with the same shape as McpHttpClient for the API loop."""

    def __init__(self, hass: HomeAssistant, store: Store) -> None:
        self.hass = hass
        self.store = store

    async def initialize(self) -> dict[str, Any]:
        return {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return [tool_definition()]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name != TOOL_NAME:
            raise McpError(f"Unknown house map tool: {name}")
        args = arguments or {}
        query = str(args.get("query") or "").strip()
        kind = str(args.get("kind") or "any").strip() or "any"
        if not query:
            return {"matches": [], "note": "Provide a query string."}
        matches = await self.hass.async_add_executor_job(search_house_map, self.store, query, kind)
        return {
            "matches": matches,
            "note": "Ids and names only. Use MCP for live state or to change anything.",
        }


def house_map_mcp_url(hass: HomeAssistant) -> str:
    base = ""
    try:
        from homeassistant.helpers.network import get_url

        base = get_url(hass, prefer_external=False, allow_cloud=False)
    except Exception:
        base = ""
    if not base:
        base = str(getattr(hass.config, "internal_url", None) or "").strip()
    if not base:
        base = "http://127.0.0.1:8123"
    return f"{base.rstrip('/')}/api/ai_workspace/house_map/mcp"


def mcp_server_config(hass: HomeAssistant, token: str = "") -> dict[str, Any]:
    server: dict[str, Any] = {"type": "http", "url": house_map_mcp_url(hass)}
    secret = str(token or "").strip()
    if secret:
        server["headers"] = {"Authorization": f"Bearer {secret}"}
    return server


async def async_setup_house_map(hass: HomeAssistant, store: Store, enabled: bool) -> None:
    bucket = hass.data.setdefault(DOMAIN, {})
    for key in ("house_map_unsub", "house_map_timer"):
        unsub = bucket.pop(key, None)
        if callable(unsub):
            unsub()
    if not enabled:
        await hass.async_add_executor_job(store.replace_house_map, [])
        return

    async def _refresh(_now=None) -> None:
        try:
            await refresh_house_map(hass, store)
        except Exception:
            _LOGGER.exception("house map refresh failed")

    await _refresh()

    @callback
    def _schedule(_event: Event | None = None) -> None:
        hass.async_create_task(_refresh())

    unsubs = [
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _schedule),
        hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _schedule),
    ]
    timer = async_track_time_interval(hass, _refresh, timedelta(seconds=_REFRESH_SECONDS))
    unsubs.append(timer)

    def _cancel() -> None:
        for item in unsubs:
            item()

    bucket["house_map_unsub"] = _cancel
