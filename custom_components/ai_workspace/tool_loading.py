"""Send cloud agents a starter set of MCP tools and let them load the rest on demand.

All HA-MCP tools come to about 38k tokens per model round. Most requests need a handful.
Tools are grouped by the category tags the MCP server sends (HA-MCP: _meta.fastmcp.tags).
Tools without tags are always sent, so other MCP servers behave as before.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

LOAD_TOOLS = "load_tools"
# Fewer tools than this: send them all.
MIN_TOOLS = 30
CORE_TAGS = frozenset({"Search & Discovery", "Service & Device Control"})
_CORE_NAMES = ("ha_get_skill_guide",)
_HISTORY_TAG = "History & Statistics"
# (pattern over the user's message, tags to load). German and English.
_TOPICS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), tags)
    for pattern, tags in (
        (r"automati|trigger|auslös", ("Automations", _HISTORY_TAG)),
        (r"dashboard|lovelace|\bkarten?\b|\bcards?\b|ansicht|\bviews?\b|kachel|\btiles?\b", ("Dashboards",)),
        (r"skript|script", ("Scripts",)),
        (r"szene|scene", ("Scenes",)),
        (r"helfer|helper|input_|\btimer|zähler|counter|zeitplan|schedule|toggle", ("Helper Entities",)),
        (r"bereich|\braum|räume|zimmer|\bareas?\b|etage|stockwerk|\bfloors?\b", ("Areas & Floors",)),
        (r"gerät|device", ("Device Registry",)),
        (r"entit|umbenenn|rename|\bicon|alias|deaktivier|disable", ("Entity Registry",)),
        (r"verlauf|histor|statisti|gestern|yesterday|\blogs?\b|fehler|error|warum|\bwhy\b|trace|failed|\bran\b|lief", (_HISTORY_TAG,)),
        (r"kalender|calendar|termin", ("Calendar",)),
        (r"todo|to-do|einkauf|shopping|aufgabe", ("Todo Lists",)),
        (r"label|kategor|categor", ("Labels & Categories",)),
        (r"gruppe|group", ("Groups",)),
        (r"\bzonen?\b", ("Zones",)),
        (r"energie|energy|solar|\bstrom", ("Energy",)),
        (r"kamera|camera|snapshot", ("Camera",)),
        (r"backup|sicherung", ("System",)),
        (r"neustart|restart|reload|neu laden|\bupdates?\b|aktualisier|theme|system", ("System",)),
        (r"integration|add-?on|\bapps?\b|hacs", ("Integrations", "Apps (add-ons)", "HACS")),
        (r"assist|pipeline|sprachassist", ("Assist",)),
        (r"blueprint|vorlage", ("Blueprints",)),
        (r"zigbee|z-?wave|matter|thread", ("Zigbee", "Z-Wave", "Matter", "Thread", "Radio Management")),
        (r"template|vorlage", ("Utilities",)),
    )
)


def tool_tags(tool: dict) -> tuple[str, ...]:
    meta = tool.get("_meta") if isinstance(tool.get("_meta"), dict) else {}
    fast = meta.get("fastmcp") if isinstance(meta.get("fastmcp"), dict) else {}
    tags = fast.get("tags") if isinstance(fast, dict) else None
    if not isinstance(tags, list):
        return ()
    return tuple(str(tag) for tag in tags if str(tag).strip())


def wanted_tags(text: str) -> set[str]:
    found: set[str] = set()
    for pattern, tags in _TOPICS:
        if pattern.search(text or ""):
            found.update(tags)
    return found


class ToolPicker:
    """Which tools a cloud agent sees this turn. Loaded tools are appended, so earlier ones stay a stable prefix."""

    def __init__(self, tools: list[dict], message: str = "", used: Iterable[str] = ()) -> None:
        self.all = list(tools)
        self._by_name = {str(tool.get("name") or ""): tool for tool in self.all}
        used_names = {str(name) for name in used}
        tags = set(CORE_TAGS) | wanted_tags(message)
        # A chat that already read a dashboard will likely write one next.
        for name in used_names:
            tags.update(tool_tags(self._by_name.get(name) or {}))
        lowered = (message or "").casefold()
        start: list[str] = []
        for tool in self.all:
            name = str(tool.get("name") or "")
            own = tool_tags(tool)
            if (
                not own
                or set(own) & tags
                or name in _CORE_NAMES
                or name in used_names
                or (len(name) > 6 and name.casefold() in lowered)
            ):
                start.append(name)
        self._order = start
        self.loaded: list[str] = []

    @property
    def active(self) -> bool:
        return len(self._order) < len(self.all)

    def visible(self) -> list[dict]:
        tools = [self._by_name[name] for name in self._order if name in self._by_name]
        if self.active:
            tools.append(self._load_tool())
        return tools

    def shows(self, name: str) -> bool:
        return name in self._order

    def knows(self, name: str) -> bool:
        return name in self._by_name

    def add(self, name: str) -> bool:
        if name in self._by_name and name not in self._order:
            self._order.append(name)
            self.loaded.append(name)
            return True
        return False

    def load(self, args: Any) -> str:
        """Run load_tools. Accepts tool names and group names."""
        raw = args.get("names") if isinstance(args, dict) else None
        if isinstance(raw, str):
            raw = [raw]
        asked = [str(item).strip() for item in (raw or []) if str(item).strip()]
        added: list[str] = []
        unknown: list[str] = []
        for item in asked:
            hits = self._resolve(item)
            if not hits:
                unknown.append(item)
            for name in hits:
                if self.add(name):
                    added.append(name)
        parts = []
        if added:
            parts.append(f"Loaded: {', '.join(added)}. You can call them now.")
        elif asked and not unknown:
            parts.append("Those tools are already loaded. Call them now.")
        if unknown:
            parts.append(f"Unknown: {', '.join(unknown)}. Use names from the load_tools description.")
        return " ".join(parts) or "Pass names: a list of tool or group names from the load_tools description."

    def _resolve(self, item: str) -> list[str]:
        key = item.casefold()
        for name in self._by_name:
            if name.casefold() == key:
                return [name]
        return [name for name, tool in self._by_name.items() if key in {tag.casefold() for tag in tool_tags(tool)}]

    def _load_tool(self) -> dict:
        groups: dict[str, list[str]] = {}
        for tool in self.all:
            name = str(tool.get("name") or "")
            if name in self._order:
                continue
            group = (tool_tags(tool) or ("Other",))[0]
            groups.setdefault(group, []).append(name)
        lines = [f"- {group}: {', '.join(names)}" for group, names in groups.items()]
        description = (
            "Only some Home Assistant tools are loaded right now. Before you use a tool that is not loaded, "
            "call this with its name or its group name; it is ready in your next step. "
            "Do not tell the user about loading tools. Tools you can load:\n" + "\n".join(lines)
        )
        return {
            "name": LOAD_TOOLS,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names or group names from the list.",
                    }
                },
                "required": ["names"],
            },
        }


def used_tool_names(rows) -> set[str]:
    """Tools this chat already used, so follow-up turns start with them."""
    import json

    names: set[str] = set()
    for row in rows or []:
        if str(getattr(row, "role", "") or "") != "assistant":
            continue
        try:
            events = json.loads(getattr(row, "events", None) or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in events if isinstance(events, list) else []:
            if isinstance(item, dict) and item.get("name") and item.get("name") != LOAD_TOOLS:
                names.add(str(item["name"]))
    return names


def pick_tools(tools: list[dict], message: str, used: Iterable[str] = ()) -> ToolPicker | None:
    if len(tools) < MIN_TOOLS:
        return None
    picker = ToolPicker(tools, message, used)
    return picker if picker.active else None
