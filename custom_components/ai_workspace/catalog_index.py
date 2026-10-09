"""Static config catalog fields built at refresh. Not live state."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_ENTITY_RE = re.compile(r"\b[a-z][a-z0-9_]+\.[a-zA-Z0-9_]+\b")
_ACTOR_DOMAINS = {
    "switch",
    "light",
    "valve",
    "cover",
    "fan",
    "lock",
    "input_boolean",
    "input_button",
    "climate",
    "humidifier",
    "water_heater",
    "siren",
    "media_player",
    "script",
    "scene",
    "button",
    "number",
    "input_number",
    "select",
    "input_select",
}
TRIGGER_KEYS = ("trigger", "triggers")
CONDITION_KEYS = ("condition", "conditions")
ACTION_KEYS = ("action", "actions")


def as_list(value: Any) -> list[Any]:
    if value is None or value is False:
        return []
    if isinstance(value, list):
        return value
    return [value]


def uniq(items: list[str], limit: int = 16) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def entity_ids_in(text: str) -> list[str]:
    return uniq(_ENTITY_RE.findall(str(text or "")))


def _trigger_kind(item: dict[str, Any]) -> str:
    return str(item.get("trigger") or item.get("platform") or item.get("type") or "").strip()


def _short_at(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_short_at(item) for item in value[:3] if item not in (None, ""))
    text = str(value or "").strip()
    if len(text) >= 8 and text[2] == ":":
        return text[:5]
    return text[:24]


def summarize_triggers(config: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in TRIGGER_KEYS:
        for item in as_list(config.get(key)):
            if not isinstance(item, dict):
                continue
            kind = _trigger_kind(item)
            if kind == "time":
                at = _short_at(item.get("at"))
                parts.append(f"time {at}".strip())
            elif kind == "sun":
                parts.append(f"sun {item.get('event') or ''}".strip())
            elif kind in {"state", "numeric_state"}:
                eid = item.get("entity_id")
                if isinstance(eid, list):
                    eid = eid[0] if eid else ""
                parts.append(f"{kind} {eid or ''}".strip())
            elif kind == "homeassistant":
                parts.append(f"homeassistant {item.get('event') or ''}".strip())
            elif kind == "calendar":
                parts.append(f"calendar {item.get('entity_id') or ''}".strip())
            elif kind == "webhook":
                parts.append("webhook")
            elif kind == "mqtt":
                parts.append("mqtt")
            elif kind == "event":
                parts.append(f"event {item.get('event_type') or ''}".strip())
            elif kind:
                parts.append(kind)
            if len(parts) >= 4:
                break
        if parts:
            break
    return "; ".join(part for part in parts if part)[:120]


def _walk(node: Any, into: set[str], *, templates: bool) -> None:
    if node is None:
        return
    if isinstance(node, str):
        if templates:
            into.update(entity_ids_in(node))
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, into, templates=templates)
        return
    if not isinstance(node, dict):
        return
    for key in ("entity_id", "entity_ids"):
        for item in as_list(node.get(key)):
            if isinstance(item, str) and "." in item:
                into.add(item.strip())
    target = node.get("target")
    if isinstance(target, dict):
        _walk(target, into, templates=templates)
    for key, value in node.items():
        if key in {"entity_id", "entity_ids", "target"}:
            continue
        _walk(value, into, templates=templates)


def harvest_ids(config: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    found: set[str] = set()
    for key in keys:
        _walk(config.get(key), found, templates=True)
    return uniq(sorted(found))


def harvest_device_ids(config: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for item in as_list(node.get("device_id")):
                if isinstance(item, str) and item.strip():
                    found.add(item.strip())
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    for key in keys:
        walk(config.get(key))
    return uniq(sorted(found))


def acts_on(config: dict[str, Any]) -> list[str]:
    ids = harvest_ids(config, ACTION_KEYS)
    return uniq(
        [
            item
            for item in ids
            if item.split(".", 1)[0] in _ACTOR_DOMAINS or item.split(".", 1)[0] not in {"sensor", "binary_sensor", "zone"}
        ]
    )


def depends_on(config: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for keys in (TRIGGER_KEYS, CONDITION_KEYS):
        found.update(harvest_ids(config, keys))
    return uniq(sorted(found))


def related_config_ids(automations: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group automations that share actors or a name stem. Keys are config_id."""
    by_actor: dict[str, set[str]] = defaultdict(set)
    by_id: dict[str, dict[str, Any]] = {}
    for item in automations:
        cid = str(item.get("config_id") or "").strip()
        if not cid:
            continue
        by_id[cid] = item
        for entity_id in item.get("acts_on") or []:
            by_actor[str(entity_id)].add(cid)
    related: dict[str, set[str]] = defaultdict(set)
    for group in by_actor.values():
        if len(group) < 2:
            continue
        for cid in group:
            related[cid].update(other for other in group if other != cid)
    names = [(cid, str(item.get("name") or "").casefold()) for cid, item in by_id.items()]
    for cid, name in names:
        if len(name) < 8:
            continue
        for other_id, other_name in names:
            if other_id == cid or not other_name:
                continue
            if name in other_name or other_name in name:
                related[cid].add(other_id)
    return {cid: uniq(sorted(ids), 12) for cid, ids in related.items() if ids}


def extra_payload(
    *,
    entity_id: str = "",
    config_id: str = "",
    path: str = "",
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    trigger_summary: str = "",
    acts_on_ids: list[str] | None = None,
    depends_on_ids: list[str] | None = None,
    related_ids: list[str] | None = None,
    area: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if entity_id:
        payload["entity_id"] = entity_id
    if config_id:
        payload["config_id"] = config_id
    if path:
        payload["path"] = path
    if aliases:
        payload["aliases"] = uniq(aliases, 8)
    if tags:
        payload["tags"] = uniq(tags, 8)
    if trigger_summary:
        payload["trigger_summary"] = trigger_summary
    if acts_on_ids:
        payload["acts_on"] = uniq(acts_on_ids)
    if depends_on_ids:
        payload["depends_on"] = uniq(depends_on_ids)
    if related_ids:
        payload["related_config_ids"] = uniq(related_ids, 12)
    if area:
        payload["area"] = area
    return payload
