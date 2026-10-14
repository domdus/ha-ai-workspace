"""Decide which MCP tool calls belong in the activity list.

Reads and entity-state calls stay out. Config writes for automations, scripts,
scenes, helpers, entities, and dashboards can be rolled back when a previous
document was saved. Any other write is only a line, and only if a config
document actually changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

_READ = {"get", "list", "search", "find", "read", "query", "overview", "logbook", "history"}
_WRITE = {
    "set",
    "update",
    "remove",
    "delete",
    "create",
    "add",
    "patch",
    "put",
    "write",
    "save",
    "edit",
    "upsert",
    "modify",
    "replace",
    "transform",
}
_SKIP = {"reload"}
_DELETE = {"remove", "delete"}
_STATE = {"turn", "toggle", "press", "notify", "lock", "unlock", "play", "broadcast", "call"}
_KINDS = (
    ("automation", ("automation", "automations")),
    ("scene", ("scene", "scenes")),
    ("script", ("script", "scripts")),
    ("helper", ("helper", "helpers")),
    ("dashboard", ("dashboard", "lovelace")),
    ("entity", ("entity", "entities")),
)
_KIND_WORD = {
    "automation": "automation",
    "script": "script",
    "scene": "scene",
    "helper": "helper",
    "entity": "entity",
    "dashboard": "dashboard",
}
_ACTION_WORD = {"create": "Created", "update": "Updated", "delete": "Deleted"}


@dataclass(frozen=True)
class Change:
    kind: str
    action: str
    item_id: str
    label: str
    domain: str = ""


def tool_name(name: str) -> str:
    raw = str(name or "").strip().lower().replace("-", "_")
    for sep in ("__", "/"):
        if sep in raw:
            raw = raw.rsplit(sep, 1)[-1]
    return raw


def _tokens(name: str) -> set[str]:
    return {part for part in tool_name(name).split("_") if part}


def _kind(tokens: set[str]) -> str:
    if "resource" in tokens and ("dashboard" in tokens or "lovelace" in tokens):
        return ""
    for kind, words in _KINDS:
        if tokens & set(words):
            return kind
    return ""


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return ""


def _from_args(args: dict, *keys: str) -> str:
    for key in keys:
        found = _text(args.get(key))
        if found:
            return found
    config = args.get("config")
    if isinstance(config, dict):
        for key in keys:
            found = _text(config.get(key))
            if found:
                return found
    return ""


def _label(args: dict, item_id: str) -> str:
    config = args.get("config") if isinstance(args.get("config"), dict) else {}
    for source in (args, config):
        for key in ("alias", "name", "title"):
            found = _text(source.get(key))
            if found:
                return found
    return item_id


def classify(name: str, arguments: dict | None) -> Change | None:
    """Return the config change this tool intends, or None when it is not one."""
    tokens = _tokens(name)
    if not tokens or tokens & _READ or tokens & _SKIP:
        return None
    kind = _kind(tokens)
    if not kind:
        return None
    args = arguments if isinstance(arguments, dict) else {}
    if kind == "automation":
        item_id = _from_args(args, "identifier", "automation_id", "entity_id", "id")
        domain = "automation"
    elif kind == "script":
        item_id = _from_args(args, "identifier", "script_id", "entity_id", "id")
        domain = "script"
    elif kind == "scene":
        item_id = _from_args(args, "identifier", "scene_id", "entity_id", "id")
        domain = "scene"
    elif kind == "helper":
        item_id = _from_args(args, "helper_id", "entity_id", "identifier", "id")
        domain = _text(args.get("helper_type")) or _text(args.get("domain"))
        if not domain and "." in item_id:
            domain = item_id.split(".", 1)[0]
    elif kind == "dashboard":
        item_id = _from_args(args, "url_path", "dashboard_id", "identifier", "path")
        domain = "lovelace"
    else:
        item_id = _from_args(args, "entity_id", "identifier", "id")
        domain = item_id.split(".", 1)[0] if "." in item_id else ""
    action = "delete" if tokens & _DELETE else ("update" if item_id else "create")
    return Change(kind=kind, action=action, item_id=item_id, label=_label(args, item_id), domain=domain)


def watches_config(name: str) -> bool:
    """True for a write we cannot name, so the caller can see whether config moved."""
    tokens = _tokens(name)
    if not tokens or tokens & _READ or tokens & _STATE or tokens & _SKIP:
        return False
    if _kind(tokens):
        return False
    return bool(tokens & _WRITE)


def summary(change: Change, found_name: str = "") -> str:
    label = (found_name or change.label or change.item_id or _KIND_WORD[change.kind]).strip()
    return f"{_ACTION_WORD[change.action]} {_KIND_WORD[change.kind]} {label}".strip()


def describe_index(before: dict[str, tuple[str, str]], after: dict[str, tuple[str, str]]) -> str:
    """One plain line for documents that appeared, disappeared, or changed. Empty when nothing did."""
    lines: list[str] = []
    for key, (label, digest) in before.items():
        kind = key.split(":", 1)[0]
        word = _KIND_WORD.get(kind, kind)
        later = after.get(key)
        if later is None:
            lines.append(f"Deleted {word} {label}")
        elif later[1] != digest:
            lines.append(f"Updated {word} {later[0] or label}")
    for key, (label, _digest) in after.items():
        if key in before:
            continue
        kind = key.split(":", 1)[0]
        lines.append(f"Created {_KIND_WORD.get(kind, kind)} {label}")
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return f"{lines[0]} (+{len(lines) - 1})"


def tool_succeeded(result: object) -> bool:
    return not (isinstance(result, dict) and result.get("isError") is True)


def index_items(kind: str, items: object, label_keys: tuple[str, ...] = ("alias", "name", "title")) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    rows: list[tuple[str, object]] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                rows.append((str(item.get("id") or ""), item))
    elif isinstance(items, dict):
        for key, item in items.items():
            rows.append((str(key), item if isinstance(item, dict) else {"id": key}))
    for item_id, item in rows:
        if not item_id or not isinstance(item, dict):
            continue
        label = item_id
        for key in label_keys:
            found = _text(item.get(key))
            if found:
                label = found
                break
        digest = json.dumps(item, sort_keys=True, default=str, ensure_ascii=False)
        out[f"{kind}:{item_id}"] = (label, digest)
    return out
