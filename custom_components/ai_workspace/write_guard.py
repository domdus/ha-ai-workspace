"""Refuse placeholder automations, scripts and scenes that agents invent to get past a write check.

The same file ships in the runtime (``ai_workspace/app/write_guard.py``) for Cursor agents.
Keep both copies identical; a test checks it.
"""

from __future__ import annotations

import json
import re
from typing import Any

_GUARDED = re.compile(r"ha_config_set_(automation|script|scene)$")
# Names no user asks for: they describe the write check, not the house.
_ALWAYS = re.compile(r"bps|best_?practice|placeholder|no_?op|dummy|write_?guard|guard_?only|ack_?only")
# Ordinary words that only count when the item does nothing but log.
_WEAK = re.compile(r"(^|_)(guard|probe|ack|test|check)(_|$)")
_NAME_ARGS = ("identifier", "automation_id", "script_id", "scene_id", "entity_id", "alias", "name", "id")
_IDLE_ACTIONS = {"system_log.write", "logbook.log", "logger.log"}
_YAML_NAME = re.compile(r"^\s*-?\s*(alias|id)\s*:\s*(.+?)\s*$", re.MULTILINE)

BLOCK_MESSAGE = (
    "AI Workspace refused this write: {name!r} looks like a placeholder or helper the user did not ask for. "
    "Do not create helper, placeholder, guard, or test automations, scripts, or scenes. "
    "The BestPracticeKey goes into the write you actually need, and it is checked on each call. "
    "Continue with the user's request. If it cannot be done, tell the user what blocked it."
)


def _normal(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _config(arguments: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw = arguments.get("config")
    if isinstance(raw, dict):
        return raw, ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}, raw
        return (parsed, "") if isinstance(parsed, dict) else ({}, raw)
    return {}, ""


def _names(arguments: dict[str, Any], config: dict[str, Any], text: str) -> list[str]:
    found = [arguments.get(key) for key in _NAME_ARGS]
    found += [config.get(key) for key in ("alias", "id", "name")]
    found += [value for _key, value in _YAML_NAME.findall(text)]
    return [name for name in (_normal(item) for item in found if isinstance(item, (str, int))) if name]


def _idle(config: dict[str, Any], text: str) -> bool:
    """True when the item only logs, waits, or has nothing to do."""
    if text:
        return False
    if "entities" in config:
        return not config.get("entities")
    steps = config.get("actions", config.get("action", config.get("sequence")))
    if steps is None:
        return False
    steps = steps if isinstance(steps, list) else [steps]
    for step in steps:
        if not isinstance(step, dict):
            return False
        service = str(step.get("action") or step.get("service") or "")
        if service:
            if service not in _IDLE_ACTIONS:
                return False
        elif not set(step) <= {"delay", "stop", "alias"}:
            return False
    return True


def placeholder_write(tool: str, arguments: Any) -> str:
    """The offending name when this call writes a placeholder, else an empty string."""
    if not _GUARDED.search(str(tool or "")) or not isinstance(arguments, dict):
        return ""
    config, text = _config(arguments)
    names = _names(arguments, config, text)
    for name in names:
        if _ALWAYS.search(name):
            return name
    if _idle(config, text):
        for name in names:
            if _WEAK.search(name):
                return name
    return ""


def block_message(name: str) -> str:
    return BLOCK_MESSAGE.format(name=name)
