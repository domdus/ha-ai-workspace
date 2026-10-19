"""Snapshot and restore Home Assistant config documents for the activity list."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH, SCENE_CONFIG_PATH, SCRIPT_CONFIG_PATH
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .activity import (
    Change,
    changed_index_keys,
    classify,
    dashboard_args,
    dashboard_id_from_args,
    dashboard_store_id,
    describe_index,
    entity_ids_from_args,
    index_items,
    looks_like_config_write,
    summary,
    tool_succeeded,
    watches_config,
    yaml_kind_from_args,
)
from .const import DOMAIN
from .store import Store

logger = logging.getLogger(__name__)

_PENDING_TTL = 600
# Lovelace often fires lovelace_updated after the MCP HTTP response returns.
_SETTLE_DELAYS = (0.15, 0.25, 0.35, 0.45)
_EVENT_LOVELACE = "lovelace_updated"
_EVENT_ENTITY_REGISTRY = "entity_registry_updated"
_EVENT_AUTOMATION_RELOADED = "automation_reloaded"
_EVENT_SCRIPT_RELOADED = "script_reloaded"
_EVENT_SCENE_RELOADED = "scene_reloaded"
_MISSING = object()
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
    session_id: str
    chat: str
    at: float
    events: list[tuple] = field(default_factory=list)
    unsubs: list = field(default_factory=list)
    dashboard_docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    entity_docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    yaml_docs: dict[str, dict[str, Any]] = field(default_factory=dict)


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
        _unsub(pending.pop(key))


def _unsub(row: Pending | None) -> None:
    if row is None:
        return
    for unsub in row.unsubs:
        try:
            unsub()
        except Exception:
            logger.debug("activity listener unsubscribe failed", exc_info=True)
    row.unsubs.clear()


def _listen(hass: HomeAssistant, row: Pending) -> None:
    @callback
    def on_lovelace(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        row.events.append(("dashboard", data.get("url_path")))

    @callback
    def on_entity(event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        entity_id = data.get("entity_id") or data.get("old_entity_id")
        row.events.append(("entity", entity_id, str(data.get("action") or "update")))

    @callback
    def on_yaml_reload(event: Event) -> None:
        if event.event_type == _EVENT_SCRIPT_RELOADED:
            kind = "script"
        elif event.event_type == _EVENT_SCENE_RELOADED:
            kind = "scene"
        else:
            kind = "automation"
        data = event.data if isinstance(event.data, dict) else {}
        row.events.append(("yaml", kind, data.get("id") or data.get("entity_id")))

    row.unsubs = [
        hass.bus.async_listen(_EVENT_LOVELACE, on_lovelace),
        hass.bus.async_listen(_EVENT_ENTITY_REGISTRY, on_entity),
        hass.bus.async_listen(_EVENT_AUTOMATION_RELOADED, on_yaml_reload),
        hass.bus.async_listen(_EVENT_SCRIPT_RELOADED, on_yaml_reload),
        hass.bus.async_listen(_EVENT_SCENE_RELOADED, on_yaml_reload),
    ]


async def track_tool(
    hass: HomeAssistant,
    store: Store,
    user_id: str,
    user_name: str,
    agent: str,
    tool: str,
    arguments: dict[str, Any],
    call,
    session_id: str = "",
):
    """Snapshot, run the tool, and keep a row only when the call succeeds."""
    token = None
    try:
        token = await prepare(hass, user_id, user_name, agent, tool, arguments, session_id)
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
    session_id: str = "",
) -> str | None:
    args = arguments if isinstance(arguments, dict) else {}
    change = classify(tool, args)
    watch = None
    document = None
    text = ""
    dashboard_docs: dict[str, dict[str, Any]] = {}
    entity_docs: dict[str, dict[str, Any]] = {}
    yaml_docs: dict[str, dict[str, Any]] = {}
    if change is None:
        if not watches_config(tool) and not looks_like_config_write(tool, args):
            return None
        watch = await collect_index(hass)
    else:
        if change.kind == "dashboard":
            dashboard_docs = await _snapshot_all_dashboards(hass)
            watch = await collect_index(hass)
        if change.action != "create":
            document = await snapshot(hass, change)
            if document is None and change.kind == "dashboard":
                document = _pick_dashboard_doc(dashboard_docs, change.item_id)
        if document is None and change.action == "update":
            change = Change(
                kind=change.kind,
                action="create",
                item_id=change.item_id,
                label=change.label,
                domain=change.domain,
            )
            if watch is None:
                watch = await collect_index(hass)
        found = ""
        if isinstance(document, dict):
            found = str(document.get("label") or "")
        text = summary(change, found)
        if change.action != "create" and document is None:
            document = None
    want_dashboards = (change is not None and change.kind == "dashboard") or dashboard_args(args)
    if (want_dashboards or watch is not None) and not dashboard_docs:
        dashboard_docs = await _snapshot_all_dashboards(hass)
    if document is None and dashboard_docs and (change is None or change.kind == "dashboard"):
        document = _pick_dashboard_doc(dashboard_docs, change.item_id if change else dashboard_id_from_args(args))
        if isinstance(document, dict):
            text = summary(
                Change(
                    kind="dashboard",
                    action="update",
                    item_id=str(document.get("id") or ""),
                    label=str(document.get("label") or ""),
                    domain="lovelace",
                ),
                str(document.get("label") or ""),
            )
    ids = entity_ids_from_args(args)
    if change is not None and change.kind == "entity" and change.item_id and change.item_id not in ids:
        ids = [change.item_id, *ids]
    for entity_id in ids:
        snap = _snapshot_entity(hass, Change(kind="entity", action="update", item_id=entity_id, label=""))
        if snap:
            entity_docs[entity_id] = snap
            if document is None and change is not None and change.kind == "entity":
                document = snap
    yaml_kind = change.kind if change is not None and change.kind in _YAML else yaml_kind_from_args(args)
    if yaml_kind:
        if isinstance(document, dict) and document.get("kind") == yaml_kind:
            yaml_docs[_yaml_doc_key(document)] = document
        else:
            yaml_docs = await _snapshot_yaml_docs(hass, (yaml_kind,))
            if document is None:
                document = _pick_yaml_doc(yaml_docs, yaml_kind, change.item_id if change else "")
                if isinstance(document, dict):
                    text = summary(
                        Change(
                            kind=yaml_kind,
                            action="update",
                            item_id=str(document.get("id") or ""),
                            label=str(document.get("label") or ""),
                            domain=yaml_kind,
                        ),
                        str(document.get("label") or ""),
                    )
    token = uuid.uuid4().hex
    pending = _pending(hass)
    _drop_old(pending)
    row = Pending(
        user_id=user_id,
        user_name=user_name or user_id,
        agent=agent or "Agent",
        tool=str(tool or ""),
        summary=text,
        document=document if isinstance(document, dict) else None,
        watch=watch,
        session_id=str(session_id or ""),
        chat=_session_title(hass, session_id),
        at=time.monotonic(),
        dashboard_docs=dashboard_docs,
        entity_docs=entity_docs,
        yaml_docs=yaml_docs,
    )
    pending[token] = row
    _listen(hass, row)
    return token


def _same_body(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, default=str, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, default=str, ensure_ascii=False
    )


def _saved_body(document: dict[str, Any]) -> object:
    if "item" in document:
        return document.get("item")
    if document.get("kind") == "dashboard":
        return document.get("config")
    return {
        key: document.get(key)
        for key in (
            "entity_id",
            "name",
            "icon",
            "area_id",
            "disabled_by",
            "hidden_by",
            "aliases",
            "labels",
            "categories",
            "device_class",
        )
    }


async def _document_changed(hass: HomeAssistant, document: dict[str, Any]) -> bool:
    """True when the saved config document is different after the tool returned."""
    kind = str(document.get("kind") or "")
    item_id = str(document.get("entity_id") or "") if kind == "entity" else str(document.get("id") or "")
    if not kind or not item_id:
        return False
    current = await snapshot(
        hass,
        Change(
            kind=kind,
            action="update",
            item_id=item_id,
            label="",
            domain=str(document.get("domain") or ""),
        ),
    )
    if current is None:
        return True
    return not _same_body(_saved_body(document), _saved_body(current))


def _pick_dashboard_doc(docs: dict[str, dict[str, Any]], item_id: str | None) -> dict[str, Any] | None:
    store_id = dashboard_store_id(item_id)
    if store_id in docs:
        return docs[store_id]
    for alt in (store_id.replace("-", "_"), store_id.replace("_", "-")):
        if alt in docs:
            return docs[alt]
    return None


def _document_for_index_keys(pending: Pending, keys: list[str]) -> dict[str, Any] | None:
    dash: list[dict[str, Any]] = []
    ents: list[dict[str, Any]] = []
    yaml_docs: list[dict[str, Any]] = []
    for key in keys:
        kind, _, item_id = key.partition(":")
        if kind == "dashboard":
            found = _pick_dashboard_doc(pending.dashboard_docs, item_id)
            if found:
                dash.append(found)
        elif kind == "entity":
            found = pending.entity_docs.get(item_id)
            if found:
                ents.append(found)
        elif kind in _YAML:
            found = _pick_yaml_doc(pending.yaml_docs, kind, item_id)
            if found:
                yaml_docs.append(found)
    if len(yaml_docs) == 1:
        return yaml_docs[0]
    if len(dash) == 1:
        return dash[0]
    if len(ents) == 1:
        return ents[0]
    return None


def _summary_from_events(pending: Pending) -> str:
    for item in pending.events:
        if item[0] == "yaml":
            kind = str(item[1] or "automation")
            doc = _pick_yaml_doc(pending.yaml_docs, kind, item[2] if len(item) > 2 else "")
            label = str((doc or {}).get("label") or item[2] or kind)
            return f"Updated {kind} {label}"
        if item[0] == "dashboard":
            store_id = dashboard_store_id(item[1])
            doc = _pick_dashboard_doc(pending.dashboard_docs, store_id)
            label = str((doc or {}).get("label") or store_id or "Overview")
            action = "Updated" if doc is not None else "Created"
            return f"{action} dashboard {label}"
        if item[0] == "entity":
            entity_id = str(item[1] or "")
            doc = pending.entity_docs.get(entity_id)
            label = str((doc or {}).get("label") or entity_id)
            action = item[2] if len(item) > 2 else "update"
            if action == "remove":
                return f"Deleted entity {label}"
            if action == "create":
                return f"Created entity {label}"
            return f"Updated entity {label}"
    return ""


async def _apply_events(hass: HomeAssistant, pending: Pending) -> tuple[dict[str, Any] | None, str]:
    dash_path: object = _MISSING
    entity_id = None
    entity_action = "update"
    yaml_kind = None
    yaml_id = None
    for item in pending.events:
        if item[0] == "yaml" and yaml_kind is None:
            yaml_kind = str(item[1] or "automation")
            yaml_id = item[2] if len(item) > 2 else None
        elif item[0] == "dashboard" and dash_path is _MISSING:
            dash_path = item[1]
        elif item[0] == "entity" and entity_id is None:
            entity_id = item[1]
            entity_action = str(item[2] if len(item) > 2 else "update")
    if yaml_kind:
        before = _pick_yaml_doc(pending.yaml_docs, yaml_kind, yaml_id)
        if before is None and isinstance(pending.document, dict) and pending.document.get("kind") == yaml_kind:
            before = pending.document
        label = str((before or {}).get("label") or yaml_id or yaml_kind)
        text = summary(
            Change(kind=yaml_kind, action="update", item_id=str((before or {}).get("id") or yaml_id or ""), label=label, domain=yaml_kind),
            label,
        )
        return before, text
    if dash_path is not _MISSING:
        store_id = dashboard_store_id(dash_path)
        before = _pick_dashboard_doc(pending.dashboard_docs, store_id)
        label = str((before or {}).get("label") or store_id or "Overview")
        action = "update"
        current = await snapshot(
            hass,
            Change(kind="dashboard", action="update", item_id=store_id, label="", domain="lovelace"),
        )
        if before is None:
            action = "create"
            label = str((current or {}).get("label") or label)
        elif current is None:
            action = "delete"
        text = summary(
            Change(kind="dashboard", action=action, item_id=store_id, label=label, domain="lovelace"),
            label,
        )
        return before, text
    domain = str(entity_id or "").split(".", 1)[0]
    if entity_id and domain in _YAML:
        before = _pick_yaml_doc(pending.yaml_docs, domain, entity_id)
        if before is None and isinstance(pending.document, dict) and pending.document.get("kind") == domain:
            before = pending.document
        action = "delete" if entity_action == "remove" else ("create" if entity_action == "create" else "update")
        label = str((before or {}).get("label") or entity_id)
        text = summary(Change(kind=domain, action=action, item_id=str(entity_id), label=label, domain=domain), label)
        return before, text
    if entity_id:
        before = pending.entity_docs.get(str(entity_id))
        if before is None and isinstance(pending.document, dict) and pending.document.get("entity_id") == entity_id:
            before = pending.document
        action = "delete" if entity_action == "remove" else ("create" if entity_action == "create" else "update")
        label = str((before or {}).get("label") or entity_id)
        text = summary(Change(kind="entity", action=action, item_id=str(entity_id), label=label), label)
        return before, text
    return None, ""


async def _dashboard_docs_changed(hass: HomeAssistant, docs: dict[str, dict[str, Any]]) -> bool:
    current = await _snapshot_all_dashboards(hass)
    if set(current) != set(docs):
        return True
    for store_id, doc in docs.items():
        now = current.get(store_id)
        if now is None:
            return True
        if not _same_body(doc.get("config"), now.get("config")):
            return True
    return False


async def _activity_settle(hass: HomeAssistant, pending: Pending) -> None:
    """Keep bus listeners active while HA finishes Lovelace / registry updates."""
    document = pending.document if isinstance(pending.document, dict) else None
    if not (pending.dashboard_docs or pending.watch is not None or document or pending.tool):
        return
    for delay in _SETTLE_DELAYS:
        if pending.events:
            return
        if pending.watch is not None:
            after = await collect_index(hass)
            if describe_index(pending.watch, after):
                return
        if document is not None and await _document_changed(hass, document):
            return
        if pending.dashboard_docs and await _dashboard_docs_changed(hass, pending.dashboard_docs):
            return
        await asyncio.sleep(delay)


async def commit(hass: HomeAssistant, store: Store, token: str, *, ok: bool) -> None:
    key = str(token or "")
    pending = _pending(hass).get(key)
    if pending is None:
        return
    await _activity_settle(hass, pending)
    pending = _pending(hass).pop(key, None)
    if pending is None:
        return
    _unsub(pending)
    text = pending.summary
    document = pending.document
    event_doc, event_text = await _apply_events(hass, pending)
    if event_text:
        text = event_text
    if event_doc is not None:
        document = event_doc
    after = None
    if pending.watch is not None:
        after = await collect_index(hass)
        indexed = describe_index(pending.watch, after)
        if indexed:
            text = event_text or indexed
            attached = _document_for_index_keys(pending, changed_index_keys(pending.watch, after))
            if attached is not None:
                document = attached
            elif event_doc is None:
                document = pending.document
        elif not pending.events and not text:
            return
        elif not ok and not pending.events:
            logger.info("activity skipped %s ok=false unchanged", pending.tool)
            return
    elif isinstance(document, dict):
        # A description-only or action-alias edit is still a change. Keep it
        # when the document moved, even if the tool result looked like a failure.
        # HA may return from the config API before automations.yaml is flushed.
        changed = await _document_changed(hass, document) or bool(pending.events)
        if not changed:
            for delay in (0.2, 0.35):
                await asyncio.sleep(delay)
                changed = await _document_changed(hass, document) or bool(pending.events)
                if changed:
                    break
        if not ok and not changed and not pending.events:
            logger.info("activity skipped %s ok=false unchanged", pending.tool)
            return
        if ok and not changed and not pending.events and not text:
            logger.info("activity skipped %s ok=true unchanged", pending.tool)
            return
    elif not ok and not pending.events:
        return
    if not text:
        if pending.events:
            text = event_text or _summary_from_events(pending)
        else:
            return
    chat = _session_title(hass, pending.session_id) or pending.chat
    doc_dict = document if isinstance(document, dict) else None
    from .logical_commit import queue_activity_fragment

    if queue_activity_fragment(
        hass,
        user_id=pending.user_id,
        user_name=pending.user_name,
        agent=pending.agent,
        session_id=pending.session_id,
        chat=chat,
        summary=text,
        tool=pending.tool,
        document=doc_dict,
    ):
        return
    row = await hass.async_add_executor_job(
        store.add_activity,
        pending.user_id,
        pending.user_name,
        pending.agent,
        text,
        pending.tool,
        json.dumps(document, ensure_ascii=False, default=str) if document else "",
        pending.session_id,
        chat,
    )
    if isinstance(document, dict) and document.get("kind") in _YAML:
        await hass.async_add_executor_job(_write_change_file, store, row, document)


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
        file_doc = await hass.async_add_executor_job(_snapshot_yaml, hass, change)
        return file_doc or _snapshot_live(hass, change)
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


def _write_change_file(store: Store, row, document: dict[str, Any]) -> None:
    """YAML copy of one automation, script, or scene for recovery if Home Assistant will not start."""
    kind = str(document.get("kind") or "")
    item = document.get("item")
    item_id = str(document.get("id") or "")
    if kind not in _YAML or not isinstance(item, dict):
        return
    body: Any = {item_id: item} if kind == "script" and item_id else item
    header = "\n".join(
        [
            "# AI Workspace change snapshot",
            f"# {row.created_at}",
            f"# {row.summary}",
            f"# {row.chat} · {row.agent}".strip(" ·"),
            f"# Restore: merge this into {_YAML[kind]} (same id), then reload {kind}s.",
            "",
        ]
    )
    path = store.change_path(row.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_utf8_file_atomic(str(path), header + dump(body))


def _session_title(hass: HomeAssistant, session_id: str) -> str:
    store = (hass.data.get(DOMAIN) or {}).get("store")
    if store is None or not str(session_id or "").strip():
        return ""
    return str(store.session_title(session_id) or "")


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


def _yaml_item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("unique_id") or "").strip()


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
        if isinstance(item, dict) and _yaml_item_id(item) == item_id:
            label = str(item.get("alias") or item.get("name") or item_id)
            return {"kind": change.kind, "id": item_id, "label": label, "item": item}
    return None


def _yaml_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for kind, relative in _YAML.items():
        data = _read_yaml(hass.config.path(relative))
        found.update(index_items(kind, data))
        for doc in _iter_live_docs(hass, kind):
            key = f"{kind}:{doc['id']}"
            if key not in found:
                found.update(index_items(kind, [{"id": doc["id"], "alias": doc["label"], **doc["item"]}]))
    return found


def _yaml_doc_key(document: dict[str, Any]) -> str:
    return f"{document.get('kind')}:{document.get('id')}"


def _pick_yaml_doc(docs: dict[str, dict[str, Any]], kind: str, item_id: object) -> dict[str, Any] | None:
    raw = str(item_id or "").strip()
    for key in (f"{kind}:{raw}", f"{kind}:{raw.split('.', 1)[-1]}" if "." in raw else ""):
        if key and key in docs:
            return docs[key]
    matches = [doc for doc in docs.values() if doc.get("kind") == kind]
    if len(matches) == 1:
        return matches[0]
    prefix = f"{kind}."
    if raw.startswith(prefix):
        rest = raw.split(".", 1)[1]
        for doc in matches:
            if str(doc.get("id") or "") == rest:
                return doc
    return None


def _component_entities(hass: HomeAssistant, kind: str) -> list[Any]:
    components = hass.data.get("entity_components")
    component = components.get(kind) if isinstance(components, dict) else None
    entities = getattr(component, "entities", None) if component is not None else None
    if not entities and kind == "scene":
        platform = hass.data.get("homeassistant_scene")
        entities = getattr(platform, "entities", None)
    if not entities:
        return []
    if isinstance(entities, dict):
        return list(entities.values())
    return list(entities)


def _scene_item(entity: Any) -> dict[str, Any]:
    cfg = getattr(entity, "scene_config", None)
    if cfg is None:
        return {}
    states = getattr(cfg, "states", None) or {}
    entities: dict[str, Any] = {}
    for entity_id, state in states.items() if isinstance(states, dict) else []:
        if hasattr(state, "state"):
            body = dict(getattr(state, "attributes", None) or {})
            body["state"] = state.state
            entities[str(entity_id)] = body
        elif isinstance(state, dict):
            entities[str(entity_id)] = state
        else:
            entities[str(entity_id)] = {"state": str(state)}
    item: dict[str, Any] = {}
    if getattr(cfg, "id", None):
        item["id"] = cfg.id
    if getattr(cfg, "name", None):
        item["name"] = cfg.name
    if getattr(cfg, "icon", None):
        item["icon"] = cfg.icon
    if entities:
        item["entities"] = entities
    return item


def _raw_config(entity: Any) -> dict[str, Any]:
    for key in ("raw_config", "_config", "config"):
        value = getattr(entity, key, None)
        if isinstance(value, dict) and value:
            return dict(value)
    return _scene_item(entity)


def _snapshot_live(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    raw = str(change.item_id or "").strip()
    item_id = _config_id(hass, change.kind, raw)
    prefix = f"{change.kind}."
    for entity in _component_entities(hass, change.kind):
        entity_id = str(getattr(entity, "entity_id", "") or "")
        config = _raw_config(entity)
        state = hass.states.get(entity_id)
        attr_id = str((state.attributes.get("id") if state is not None else "") or "")
        config_id = str(config.get("id") or attr_id or "")
        slug = entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
        aliases = {entity_id, slug, config_id, attr_id, item_id, raw}
        if raw.startswith(prefix):
            aliases.add(raw.split(".", 1)[1])
        if raw not in aliases and item_id not in aliases:
            continue
        if not config:
            continue
        stored = config_id or item_id or slug
        label = str(config.get("alias") or config.get("name") or getattr(entity, "name", None) or stored)
        return {"kind": change.kind, "id": stored, "label": label, "item": config}
    return None


def _iter_live_docs(hass: HomeAssistant, kind: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for entity in _component_entities(hass, kind):
        config = _raw_config(entity)
        if not config:
            continue
        entity_id = str(getattr(entity, "entity_id", "") or "")
        stored = str(config.get("id") or entity_id.split(".", 1)[-1])
        label = str(config.get("alias") or config.get("name") or getattr(entity, "name", None) or stored)
        found.append({"kind": kind, "id": stored, "label": label, "item": config})
    return found


async def _snapshot_yaml_docs(hass: HomeAssistant, kinds: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def from_files() -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for kind in kinds:
            if kind not in _YAML:
                continue
            data = _read_yaml(hass.config.path(_YAML[kind]))
            if kind == "script" and isinstance(data, dict):
                rows = [{"id": key, **item} if isinstance(item, dict) else {"id": key} for key, item in data.items()]
            else:
                rows = data if isinstance(data, list) else []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                item_id = _yaml_item_id(item) if kind != "script" else str(item.get("id") or "")
                if not item_id:
                    continue
                label = str(item.get("alias") or item.get("name") or item_id)
                body = {key: value for key, value in item.items() if key != "id"} if kind == "script" else item
                doc = {"kind": kind, "id": item_id, "label": label, "item": body}
                out[_yaml_doc_key(doc)] = doc
        return out

    found.update(await hass.async_add_executor_job(from_files))
    for kind in kinds:
        for doc in _iter_live_docs(hass, kind):
            found.setdefault(_yaml_doc_key(doc), doc)
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
            rows = [row for row in (current or []) if not (isinstance(row, dict) and _yaml_item_id(row) == item_id)]
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
        "device_class": getattr(entry, "device_class", None),
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
    if "device_class" in document:
        fields["device_class"] = document.get("device_class")
    saved_id = str(document.get("entity_id") or "")
    if saved_id and saved_id != entity_id:
        fields["new_entity_id"] = saved_id
    registry.async_update_entity(entity_id, **fields)


def _dashboard_key(url_path: str) -> str | None:
    store_id = dashboard_store_id(url_path)
    return None if store_id == "lovelace" else store_id


def _board_store_key(key: object) -> str:
    if key in (None, "", "lovelace", "default"):
        return "lovelace"
    return str(key)


def _dashboards(hass: HomeAssistant) -> dict:
    lovelace = hass.data.get("lovelace")
    boards = getattr(lovelace, "dashboards", None)
    return boards if isinstance(boards, dict) else {}


def _resolve_board(hass: HomeAssistant, item_id: str) -> tuple[str, Any]:
    boards = _dashboards(hass)
    store_id = dashboard_store_id(item_id)
    if store_id == "lovelace":
        board = boards.get(None)
        if board is None:
            board = boards.get("lovelace")
        return "lovelace", board
    board = boards.get(store_id)
    if board is not None:
        return store_id, board
    for alt in (store_id.replace("-", "_"), store_id.replace("_", "-")):
        if alt in boards:
            return str(alt), boards[alt]
    return store_id, None


async def _load_board_config(board: Any) -> dict[str, Any] | None:
    try:
        config = await board.async_load(False)
    except Exception:
        logger.debug("dashboard async_load skipped", exc_info=True)
        return None
    return config if isinstance(config, dict) else None


async def _snapshot_board(board: Any, stored_key: str, label: str = "") -> dict[str, Any] | None:
    config = await _load_board_config(board)
    meta = dict(getattr(board, "config", None) or {})
    title = str(meta.get("title") or label or stored_key or "Overview")
    return {
        "kind": "dashboard",
        "id": stored_key,
        "label": title,
        "config": config if isinstance(config, dict) else {},
        "meta": meta,
    }


async def _snapshot_all_dashboards(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for key, board in _dashboards(hass).items():
        stored = _board_store_key(key)
        doc = await _snapshot_board(board, stored)
        if doc:
            found[stored] = doc
    return found


async def _snapshot_dashboard(hass: HomeAssistant, change: Change) -> dict[str, Any] | None:
    store_id, board = _resolve_board(hass, change.item_id)
    if board is None:
        return None
    return await _snapshot_board(board, store_id, change.label)


async def _dashboard_index(hass: HomeAssistant) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for key, board in _dashboards(hass).items():
        stored = _board_store_key(key)
        meta = dict(getattr(board, "config", None) or {})
        label = str(meta.get("title") or stored)
        config = await _load_board_config(board)
        body = config if isinstance(config, dict) else meta
        found.update(index_items("dashboard", [{"id": stored, "title": label, "config": body}], ("title",)))
    return found


async def _restore_dashboard(hass: HomeAssistant, document: dict[str, Any]) -> None:
    config = document.get("config")
    if not isinstance(config, dict):
        raise ActivityError("The saved dashboard is incomplete.")
    _store_id, board = _resolve_board(hass, str(document.get("id") or ""))
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
        aliases = []
        for alias in getattr(entry, "aliases", None) or []:
            aliases.append(alias if isinstance(alias, str) else str(getattr(alias, "name", alias)))
        labels = sorted(str(item) for item in (getattr(entry, "labels", None) or []))
        categories = {str(key): str(value) for key, value in (getattr(entry, "categories", None) or {}).items()}
        rows.append(
            {
                "id": entry.entity_id,
                "name": entry.name or entry.original_name or entry.entity_id,
                "area_id": entry.area_id,
                "icon": entry.icon,
                "disabled_by": getattr(entry.disabled_by, "value", entry.disabled_by),
                "hidden_by": getattr(entry.hidden_by, "value", entry.hidden_by),
                "aliases": sorted(aliases),
                "labels": labels,
                "categories": categories,
                "device_class": getattr(entry, "device_class", None),
            }
        )
    return index_items("entity", rows, ("name",))
