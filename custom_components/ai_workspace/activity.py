"""Decide which MCP tool calls belong in the activity list.

Reads and entity-state calls stay out. Config writes for automations, scripts,
scenes, helpers, entities, and dashboards can be rolled back when a previous
document was saved. Dashboard and entity-registry events from Home Assistant
name the document that actually moved, so a wrong tool argument still records.
Any other write is only a line, and only if a config document actually changed.
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
_SKIP = {"reload", "backup"}
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


def dashboard_store_id(url_path: object) -> str:
    """Map a Lovelace url_path (including the default board) to the snapshot id."""
    raw = _text(url_path).strip("/")
    if raw.lower().startswith("lovelace/"):
        return "lovelace"
    if raw in {"", "lovelace", "default"}:
        return "lovelace"
    return raw


def dashboard_id_from_args(args: dict) -> str:
    # HA-MCP omits url_path or sends null for the default Lovelace board.
    if "url_path" in args:
        return dashboard_store_id(args.get("url_path"))
    found = _text(args.get("dashboard_id"))
    if found:
        return dashboard_store_id(found)
    path = _text(args.get("path"))
    # JSON Patch pointers look like /views/0/title — not a dashboard id.
    if not path or path.startswith("/") or path.startswith("views"):
        return ""
    return dashboard_store_id(path)


def dashboard_args(args: dict) -> bool:
    if dashboard_id_from_args(args):
        return True
    patch = args.get("patch")
    if isinstance(patch, list) and patch:
        return True
    config = args.get("config")
    return isinstance(config, dict) and ("views" in config or "sections" in config or "cards" in config)


def entity_ids_from_args(args: dict) -> list[str]:
    raw = args.get("entity_id")
    if isinstance(raw, list):
        return [found for item in raw if (found := _text(item))]
    found = _text(raw)
    return [found] if found else []


def yaml_kind_from_args(args: dict) -> str:
    """Automation, script, or scene from arguments when the tool name lost those words."""
    if dashboard_args(args):
        return ""
    if _text(args.get("automation_id")):
        return "automation"
    if _text(args.get("script_id")):
        return "script"
    if _text(args.get("scene_id")):
        return "scene"
    ident = _from_args(args, "identifier", "entity_id", "id")
    for prefix, kind in (("automation.", "automation"), ("script.", "script"), ("scene.", "scene")):
        if ident.startswith(prefix):
            return kind
    return ""


def looks_like_config_write(name: str, arguments: dict | None) -> bool:
    """True when the call should be watched even if the tool name is hashed or generic."""
    if classify(name, arguments) is not None:
        return True
    if watches_config(name):
        return True
    tokens = _tokens(name)
    if not tokens or tokens & _READ or tokens & _STATE or tokens & _SKIP:
        return False
    args = arguments if isinstance(arguments, dict) else {}
    if yaml_kind_from_args(args):
        return True
    ident = _from_args(args, "identifier", "automation_id", "script_id", "scene_id")
    if ident and (args.get("python_transform") not in (None, "") or isinstance(args.get("config"), dict)):
        return True
    if args.get("python_transform") not in (None, ""):
        return True
    return dashboard_args(args) or bool(entity_ids_from_args(args))


def classify(name: str, arguments: dict | None) -> Change | None:
    """Return the config change this tool intends, or None when it is not one."""
    tokens = _tokens(name)
    if not tokens or tokens & _READ or tokens & _SKIP:
        return None
    kind = _kind(tokens)
    args = arguments if isinstance(arguments, dict) else {}
    if not kind and not (tokens & _STATE):
        if dashboard_args(args):
            kind = "dashboard"
        elif yaml_kind_from_args(args):
            kind = yaml_kind_from_args(args)
        elif entity_ids_from_args(args) and not (tokens & {"helper", "helpers"}):
            kind = "entity"
    if not kind:
        return None
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
        item_id = dashboard_id_from_args(args)
        domain = "lovelace"
    else:
        ids = entity_ids_from_args(args)
        item_id = ids[0] if ids else _from_args(args, "identifier", "id")
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


def changed_index_keys(
    before: dict[str, tuple[str, str]], after: dict[str, tuple[str, str]]
) -> list[str]:
    keys: list[str] = []
    for key, (_label, digest) in before.items():
        later = after.get(key)
        if later is None or later[1] != digest:
            keys.append(key)
    for key in after:
        if key not in before:
            keys.append(key)
    return keys


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
