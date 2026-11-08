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
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml

from .activity import (
    Change,
    changed_index_keys,
    classify,
    dashboard_args,
    dashboard_board_key,
    dashboard_id_from_args,
    dashboard_store_id,
    describe_index,
    entity_ids_from_args,
    freeze_mapping,
    index_items,
    looks_like_config_write,
    should_keep_activity,
    summary,
    tool_name,
    tool_succeeded,
    watches_config,
    yaml_kind_from_args,
)
from .const import DOMAIN
from .notes import TOOL_NAME as NOTES_TOOL
from .store import Store

logger = logging.getLogger(__name__)

_PENDING_TTL = 600
_PENDING_MAX = 100
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
    while len(pending) >= _PENDING_MAX:
        _unsub(pending.pop(next(iter(pending))))


def _unsub(row: Pending | None) -> None:
    if row is None:
        return
    for unsub in row.unsubs:
        try:
            unsub()
        except Exception:
            logger.debug("activity listener unsubscribe failed", exc_info=True)
    row.unsubs.clear()


def session_has_pending(hass: HomeAssistant, session_id: str) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    return any(str(row.session_id or "") == sid for row in _pending(hass).values())


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


def unsub_turn(row) -> None:
    for unsub in getattr(row, "unsubs", []) or []:
        try:
            unsub()
        except Exception:
            logger.debug("turn listener unsubscribe failed", exc_info=True)
    if hasattr(row, "unsubs"):
        row.unsubs = []


def _listen_turn(hass: HomeAssistant, row) -> None:
    if getattr(row, "unsubs", None):
        unsub_turn(row)

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


async def attach_turn_watch(hass: HomeAssistant, user_id: str, session_id: str) -> None:
    """Snapshot dashboards and listen for Lovelace while this chat turn is open.

    Cursor config writes go Runtime → HA prepare/commit. If that callback never
    lands, the turn still has a before-image and ``lovelace_updated`` events.
    """
    from .logical_commit import turn_bucket

    row = turn_bucket(hass, user_id, session_id)
    if row is None:
        return
    _listen_turn(hass, row)
    row.dashboard_docs = await _snapshot_all_dashboards(hass, force=True)


async def harvest_turn_changes(hass: HomeAssistant, row) -> None:
    """Fill an empty logical commit from Lovelace events or dashboard diffs.

    Prepare/commit may snapshot the live Lovelace dict. Home Assistant mutates
    that object on save, so a stored document can silently become the after-image.
    When fragments already exist, swap in the turn-start copy if the fragment
    matches the live dashboard and the turn-start copy does not.
    """
    from .logical_commit import ActivityFragment

    if row is None:
        return
    before = dict(getattr(row, "dashboard_docs", None) or {})
    current = await _snapshot_all_dashboards(hass, force=True)
    fragments = getattr(row, "fragments", None) or []
    if fragments:
        for frag in fragments:
            doc = frag.document if isinstance(getattr(frag, "document", None), dict) else None
            if not doc or doc.get("kind") != "dashboard":
                continue
            store_id = str(doc.get("id") or "")
            prior = before.get(store_id)
            live = current.get(store_id)
            prior_cfg = prior.get("config") if isinstance(prior, dict) else None
            live_cfg = live.get("config") if isinstance(live, dict) else None
            if not isinstance(prior_cfg, dict) or not prior_cfg:
                continue
            matches_live = isinstance(live_cfg, dict) and _same_body(doc.get("config"), live_cfg)
            if matches_live and not _same_body(doc.get("config"), prior_cfg):
                frag.document = prior
                logger.info("Change History replaced after-image snapshot for dashboard %s", store_id)
        return
    changed: list[str] = []
    if before:
        for store_id, doc in current.items():
            prior = before.get(store_id)
            if prior is None or not _same_body((prior or {}).get("config"), doc.get("config")):
                changed.append(store_id)
        for store_id in before:
            if store_id not in current:
                changed.append(store_id)
    if not changed:
        for item in getattr(row, "events", []) or []:
            if item and item[0] == "dashboard":
                store_id = dashboard_store_id(item[1])
                if store_id not in changed:
                    changed.append(store_id)
    seen: set[str] = set()
    for store_id in changed:
        if store_id in seen:
            continue
        seen.add(store_id)
        prior = before.get(store_id)
        now = current.get(store_id)
        label = str((prior or now or {}).get("label") or store_id or "Overview")
        if prior is None:
            action = "Created"
        elif now is None:
            action = "Deleted"
        else:
            action = "Updated"
        row.fragments.append(
            ActivityFragment(
                summary=f"{action} dashboard {label}",
                tool="lovelace_updated",
                document=prior if isinstance(prior, dict) else None,
            )
        )


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
    *,
    authorization: str = "",
):
    """Snapshot, run the tool, and keep a row only when the call succeeds."""
    token = None
    try:
        token = await prepare(
            hass, user_id, user_name, agent, tool, arguments, session_id, authorization=authorization
        )
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
    *,
    authorization: str = "",
) -> str | None:
    """Snapshot what a tool is about to change. authorization is the chatting user's own login."""
    args = arguments if isinstance(arguments, dict) else {}
    if tool_name(tool) == NOTES_TOOL:
        return await _prepare_notes(hass, user_id, user_name, agent, tool, args, session_id)
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
            dashboard_docs = await _snapshot_all_dashboards(hass, force=True)
            watch = await collect_index(hass)
        if change.action != "create":
            document = await snapshot(hass, change, force=change.kind == "dashboard", authorization=authorization)
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
        dashboard_docs = await _snapshot_all_dashboards(hass, force=True)
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
        chat=await _session_title(hass, session_id),
        at=time.monotonic(),
        dashboard_docs=dashboard_docs,
        entity_docs=entity_docs,
        yaml_docs=yaml_docs,
    )
    pending[token] = row
    _listen(hass, row)
    return token


_NOTES_SUMMARY = {"add": "Added a remembered note", "remove": "Removed a remembered note", "replace": "Rewrote the remembered notes"}


async def _snapshot_notes(hass: HomeAssistant) -> dict[str, Any]:
    from .notes import async_load_notes

    return {"kind": "notes", "id": "notes", "label": "Remembered notes", "text": await async_load_notes(hass)}


async def _prepare_notes(
    hass: HomeAssistant,
    user_id: str,
    user_name: str,
    agent: str,
    tool: str,
    args: dict[str, Any],
    session_id: str,
) -> str:
    """The notes as they were, so the agent's write can be undone like a config change."""
    action = str(args.get("action") or "").strip().lower()
    token = uuid.uuid4().hex
    pending = _pending(hass)
    _drop_old(pending)
    pending[token] = Pending(
        user_id=user_id,
        user_name=user_name or user_id,
        agent=agent or "Agent",
        tool=str(tool or ""),
        summary=_NOTES_SUMMARY.get(action, "Changed the remembered notes"),
        document=await _snapshot_notes(hass),
        watch=None,
        session_id=str(session_id or ""),
        chat=await _session_title(hass, session_id),
        at=time.monotonic(),
    )
    return token


def _same_body(left: object, right: object) -> bool:
    return json.dumps(left, sort_keys=True, default=str, ensure_ascii=False) == json.dumps(
        right, sort_keys=True, default=str, ensure_ascii=False
    )


def _saved_body(document: dict[str, Any]) -> object:
    if document.get("kind") == "notes":
        return str(document.get("text") or "")
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
        force=True,
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
            item_id = item[2] if len(item) > 2 else ""
            doc = _pick_yaml_doc(pending.yaml_docs, kind, item_id)
            if doc is None and not item_id:
                return f"Changed {'an' if kind[:1] in 'aeiou' else 'a'} {kind}"
            label = str((doc or {}).get("label") or item_id or kind)
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
        if before is None and not yaml_id:
            # A new automation, script, or scene: the reload event names nothing, so
            # "Updated automation automation" would win over the index ("Created automation …").
            return None, ""
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
            force=True,
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
    current = await _snapshot_all_dashboards(hass, force=True)
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
    if document is not None and document.get("kind") == "notes":
        # Saved before the tool returned; nothing in Home Assistant follows later.
        return
    for delay in _SETTLE_DELAYS:
        if pending.events:
            return
        if pending.watch is not None:
            after = await collect_index(hass, force=True)
            if describe_index(pending.watch, after):
                return
        if document is not None and await _document_changed(hass, document):
            return
        if pending.dashboard_docs and await _dashboard_docs_changed(hass, pending.dashboard_docs):
            return
        await asyncio.sleep(delay)


async def commit(hass: HomeAssistant, store: Store, token: str, *, ok: bool, user_id: str | None = None) -> None:
    key = str(token or "")
    pending = _pending(hass).get(key)
    if pending is None:
        return
    if user_id is not None and pending.user_id != user_id:
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
    indexed = ""
    changed = False
    if pending.watch is not None:
        after = await collect_index(hass, force=True)
        indexed = describe_index(pending.watch, after)
        if indexed:
            text = event_text or indexed
            attached = _document_for_index_keys(pending, changed_index_keys(pending.watch, after))
            if attached is not None:
                document = attached
            elif event_doc is None:
                document = pending.document
    if isinstance(document, dict) and document.get("kind") == "notes":
        if not await _document_changed(hass, document):
            logger.info("activity skipped %s: notes unchanged", pending.tool)
            return
        changed = True
    elif isinstance(document, dict):
        changed = await _document_changed(hass, document)
        if not changed and pending.dashboard_docs:
            changed = await _dashboard_docs_changed(hass, pending.dashboard_docs)
        if not changed and not pending.events and not indexed:
            for delay in (0.2, 0.35):
                await asyncio.sleep(delay)
                changed = await _document_changed(hass, document)
                if not changed and pending.dashboard_docs:
                    changed = await _dashboard_docs_changed(hass, pending.dashboard_docs)
                if changed or pending.events:
                    break
    elif pending.dashboard_docs:
        changed = await _dashboard_docs_changed(hass, pending.dashboard_docs)
    if not should_keep_activity(
        ok=ok,
        summary=text,
        events=bool(pending.events),
        indexed=bool(indexed),
        changed=changed,
    ):
        logger.info("activity skipped %s ok=%s unchanged", pending.tool, ok)
        return
    if not text:
        if pending.events:
            text = event_text or _summary_from_events(pending)
        elif indexed:
            text = indexed
        else:
            return
    chat = await _session_title(hass, pending.session_id) or pending.chat
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


async def rollback(hass: HomeAssistant, document: dict[str, Any], authorization: str = "") -> None:
    """authorization is the signed-in user's header; automations, scripts, and scenes go through HA's config API."""
    from .logical_commit import documents_to_restore

    docs = documents_to_restore(document)
    # Several note writes in one turn: the first snapshot is how the notes were before the turn.
    notes = [doc for doc in docs if doc.get("kind") == "notes"]
    docs = [doc for doc in docs if doc.get("kind") != "notes"] + notes[:1]
    restored = 0
    last_error: ActivityError | None = None
    for doc in docs:
        try:
            await _rollback_one(hass, doc, authorization)
        except ActivityError as exc:
            last_error = exc
            continue
        restored += 1
    if restored:
        return
    raise last_error or ActivityError("This change has nothing to restore.")


async def _rollback_one(hass: HomeAssistant, document: dict[str, Any], authorization: str = "") -> None:
    kind = str(document.get("kind") or "")
    if kind in _YAML:
        await _restore_config_item(hass, kind, document, authorization)
        return
    if kind == "helper":
        await _restore_helper(hass, document, authorization)
        return
    if kind == "entity":
        _restore_entity(hass, document)
        return
    if kind == "dashboard":
        await _restore_dashboard(hass, document, authorization)
        return
    if kind == "notes" and isinstance(document.get("text"), str):
        from .notes import async_save_notes, notes_lock

        async with notes_lock(hass):
            await async_save_notes(hass, document["text"])
        return
    raise ActivityError("This change has nothing to restore.")


async def snapshot(
    hass: HomeAssistant, change: Change, force: bool = False, authorization: str = ""
) -> dict[str, Any] | None:
    if change.kind in _YAML:
        file_doc = await hass.async_add_executor_job(_snapshot_yaml, hass, change)
        return file_doc or _snapshot_live(hass, change)
    if change.kind == "helper":
        return await _snapshot_helper(hass, change, authorization)
    if change.kind == "entity":
        return _snapshot_entity(hass, change)
    if change.kind == "dashboard":
        return await _snapshot_dashboard(hass, change, force=force)
    if change.kind == "notes":
        return await _snapshot_notes(hass)
    return None


async def collect_index(hass: HomeAssistant, force: bool = False) -> dict[str, tuple[str, str]]:
    yaml_index = await hass.async_add_executor_job(_yaml_index, hass)
    yaml_index.update(_entity_index(hass))
    yaml_index.update(await _dashboard_index(hass, force=force))
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


async def _session_title(hass: HomeAssistant, session_id: str) -> str:
    store = (hass.data.get(DOMAIN) or {}).get("store")
    if store is None or not str(session_id or "").strip():
        return ""
    return str(await hass.async_add_executor_job(store.session_title, session_id) or "")


def _read_yaml(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    return load_yaml(path)


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


async def _restore_config_item(
    hass: HomeAssistant, kind: str, document: dict[str, Any], authorization: str
) -> None:
    """Save the earlier version through Home Assistant's own config API.

    That is the same call the automation, script, and scene editors make: Home Assistant
    validates the item, writes its own file, and reloads it. AI Workspace never writes
    automations.yaml, scripts.yaml, or scenes.yaml itself.
    """
    item_id = str(document.get("id") or "")
    item = document.get("item")
    if not item_id or not isinstance(item, dict):
        raise ActivityError("The saved document is incomplete.")
    if not str(authorization or "").strip():
        raise ActivityError("Sign in again, then roll back this change.")
    body = {key: value for key, value in item.items() if key != "id"} if kind == "script" else dict(item)
    if kind != "script":
        body["id"] = item_id
    status, message = await _post_config(hass, kind, item_id, body, authorization)
    if status in (401, 403):
        raise ActivityError("Only an administrator can roll back automations, scripts, and scenes.")
    if status != 200:
        detail = f": {message}" if message else ""
        raise ActivityError(f"Home Assistant did not accept the saved {kind}{detail}")


async def _post_config(
    hass: HomeAssistant, kind: str, item_id: str, body: dict[str, Any], authorization: str
) -> tuple[int, str]:
    from urllib.parse import quote

    from aiohttp import ClientError

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    path = f"/api/config/{kind}/config/{quote(item_id, safe='')}"
    headers = {"Authorization": authorization, "Content-Type": "application/json"}
    last_error = "Home Assistant's config API could not be reached."
    for base, verify in _own_api_bases(hass):
        try:
            session = async_get_clientsession(hass, verify_ssl=verify)
            async with session.post(f"{base}{path}", json=body, headers=headers, timeout=30) as resp:
                try:
                    data = await resp.json(content_type=None)
                except (ValueError, ClientError):
                    data = None
                message = str(data.get("message") or "") if isinstance(data, dict) else ""
                return resp.status, message[:300]
        except (ClientError, TimeoutError, OSError) as exc:
            last_error = str(exc) or last_error
            continue
    raise ActivityError(last_error)


def _own_api_bases(hass: HomeAssistant) -> list[tuple[str, bool]]:
    """This Home Assistant's own API: loopback first, then its internal URL."""
    api = getattr(hass.config, "api", None)
    port = int(getattr(api, "port", None) or 8123)
    tls = bool(getattr(api, "use_ssl", False))
    bases: list[tuple[str, bool]] = []
    try:
        from homeassistant.helpers.network import NoURLAvailableError, get_url

        internal = str(get_url(hass, allow_internal=True, allow_external=False, allow_ip=True)).rstrip("/")
    except (ImportError, NoURLAvailableError):
        internal = ""
    if tls:
        if internal:
            bases.append((internal, True))
        # The certificate cannot name 127.0.0.1; this is our own process.
        bases.append((f"https://127.0.0.1:{port}", False))
    else:
        bases.append((f"http://127.0.0.1:{port}", True))
        if internal:
            bases.append((internal, True))
    return bases


class _WsError(Exception):
    """Home Assistant answered a websocket command with an error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message or code)
        self.code = code


async def _own_ws(hass: HomeAssistant, authorization: str, commands: list[dict[str, Any]]) -> list[Any]:
    """Run commands on this Home Assistant's own websocket API, signed in as the given user.

    The same commands the helper and dashboard editors send, so Home Assistant checks the
    user's permissions, validates the item, stores it and reloads it.
    """
    from aiohttp import ClientError, WSMsgType

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    scheme, _, token = str(authorization or "").partition(" ")
    token = token.strip() if scheme.lower() == "bearer" else ""
    if not token:
        raise ActivityError("Sign in again, then roll back this change.")
    last_error = "Home Assistant's websocket API could not be reached."
    for base, verify in _own_api_bases(hass):
        url = "ws" + base[len("http"):] + "/api/websocket"
        try:
            session = async_get_clientsession(hass, verify_ssl=verify)
            async with session.ws_connect(url, timeout=30, heartbeat=25) as ws:
                hello = await ws.receive_json(timeout=10)
                if hello.get("type") != "auth_required":
                    raise ActivityError("Home Assistant's websocket API did not ask for a login.")
                await ws.send_json({"type": "auth", "access_token": token})
                auth = await ws.receive_json(timeout=10)
                if auth.get("type") != "auth_ok":
                    raise ActivityError("Sign in again, then roll back this change.")
                results: list[Any] = []
                for number, command in enumerate(commands, start=1):
                    await ws.send_json({**command, "id": number})
                    while True:
                        msg = await ws.receive(timeout=30)
                        if msg.type != WSMsgType.TEXT:
                            raise ActivityError("Home Assistant closed the websocket.")
                        data = json.loads(msg.data)
                        if data.get("id") == number and data.get("type") == "result":
                            break
                    if not data.get("success"):
                        error = data.get("error") or {}
                        raise _WsError(str(error.get("code") or ""), str(error.get("message") or "")[:300])
                    results.append(data.get("result"))
                return results
        except (ClientError, TimeoutError, OSError) as exc:
            last_error = str(exc) or last_error
            continue
    raise ActivityError(last_error)


async def _ws_one(hass: HomeAssistant, authorization: str, command: dict[str, Any]) -> Any:
    try:
        return (await _own_ws(hass, authorization, [command]))[0]
    except _WsError as exc:
        if exc.code == "unauthorized":
            raise ActivityError("Only an administrator can roll back this change.") from exc
        raise ActivityError(str(exc)) from exc


def _helper_ids(change: Change) -> tuple[str, str]:
    domain = change.domain
    item_id = change.item_id
    if "." in item_id:
        prefix, rest = item_id.split(".", 1)
        if not domain:
            domain = prefix
        item_id = rest
    return domain, item_id


async def _helper_items(hass: HomeAssistant, domain: str, authorization: str) -> list[dict[str, Any]]:
    result = await _ws_one(hass, authorization, {"type": f"{domain}/list"})
    return [item for item in (result or []) if isinstance(item, dict)]


async def _snapshot_helper(hass: HomeAssistant, change: Change, authorization: str = "") -> dict[str, Any] | None:
    """The helper's stored settings, read through its own websocket list command.

    Without the user's login (or as a non-admin) there is no snapshot; the row then offers
    Undo with agent instead of Rollback.
    """
    domain, item_id = _helper_ids(change)
    if not domain or not item_id or not authorization:
        return None
    try:
        items = await _helper_items(hass, domain, authorization)
    except ActivityError as exc:
        logger.debug("helper snapshot skipped for %s.%s: %s", domain, item_id, exc)
        return None
    item = next((row for row in items if str(row.get("id") or "") == item_id), None)
    if item is None:
        return None
    label = str(item.get("name") or item.get("alias") or item_id)
    return {"kind": "helper", "domain": domain, "id": item_id, "label": label, "item": freeze_mapping(item)}


async def _restore_helper(hass: HomeAssistant, document: dict[str, Any], authorization: str) -> None:
    """Put the helper back with the same {domain}/update or /create command its editor sends."""
    domain = str(document.get("domain") or "")
    item_id = str(document.get("id") or "")
    item = document.get("item")
    if not domain or not item_id or not isinstance(item, dict):
        raise ActivityError("The saved helper is incomplete.")
    payload = {key: value for key, value in item.items() if key != "id"}
    items = await _helper_items(hass, domain, authorization)
    if any(str(row.get("id") or "") == item_id for row in items):
        await _ws_one(hass, authorization, {"type": f"{domain}/update", f"{domain}_id": item_id, **payload})
        return
    created = await _ws_one(hass, authorization, {"type": f"{domain}/create", **payload})
    if isinstance(created, dict) and created.get("id") not in {None, item_id}:
        logger.info("helper restore created %s as %s", item_id, created.get("id"))


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


def _board_store_key(key: object) -> str:
    if key in (None, "", "default"):
        return "lovelace"
    return str(key)


def _dashboards(hass: HomeAssistant) -> dict:
    lovelace = hass.data.get("lovelace")
    boards = getattr(lovelace, "dashboards", None)
    return boards if isinstance(boards, dict) else {}


def _iter_dashboards(hass: HomeAssistant):
    """Yield (dict_key, board), skipping the implicit default when named lovelace exists."""
    boards = _dashboards(hass)
    skip_default = None in boards and "lovelace" in boards
    for key, board in boards.items():
        if skip_default and key is None:
            continue
        yield key, board


def _resolve_board(hass: HomeAssistant, item_id: str) -> tuple[str, Any]:
    boards = _dashboards(hass)
    store_id = dashboard_store_id(item_id)
    key = dashboard_board_key(item_id, boards)
    board = boards.get(key)
    if board is not None:
        return _board_store_key(key), board
    board = boards.get(store_id)
    if board is not None:
        return store_id, board
    for alt in (store_id.replace("-", "_"), store_id.replace("_", "-")):
        if alt in boards:
            return str(alt), boards[alt]
    return store_id, None


async def _load_board_config(board: Any, force: bool = False) -> dict[str, Any] | None:
    try:
        config = await board.async_load(force)
    except Exception:
        logger.debug("dashboard async_load skipped", exc_info=True)
        return None
    return config if isinstance(config, dict) else None


async def _snapshot_board(
    board: Any, stored_key: str, label: str = "", force: bool = False, url_path: object = ""
) -> dict[str, Any] | None:
    config = freeze_mapping(await _load_board_config(board, force=force))
    meta = freeze_mapping(getattr(board, "config", None) or {})
    title = str(meta.get("title") or label or stored_key or "Overview")
    path = None if url_path in (None, "", "default") else str(url_path)
    return {
        "kind": "dashboard",
        "id": stored_key,
        "url_path": path,
        "label": title,
        "config": config,
        "meta": meta,
    }


async def _snapshot_all_dashboards(hass: HomeAssistant, force: bool = False) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for key, board in _iter_dashboards(hass):
        stored = _board_store_key(key)
        doc = await _snapshot_board(board, stored, force=force, url_path=key)
        if doc:
            found[stored] = doc
    return found


async def _snapshot_dashboard(hass: HomeAssistant, change: Change, force: bool = False) -> dict[str, Any] | None:
    store_id, board = _resolve_board(hass, change.item_id)
    if board is None:
        return None
    key = dashboard_board_key(change.item_id, _dashboards(hass))
    return await _snapshot_board(board, store_id, change.label, force=force, url_path=key)


async def _dashboard_index(hass: HomeAssistant, force: bool = False) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for key, board in _iter_dashboards(hass):
        stored = _board_store_key(key)
        meta = dict(getattr(board, "config", None) or {})
        label = str(meta.get("title") or stored)
        config = await _load_board_config(board, force=force)
        body = config if isinstance(config, dict) else meta
        found.update(index_items("dashboard", [{"id": stored, "title": label, "config": body}], ("title",)))
    return found


async def _restore_dashboard(hass: HomeAssistant, document: dict[str, Any], authorization: str) -> None:
    """Save the earlier dashboard with lovelace/config/save, the dashboard editor's own command."""
    config = document.get("config")
    if not isinstance(config, dict):
        raise ActivityError("The saved dashboard is incomplete.")
    boards = _dashboards(hass)
    if "url_path" in document:
        store_id = _board_store_key(document.get("url_path"))
        board = boards.get(document.get("url_path"))
    else:
        store_id, board = _resolve_board(hass, str(document.get("id") or ""))
    url_path = None if store_id == "lovelace" else store_id
    if board is None:
        await _recreate_dashboard(hass, str(document.get("id") or store_id), document.get("meta") or {}, authorization)
    try:
        current = await _ws_one(hass, authorization, {"type": "lovelace/config", "url_path": url_path, "force": True})
    except ActivityError:
        current = None
    if isinstance(current, dict) and _same_body(current, config):
        logger.warning(
            "Change History rollback skipped: snapshot already matches live dashboard %s",
            document.get("id") or "",
        )
        raise ActivityError(
            "The saved snapshot already matches the live dashboard. Ask to restore and pick an HA-MCP backup from before this change."
        )
    await _ws_one(hass, authorization, {"type": "lovelace/config/save", "url_path": url_path, "config": config})


async def _recreate_dashboard(hass: HomeAssistant, url_path: str, meta: dict, authorization: str) -> None:
    """Add a deleted dashboard back with lovelace/dashboards/create, as the Dashboards page does."""
    payload: dict[str, Any] = {
        "type": "lovelace/dashboards/create",
        "url_path": url_path or "lovelace",
        "title": str(meta.get("title") or url_path or "Dashboard"),
        "icon": meta.get("icon") or "mdi:view-dashboard",
        "show_in_sidebar": bool(meta.get("show_in_sidebar", True)),
        "require_admin": bool(meta.get("require_admin", False)),
    }
    if url_path in {"lovelace", "map"}:
        payload["allow_single_word"] = True
    await _ws_one(hass, authorization, payload)


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
