"""Snapshot and restore Home Assistant config documents for the activity list."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH, SCENE_CONFIG_PATH, SCRIPT_CONFIG_PATH
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .activity import Change, classify, describe_index, index_items, summary, tool_succeeded, watches_config
from .const import DOMAIN
from .store import Store

logger = logging.getLogger(__name__)

_PENDING_TTL = 600
_YAML = {
    "automation": AUTOMATION_CONFIG_PATH,
    "script": SCRIPT_CONFIG_PATH,
    "scene": SCENE_CONFIG_PATH,
}


class ActivityError(RuntimeError):
    pass


@dataclass
class Pending:
    user_id: str
    user_name: str
    agent: str
    tool: str
    summary: str
    document: dict[str, Any] | None
    watch: dict[str, tuple[str, str]] | None
    at: float


def _pending(hass: HomeAssistant) -> dict[str, Pending]:
    bucket = hass.data.setdefault(DOMAIN, {})
    pending = bucket.get("activity_pending")
    if not isinstance(pending, dict):
        pending = {}
        bucket["activity_pending"] = pending
    return pending


def _drop_old(pending: dict[str, Pending]) -> None:
    cutoff = time.monotonic() - _PENDING_TTL
    for key in [item for item, row in pending.items() if row.at < cutoff]:
        pending.pop(key, None)


async def track_tool(
    hass: HomeAssistant,
    store: Store,
    user_id: str,
    user_name: str,
    agent: str,
    tool: str,
    arguments: dict[str, Any],
    call,
):
    """Snapshot, run the tool, and keep a row only when the call succeeds."""
    token = None
    try:
        token = await prepare(hass, user_id, user_name, agent, tool, arguments)
    except Exception:
        logger.warning("activity prepare failed", exc_info=True)
    try:
        result = await call(tool, arguments)
    except Exception:
        if token:
            try:
                await commit(hass, store, token, ok=False)
            except Exception:
                logger.warning("activity commit failed", exc_info=True)
        raise
    if token:
        try:
            await commit(hass, store, token, ok=tool_succeeded(result))
        except Exception:
            logger.warning("activity commit failed", exc_info=True)
    return result


async def prepare(
    hass: HomeAssistant,
    user_id: str,
    user_name: str,
    agent: str,
    tool: str,
    arguments: dict[str, Any] | None,
) -> str | None:
    args = arguments if isinstance(arguments, dict) else {}
    change = classify(tool, args)
    watch = None
    document = None
    text = ""
    if change is None:
        if not watches_config(tool):
            return None
        watch = await collect_index(hass)
    else:
        if change.action != "create":
            document = await snapshot(hass, change)
        if document is None and change.action == "update":
            change = Change(
                kind=change.kind,
                action="create",
                item_id=change.item_id,
                label=change.label,
                domain=change.domain,
            )
        found = ""
        if isinstance(document, dict):
            found = str(document.get("label") or "")
        text = summary(change, found)
        if change.action != "create" and document is None:
            document = None
    token = uuid.uuid4().hex
    pending = _pending(hass)
    _drop_old(pending)
    pending[token] = Pending(
        user_id=user_id,
        user_name=user_name or user_id,
        agent=agent or "Agent",
        tool=str(tool or ""),
        summary=text,
        document=document if isinstance(document, dict) else None,
        watch=watch,
        at=time.monotonic(),
    )
    return token


async def commit(hass: HomeAssistant, store: Store, token: str, *, ok: bool) -> None:
    pending = _pending(hass).pop(str(token or ""), None)
    if pending is None or not ok:
        return
    text = pending.summary
    document = pending.document
    if pending.watch is not None:
        text = describe_index(pending.watch, await collect_index(hass))
        document = None
        if not text:
            return
    if not text:
        return
    await hass.async_add_executor_job(
        store.add_activity,
        pending.user_id,
        pending.user_name,
        pending.agent,
        text,
        pending.tool,
        json.dumps(document, ensure_ascii=False, default=str) if document else "",
    )


async def rollback(hass: HomeAssistant, document: dict[str, Any]) -> None:
    kind = str(document.get("kind") or "")
    if kind in _YAML:
        await _restore_yaml(hass, kind, document)
        return
    if kind == "helper":
        await _restore_helper(hass, document)
        return
    if kind == "entity":
        _restore_entity(hass, document)
        return
    if kind == "dashboard":
        await _restore_dashboard(hass, document)
        return
    raise ActivityError("This change has nothing to restore.")


async def snapshot(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    if change.kind in _YAML:
        return await hass.async_add_executor_job(_snapshot_yaml, hass, change)
    if change.kind == "helper":
        return _snapshot_helper(hass, change)
    if change.kind == "entity":
        return _snapshot_entity(hass, change)
    if change.kind == "dashboard":
        return await _snapshot_dashboard(hass, change)
    return None


async def collect_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    yaml_index = await hass.async_add_executor_job(_yaml_index, hass)
    yaml_index.update(_entity_index(hass))
    yaml_index.update(await _dashboard_index(hass))
    return yaml_index


def _read_yaml(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    return load_yaml(path)


def _write_yaml(path: str, data: Any) -> None:
    write_utf8_file_atomic(path, dump(data))


def _config_id(hass: HomeAssistant, kind: str, identifier: str) -> str:
    raw = str(identifier or "").strip()
    if not raw:
        return ""
    prefix = f"{kind}."
    if raw.startswith(prefix):
        state = hass.states.get(raw)
        if state is not None:
            found = str(state.attributes.get("id") or "").strip()
            if found:
                return found
        entry = er.async_get(hass).async_get(raw)
        if entry is not None and entry.unique_id:
            return str(entry.unique_id)
        return raw.split(".", 1)[1]
    return raw


def _snapshot_yaml(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    path = hass.config.path(_YAML[change.kind])
    data = _read_yaml(path)
    item_id = _config_id(hass, change.kind, change.item_id)
    if change.kind == "script":
        if not isinstance(data, dict):
            return None
        item = data.get(item_id)
        if not isinstance(item, dict):
            return None
        label = str(item.get("alias") or item.get("name") or item_id)
        return {"kind": "script", "id": item_id, "label": label, "item": item}
    rows = data if isinstance(data, list) else []
    for item in rows:
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            label = str(item.get("alias") or item.get("name") or item_id)
            return {"kind": change.kind, "id": item_id, "label": label, "item": item}
    return None


def _yaml_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for kind, relative in _YAML.items():
        data = _read_yaml(hass.config.path(relative))
        found.update(index_items(kind, data))
    return found


async def _restore_yaml(hass: HomeAssistant, kind: str, document: dict[str, Any]) -> None:
    item_id = str(document.get("id") or "")
    item = document.get("item")
    if not item_id or not isinstance(item, dict):
        raise ActivityError("The saved document is incomplete.")
    path = hass.config.path(_YAML[kind])

    def write() -> None:
        current = _read_yaml(path)
        if kind == "script":
            data = dict(current) if isinstance(current, dict) else {}
            data[item_id] = item
        else:
            rows = [row for row in (current or []) if not (isinstance(row, dict) and str(row.get("id") or "") == item_id)]
            rows.append(item)
            data = rows
        _write_yaml(path, data)

    await hass.async_add_executor_job(write)
    payload = {"id": item_id} if kind == "automation" else {}
    await hass.services.async_call(kind, SERVICE_RELOAD, payload, blocking=True)


def _collection(hass: HomeAssistant, prefix: str):
    handlers = hass.data.get("websocket_api") or {}
    slot = handlers.get(f"{prefix}/list") if isinstance(handlers, dict) else None
    handler = slot[0] if isinstance(slot, tuple) and slot else None
    seen: set[int] = set()
    while handler is not None and id(handler) not in seen:
        seen.add(id(handler))
        owner = getattr(handler, "__self__", None)
        collection = getattr(owner, "storage_collection", None)
        if collection is not None and hasattr(collection, "data"):
            return collection
        handler = getattr(handler, "__wrapped__", None)
    return None


def _helper_ids(change: Change) -> tuple[str, str]:
    domain = change.domain
    item_id = change.item_id
    if "." in item_id:
        prefix, rest = item_id.split(".", 1)
        if not domain:
            domain = prefix
        item_id = rest
    return domain, item_id


def _snapshot_helper(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    domain, item_id = _helper_ids(change)
    if not domain or not item_id:
        return None
    collection = _collection(hass, domain)
    if collection is None:
        return None
    item = collection.data.get(item_id) if isinstance(collection.data, dict) else None
    if not isinstance(item, dict):
        return None
    label = str(item.get("name") or item.get("alias") or item_id)
    return {"kind": "helper", "domain": domain, "id": item_id, "label": label, "item": dict(item)}


async def _restore_helper(hass: HomeAssistant, document: dict[str, Any]) -> None:
    domain = str(document.get("domain") or "")
    item_id = str(document.get("id") or "")
    item = document.get("item")
    if not domain or not item_id or not isinstance(item, dict):
        raise ActivityError("The saved helper is incomplete.")
    collection = _collection(hass, domain)
    if collection is None:
        raise ActivityError("That helper type is not available.")
    payload = {key: value for key, value in item.items() if key != "id"}
    try:
        if item_id in collection.data:
            await collection.async_update_item(item_id, payload)
        else:
            created = await collection.async_create_item(payload)
            if isinstance(created, dict) and created.get("id") not in {None, item_id}:
                logger.info("helper restore created %s as %s", item_id, created.get("id"))
    except Exception as exc:
        raise ActivityError(str(exc)[:300]) from exc


def _entry_dict(entry) -> dict[str, Any]:
    aliases = []
    for alias in getattr(entry, "aliases", None) or []:
        aliases.append(alias if isinstance(alias, str) else str(getattr(alias, "name", alias)))
    labels = sorted(str(item) for item in (getattr(entry, "labels", None) or []))
    categories = dict(getattr(entry, "categories", None) or {})
    return {
        "kind": "entity",
        "entity_id": entry.entity_id,
        "label": entry.name or entry.original_name or entry.entity_id,
        "name": entry.name,
        "icon": entry.icon,
        "area_id": entry.area_id,
        "disabled_by": getattr(entry.disabled_by, "value", entry.disabled_by),
        "hidden_by": getattr(entry.hidden_by, "value", entry.hidden_by),
        "aliases": aliases,
        "labels": labels,
        "categories": {str(key): str(value) for key, value in categories.items()},
        "platform": entry.platform,
        "unique_id": entry.unique_id,
        "domain": entry.domain,
    }


def _snapshot_entity(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    entity_id = change.item_id
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    return _entry_dict(entry)


def _restore_entity(hass: HomeAssistant, document: dict[str, Any]) -> None:
    registry = er.async_get(hass)
    entity_id = str(document.get("entity_id") or "")
    domain = str(document.get("domain") or "")
    platform = str(document.get("platform") or "")
    unique_id = str(document.get("unique_id") or "")
    current = registry.async_get(entity_id)
    if current is None and domain and platform and unique_id:
        current = registry.async_get_entity_id(domain, platform, unique_id)
        if current is None:
            current_entry = registry.async_get_or_create(domain, platform, unique_id)
            entity_id = current_entry.entity_id
        else:
            entity_id = current
    if registry.async_get(entity_id) is None:
        raise ActivityError("That entity is no longer in the registry.")
    fields = {
        "name": document.get("name"),
        "icon": document.get("icon"),
        "area_id": document.get("area_id"),
        "disabled_by": document.get("disabled_by"),
        "hidden_by": document.get("hidden_by"),
        "aliases": list(document.get("aliases") or []),
        "labels": set(document.get("labels") or []),
        "categories": dict(document.get("categories") or {}),
    }
    saved_id = str(document.get("entity_id") or "")
    if saved_id and saved_id != entity_id:
        fields["new_entity_id"] = saved_id
    registry.async_update_entity(entity_id, **fields)


def _dashboard_key(url_path: str) -> str | None:
    raw = str(url_path or "").strip().strip("/")
    if raw in {"", "lovelace", "default"}:
        return None
    return raw


def _dashboards(hass: HomeAssistant) -> dict:
    lovelace = hass.data.get("lovelace")
    boards = getattr(lovelace, "dashboards", None)
    return boards if isinstance(boards, dict) else {}


async def _snapshot_dashboard(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    key = _dashboard_key(change.item_id)
    board = _dashboards(hass).get(key)
    if board is None and key is None:
        board = _dashboards(hass).get("lovelace")
        key = "lovelace" if board is not None else None
    if board is None:
        return None
    try:
        config = await board.async_load(False)
    except Exception:
        logger.debug("dashboard snapshot skipped for %s", change.item_id, exc_info=True)
        return None
    if not isinstance(config, dict):
        return None
    meta = dict(getattr(board, "config", None) or {})
    label = str(meta.get("title") or change.label or change.item_id or "Overview")
    stored_key = "lovelace" if key is None else str(key)
    return {"kind": "dashboard", "id": stored_key, "label": label, "config": config, "meta": meta}


async def _dashboard_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for key, board in _dashboards(hass).items():
        stored = "lovelace" if key in (None, "") else str(key)
        meta = dict(getattr(board, "config", None) or {})
        label = str(meta.get("title") or stored)
        data = getattr(board, "_data", None)
        config = data.get("config") if isinstance(data, dict) else None
        body = config if isinstance(config, dict) else meta
        found.update(index_items("dashboard", [{"id": stored, "title": label, "config": body}], ("title",)))
    return found


async def _restore_dashboard(hass: HomeAssistant, document: dict[str, Any]) -> None:
    config = document.get("config")
    if not isinstance(config, dict):
        raise ActivityError("The saved dashboard is incomplete.")
    key = _dashboard_key(str(document.get("id") or ""))
    boards = _dashboards(hass)
    board = boards.get(key)
    if board is None and key is None:
        board = boards.get("lovelace")
    if board is None:
        board = await _recreate_dashboard(hass, str(document.get("id") or ""), document.get("meta") or {})
    try:
        await board.async_save(config)
    except Exception as exc:
        raise ActivityError(str(exc)[:300]) from exc


async def _recreate_dashboard(hass: HomeAssistant, url_path: str, meta: dict) -> Any:
    collection = _collection(hass, "lovelace/dashboards")
    if collection is None:
        raise ActivityError("That dashboard is gone.")
    payload = {
        "url_path": url_path or "lovelace",
        "title": str(meta.get("title") or url_path or "Dashboard"),
        "icon": meta.get("icon") or "mdi:view-dashboard",
        "show_in_sidebar": bool(meta.get("show_in_sidebar", True)),
        "require_admin": bool(meta.get("require_admin", False)),
    }
    if url_path in {"lovelace", "map"}:
        payload["allow_single_word"] = True
    try:
        await collection.async_create_item(payload)
    except Exception as exc:
        raise ActivityError(str(exc)[:300]) from exc
    board = _dashboards(hass).get(_dashboard_key(url_path))
    if board is None:
        raise ActivityError("That dashboard is gone.")
    return board


def _entity_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    rows = []
    for entry in er.async_get(hass).entities.values():
        rows.append(
            {
                "id": entry.entity_id,
                "name": entry.name or entry.original_name or entry.entity_id,
                "area_id": entry.area_id,
                "icon": entry.icon,
                "disabled_by": getattr(entry.disabled_by, "value", entry.disabled_by),
                "hidden_by": getattr(entry.hidden_by, "value", entry.hidden_by),
            }
        )
    return index_items("entity", rows, ("name",))
