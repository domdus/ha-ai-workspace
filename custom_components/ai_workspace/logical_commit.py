"""Bundle config writes from one agent turn into a single Change History row."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGICAL_KIND = "logical_commit"
_ORPHAN_FLUSH_DELAY = 2.5
logger = logging.getLogger(__name__)


@dataclass
class ActivityFragment:
    summary: str
    tool: str
    document: dict[str, Any] | None


@dataclass
class LogicalCommit:
    commit_id: str
    user_id: str
    user_name: str
    agent: str
    session_id: str
    chat: str
    fragments: list[ActivityFragment] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    unsubs: list = field(default_factory=list)
    dashboard_docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    orphan: bool = False
    flush_unsub: Any = None


def _bucket(hass: HomeAssistant) -> dict[tuple[str, str], LogicalCommit]:
    store = hass.data.setdefault(DOMAIN, {})
    pending = store.get("logical_commits")
    if not isinstance(pending, dict):
        pending = {}
        store["logical_commits"] = pending
    return pending


def _key(user_id: str, session_id: str) -> tuple[str, str]:
    return (str(user_id or "").strip(), str(session_id or "").strip())


def turn_bucket(hass: HomeAssistant, user_id: str, session_id: str) -> LogicalCommit | None:
    return _bucket(hass).get(_key(user_id, session_id))


def _cancel_flush(row: LogicalCommit | None) -> None:
    if row is None:
        return
    unsub = row.flush_unsub
    row.flush_unsub = None
    if unsub is None:
        return
    try:
        unsub()
    except Exception:
        logger.debug("logical commit flush cancel failed", exc_info=True)


def _release_turn(row: LogicalCommit | None) -> None:
    if row is None:
        return
    _cancel_flush(row)
    for unsub in row.unsubs:
        try:
            unsub()
        except Exception:
            logger.debug("logical commit listener unsubscribe failed", exc_info=True)
    row.unsubs.clear()


def begin_logical_commit(
    hass: HomeAssistant,
    user_id: str,
    user_name: str,
    agent: str,
    session_id: str,
    chat: str = "",
    *,
    orphan: bool = False,
) -> str:
    key = _key(user_id, session_id)
    _release_turn(_bucket(hass).pop(key, None))
    commit_id = uuid.uuid4().hex
    _bucket(hass)[key] = LogicalCommit(
        commit_id=commit_id,
        user_id=key[0],
        user_name=str(user_name or user_id or "").strip(),
        agent=str(agent or "Agent").strip() or "Agent",
        session_id=key[1],
        chat=str(chat or "").strip()[:80],
        orphan=orphan,
    )
    return commit_id


def active_commit_id(hass: HomeAssistant, user_id: str, session_id: str) -> str:
    row = turn_bucket(hass, user_id, session_id)
    return str(row.commit_id) if row else ""


def _schedule_orphan_flush(hass: HomeAssistant, user_id: str, session_id: str) -> None:
    row = turn_bucket(hass, user_id, session_id)
    if row is None or not row.orphan:
        return
    _cancel_flush(row)
    delay = getattr(hass, "async_call_later", None)
    if not callable(delay):
        return

    async def _run(_now=None) -> None:
        store = (hass.data.get(DOMAIN) or {}).get("store")
        if store is None:
            return
        await flush_logical_commit(hass, store, user_id, session_id)

    row.flush_unsub = delay(_ORPHAN_FLUSH_DELAY, _run)


def queue_activity_fragment(
    hass: HomeAssistant,
    *,
    user_id: str,
    user_name: str,
    agent: str,
    session_id: str,
    chat: str,
    summary: str,
    tool: str,
    document: dict[str, Any] | None,
) -> bool:
    key = _key(user_id, session_id)
    bucket = _bucket(hass).get(key)
    if bucket is None:
        begin_logical_commit(
            hass,
            user_id,
            user_name,
            agent,
            session_id,
            chat,
            orphan=True,
        )
        bucket = _bucket(hass).get(key)
        if bucket is None:
            return False
    if agent and bucket.agent in {"", "Agent"}:
        bucket.agent = str(agent).strip() or bucket.agent
    if chat and not bucket.chat:
        bucket.chat = str(chat).strip()[:80]
    bucket.fragments.append(
        ActivityFragment(
            summary=str(summary or "").strip(),
            tool=str(tool or "").strip()[:120],
            document=document if isinstance(document, dict) else None,
        )
    )
    if bucket.orphan:
        _schedule_orphan_flush(hass, user_id, session_id)
    return True


def merge_logical_document(fragments: list[ActivityFragment]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    for item in fragments:
        entry: dict[str, Any] = {"summary": item.summary, "tool": item.tool}
        if isinstance(item.document, dict):
            entry["document"] = item.document
        changes.append(entry)
    return {
        "kind": _LOGICAL_KIND,
        "logical_commit": True,
        "change_count": len(changes),
        "changes": changes,
    }


def merge_logical_summary(fragments: list[ActivityFragment]) -> str:
    lines = [item.summary for item in fragments if item.summary]
    if not lines:
        return "Configuration changes"
    if len(lines) == 1:
        return lines[0][:240]
    head = "; ".join(lines[:3])
    if len(lines) > 3:
        return f"{len(lines)} changes: {head[:200]}…"
    return head[:240]


def merge_logical_tools(fragments: list[ActivityFragment]) -> str:
    names: list[str] = []
    for item in fragments:
        name = str(item.tool or "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        return "logical_commit"
    if len(names) == 1:
        return names[0][:120]
    return f"logical_commit ({len(names)} tools)"


def parse_logical_document(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("kind") == _LOGICAL_KIND or doc.get("logical_commit"):
        return doc
    return None


def _target_from_document(doc: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(doc.get("kind") or "").strip()
    item_id = str(doc.get("entity_id") or doc.get("id") or "").strip()
    label = str(doc.get("label") or doc.get("name") or "").strip()
    return kind, item_id, label


def documents_to_restore(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Nested snapshots inside a logical commit, or the single document."""
    if not isinstance(document, dict):
        return []
    if document.get("kind") == _LOGICAL_KIND or document.get("logical_commit"):
        out: list[dict[str, Any]] = []
        for change in document.get("changes") or []:
            nested = change.get("document") if isinstance(change, dict) else None
            if isinstance(nested, dict):
                out.append(nested)
        return out
    return [document]


def restore_targets(document: str) -> list[tuple[str, str, str]]:
    doc = parse_logical_document(document)
    if doc is None:
        try:
            parsed = json.loads(document)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            kind, item_id, label = _target_from_document(parsed)
            return [(kind, item_id, label)] if kind or item_id or label else []
        return []

    out: list[tuple[str, str, str]] = []
    for change in doc.get("changes") or []:
        if not isinstance(change, dict):
            continue
        nested = change.get("document")
        if isinstance(nested, dict):
            kind, item_id, label = _target_from_document(nested)
            if not label:
                label = str(change.get("summary") or "").strip()
        else:
            kind = item_id = ""
            label = str(change.get("summary") or "").strip()
        if kind or item_id or label:
            out.append((kind, item_id, label))
    return out


async def flush_logical_commit(hass: HomeAssistant, store, user_id: str, session_id: str) -> None:
    from .activity_ha import _write_change_file, harvest_turn_changes, session_has_pending, unsub_turn

    key = _key(user_id, session_id)
    bucket = _bucket(hass).get(key)
    if bucket is None:
        return
    _cancel_flush(bucket)
    if not bucket.fragments:
        for _ in range(25):
            if bucket.fragments or not session_has_pending(hass, session_id):
                break
            await asyncio.sleep(0.1)
    if not bucket.fragments:
        await harvest_turn_changes(hass, bucket)
    unsub_turn(bucket)
    bucket = _bucket(hass).pop(key, None)
    if bucket is None or not bucket.fragments:
        return

    fragments = bucket.fragments
    if len(fragments) == 1:
        frag = fragments[0]
        document = frag.document
        document_str = json.dumps(document, ensure_ascii=False, default=str) if document else ""
        row = await hass.async_add_executor_job(
            store.add_activity,
            bucket.user_id,
            bucket.user_name,
            bucket.agent,
            frag.summary,
            frag.tool,
            document_str,
            bucket.session_id,
            bucket.chat,
        )
        if isinstance(document, dict) and document.get("kind") in {"automation", "script", "scene"}:
            await hass.async_add_executor_job(_write_change_file, store, row, document)
        return

    merged = merge_logical_document(fragments)
    summary = merge_logical_summary(fragments)
    tool = merge_logical_tools(fragments)
    row = await hass.async_add_executor_job(
        store.add_activity,
        bucket.user_id,
        bucket.user_name,
        bucket.agent,
        summary,
        tool,
        json.dumps(merged, ensure_ascii=False, default=str),
        bucket.session_id,
        bucket.chat,
    )
    for frag in fragments:
        doc = frag.document
        if isinstance(doc, dict) and doc.get("kind") in {"automation", "script", "scene"}:
            await hass.async_add_executor_job(_write_change_file, store, row, doc)
