"""Optional local config catalog of entities, areas, automations, and dashboards."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .catalog_index import (
    ACTION_KEYS,
    acts_on as acts_on_ids,
    apply_catalog_detail,
    depends_on as depends_on_ids,
    extra_payload,
    harvest_device_ids,
    related_config_ids,
    summarize_triggers,
    uniq,
)
from .const import DOMAIN
from .mcp_client import McpError
from .store import Store

_LOGGER = logging.getLogger(__name__)

TOOL_NAME = "search_catalog"
TOOL_ALIASES = frozenset({"search_house_map"})
CATALOG_SERVER = "catalog"
TOOL_DESCRIPTION = (
    "Find static wiring for a named item: ids, automation triggers, acts_on, depends_on, related_config_ids. "
    "Never use this for list all automations, counts, or on/off — use Home Assistant MCP with a domain listing instead. "
    "Never chain search_catalog with per-item ha_config_get_* calls just to build a list with edit links. "
    "Default detail is compact (name and id). Pass detail=wiring only for one named automation's wiring. Not live state."
)
CATALOG_INSTRUCTIONS = (
    "For counts, lists, names, and on/off, call the Home Assistant MCP tools first (domain-filtered listing, 1–3 calls). "
    "search_catalog is a capped static index for wiring of one named item (triggers, acts_on, related ids). "
    "Default detail is compact. Use detail=wiring only for one named item. "
    "The catalog has no live on/off and is a poor substitute for a full live list."
)
HOUSE_MAP_INSTRUCTIONS = CATALOG_INSTRUCTIONS

_COMPACT_LIMIT = 80
_WIRING_LIMIT = 24
_REFRESH_SECONDS = 15 * 60
_ACTOR_DOMAINS = {
    "switch",
    "light",
    "valve",
    "cover",
    "fan",
    "lock",
    "input_boolean",
    "climate",
    "humidifier",
    "siren",
    "button",
}


def tool_definition() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words to match against names, aliases, tags, and ids.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["any", "entity", "area", "automation", "dashboard"],
                    "description": "Limit to one kind of row. Default any.",
                },
                "detail": {
                    "type": "string",
                    "enum": ["compact", "wiring"],
                    "description": "compact (default): name and id. wiring: triggers, acts_on, related ids.",
                },
            },
            "required": ["query"],
        },
    }


def _label_names(hass: HomeAssistant, label_ids: Any) -> list[str]:
    ids = [str(item) for item in (label_ids or []) if item]
    if not ids:
        return []
    try:
        from homeassistant.helpers import label_registry as lr

        registry = lr.async_get(hass)
    except Exception:
        return []
    names: list[str] = []
    getter = getattr(registry, "async_get_label", None)
    labels = getattr(registry, "labels", None)
    for lid in ids:
        label = getter(lid) if callable(getter) else (labels.get(lid) if isinstance(labels, dict) else None)
        if label is None:
            continue
        name = str(getattr(label, "name", None) or lid).strip()
        if name:
            names.append(name)
    return uniq(names, 8)


def _automation_entities(hass: HomeAssistant) -> list[Any]:
    components = hass.data.get("entity_components")
    if isinstance(components, dict):
        component = components.get("automation")
        entities = getattr(component, "entities", None) if component is not None else None
        if entities:
            if isinstance(entities, dict):
                return list(entities.values())
            return list(entities)
    return []


def _raw_config(entity: Any) -> dict[str, Any]:
    for key in ("raw_config", "_config", "config"):
        value = getattr(entity, key, None)
        if isinstance(value, dict) and value:
            return value
    return {}


def _entities_for_device(registry: er.EntityRegistry, device_id: str, *, actors: bool) -> list[str]:
    try:
        entries = er.async_entries_for_device(registry, device_id, include_disabled_entities=False)
    except TypeError:
        entries = [item for item in registry.entities.values() if item.device_id == device_id and item.disabled_by is None]
    out: list[str] = []
    for item in entries:
        domain = str(item.domain or "")
        if actors and domain not in _ACTOR_DOMAINS:
            continue
        if not actors and domain in _ACTOR_DOMAINS:
            continue
        out.append(item.entity_id)
    return out


def collect_rows(hass: HomeAssistant) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    areas = ar.async_get(hass)
    area_names = {area.id: area.name for area in areas.async_list_areas()}
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    entity_by_id = {entity.entity_id: entity for entity in _automation_entities(hass)}
    pending_autos: list[dict[str, Any]] = []

    for area_id, name in area_names.items():
        rows.append(("area", area_id, name or area_id, area_id, "", json.dumps({"area": name or area_id}, ensure_ascii=False)))

    for entry in registry.entities.values():
        if entry.disabled_by is not None:
            continue
        name = (entry.name or entry.original_name or entry.entity_id or "").strip()
        area_id = entry.area_id or ""
        if not area_id and entry.device_id:
            device = devices.async_get(entry.device_id)
            if device is not None:
                area_id = str(device.area_id or "")
        area_name = area_names.get(area_id, "")
        label = f"{name} ({area_name})" if area_name else name
        aliases = uniq(list(getattr(entry, "aliases", None) or []), 8)
        tags = _label_names(hass, getattr(entry, "labels", None))
        kind = "automation" if entry.domain == "automation" else "entity"
        extra: dict[str, Any] = extra_payload(
            entity_id=entry.entity_id,
            aliases=aliases,
            tags=tags,
            area=area_name,
        )
        if kind == "automation":
            state = hass.states.get(entry.entity_id)
            config_id = ""
            if state is not None:
                config_id = str(state.attributes.get("id") or "").strip()
            extra["config_id"] = config_id
            entity = entity_by_id.get(entry.entity_id)
            config = _raw_config(entity) if entity is not None else {}
            trigger_summary = summarize_triggers(config) if config else ""
            acted = list(acts_on_ids(config) if config else [])
            depended = list(depends_on_ids(config) if config else [])
            if config:
                for device_id in harvest_device_ids(config, ACTION_KEYS):
                    acted.extend(_entities_for_device(registry, device_id, actors=True))
                for device_id in harvest_device_ids(config, ("trigger", "triggers", "condition", "conditions")):
                    depended.extend(_entities_for_device(registry, device_id, actors=False))
            extra.update(
                extra_payload(
                    entity_id=entry.entity_id,
                    config_id=config_id,
                    aliases=aliases,
                    tags=tags,
                    trigger_summary=trigger_summary,
                    acts_on_ids=acted,
                    depends_on_ids=depended,
                    area=area_name,
                )
            )
            pending_autos.append(
                {
                    "entity_id": entry.entity_id,
                    "config_id": config_id,
                    "name": name,
                    "acts_on": extra.get("acts_on") or [],
                    "row": extra,
                }
            )
        rows.append((kind, entry.entity_id, label or entry.entity_id, area_id, entry.domain or "", json.dumps(extra, ensure_ascii=False)))

    for state in hass.states.async_all("automation"):
        entity_id = state.entity_id
        if any(row[1] == entity_id for row in rows):
            continue
        config_id = str(state.attributes.get("id") or "").strip()
        name = str(state.attributes.get("friendly_name") or entity_id).strip()
        extra = extra_payload(entity_id=entity_id, config_id=config_id)
        pending_autos.append(
            {
                "entity_id": entity_id,
                "config_id": config_id,
                "name": name,
                "acts_on": [],
                "row": extra,
            }
        )
        rows.append(("automation", entity_id, name, "", "automation", json.dumps(extra, ensure_ascii=False)))

    related = related_config_ids(pending_autos)
    if related:
        by_entity = {item["entity_id"]: item for item in pending_autos}
        rewritten: list[tuple[str, str, str, str, str, str]] = []
        for row in rows:
            if row[0] != "automation":
                rewritten.append(row)
                continue
            item = by_entity.get(row[1])
            if item is None:
                rewritten.append(row)
                continue
            extra = dict(item["row"])
            related_ids = related.get(str(item.get("config_id") or ""), [])
            if related_ids:
                extra["related_config_ids"] = related_ids
            rewritten.append((row[0], row[1], row[2], row[3], row[4], json.dumps(extra, ensure_ascii=False)))
        rows = rewritten

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
    _LOGGER.debug("config catalog refreshed rows=%s", len(rows))
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
        if name not in {TOOL_NAME, *TOOL_ALIASES}:
            raise McpError(f"Unknown catalog tool: {name}")
        args = arguments or {}
        query = str(args.get("query") or "").strip()
        kind = str(args.get("kind") or "any").strip() or "any"
        detail = str(args.get("detail") or "compact").strip().lower() or "compact"
        if not query:
            return {"matches": [], "note": "Provide a query string. For a full name list with on/off, use Home Assistant MCP."}
        limit = _WIRING_LIMIT if detail == "wiring" else _COMPACT_LIMIT
        matches = await self.hass.async_add_executor_job(
            search_house_map, self.store, query, kind, limit
        )
        matches = apply_catalog_detail(matches, detail)
        return {
            "matches": matches,
            "note": "Static catalog. Not live state. For a full name list with on/off, use Home Assistant MCP.",
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
    return f"{base.rstrip('/')}/api/ai_workspace/catalog/mcp"


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
            _LOGGER.exception("config catalog refresh failed")

    await _refresh()

    @callback
    def _schedule(_event: Event | None = None) -> None:
        hass.async_create_task(_refresh())

    unsubs = [
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _schedule),
        hass.bus.async_listen(ar.EVENT_AREA_REGISTRY_UPDATED, _schedule),
        hass.bus.async_listen("automation_reloaded", _schedule),
    ]
    timer = async_track_time_interval(hass, _refresh, timedelta(seconds=_REFRESH_SECONDS))
    unsubs.append(timer)

    def _cancel() -> None:
        for item in unsubs:
            item()

    bucket["house_map_unsub"] = _cancel
