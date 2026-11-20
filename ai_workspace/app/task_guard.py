"""Tool limits for agent task runs (``ai_workspace.run_task``).

A task runs unattended, usually from an automation. Two rules apply on every tool call:

* Loop protection, always: no ``ai_workspace.run_task`` (or anything else of AI Workspace),
  no ``automation.trigger``, and no tool that creates, edits or deletes automations or scripts.
* Read-only (``allow_changes`` off): only tools whose name says they read. Anything else,
  including every service call, is refused. Unknown tools count as writes.

The same file ships in the runtime (``ai_workspace/app/task_guard.py``) for Claude, Cursor and
Codex agents, whose tool calls go through the runtime's MCP proxy. Keep both copies identical;
a test checks it.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Words in a tool name that only read.
_READ = {
    "get",
    "list",
    "search",
    "find",
    "read",
    "query",
    "overview",
    "logbook",
    "history",
    "fetch",
    "lookup",
    "describe",
    "show",
    "status",
    "state",
    "states",
    "info",
    "context",
    "datetime",
    "count",
    "statistics",
    "render",
    "eval",
    "inspect",
    "check",
    "validate",
    "guide",
    "chats",
}
# Words that change something. They win over a read word ("get_or_create").
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
    "rename",
    "reload",
    "restart",
    "backup",
    "restore",
    "install",
    "enable",
    "disable",
    "assign",
    "move",
    "import",
    "deploy",
    "run",
    "execute",
    "start",
    "stop",
    "cancel",
    "remember",
    "forget",
    "call",
    "turn",
    "toggle",
    "press",
    "notify",
    "lock",
    "unlock",
    "open",
    "close",
    "play",
    "pause",
    "broadcast",
    "send",
    "trigger",
    "fire",
    "job",
}
# Read-only tools whose names carry no read word, by exact (lower-case) name.
_READ_NAMES = {
    "getlivecontext",
    "getdatetime",
    "web_search",
    "websearch",
    "web_fetch",
    "webfetch",
    "list_chats",
    "read_chat",
    "ha_eval_template",
}
_LOOP_KINDS = {"automation", "automations", "script", "scripts", "blueprint", "blueprints"}
_LOOP_DOMAINS = {"ai_workspace"}
_LOOP_SERVICES = {"automation.trigger"}

LOOP_MESSAGE = (
    "AI Workspace refused {tool!r}: this is an agent task. A task must not start tasks, trigger automations, "
    "or create, edit or delete automations or scripts. Answer with what you found; the user can make the change."
)
READ_ONLY_MESSAGE = (
    "AI Workspace refused {tool!r}: this task is read-only (Allow changes is off). "
    "Only read the house. Say in your answer what you would change and why."
)


def tool_name(name: Any) -> str:
    raw = str(name or "").strip()
    for sep in ("__", "/"):
        if sep in raw:
            raw = raw.rsplit(sep, 1)[-1]
    return raw


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool_name(name))
    return {part for part in re.split(r"[^a-z0-9]+", spaced.lower()) if part}


def _args(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            found = json.loads(arguments)
        except ValueError:
            return {}
        return found if isinstance(found, dict) else {}
    return {}


def _services(arguments: dict[str, Any]) -> list[str]:
    """``domain.service`` names a service-call tool would run."""
    found: list[str] = []
    domain = str(arguments.get("domain") or "").strip().lower()
    for key in ("service", "action", "service_name"):
        value = str(arguments.get(key) or "").strip().lower()
        if not value:
            continue
        found.append(value if "." in value or not domain else f"{domain}.{value}")
    if domain and not found:
        found.append(f"{domain}.")
    return found


def loop_refusal(tool: Any, arguments: Any = None) -> bool:
    """True when this call could start a task again or change automations/scripts."""
    tokens = _tokens(tool)
    args = _args(arguments)
    for service in _services(args):
        if service.split(".", 1)[0] in _LOOP_DOMAINS or service in _LOOP_SERVICES:
            return True
    if "ai" in tokens and "workspace" in tokens and tokens & {"run", "task"}:
        return True
    if tokens & _LOOP_KINDS and tokens & _WRITE:
        return True
    return False


def is_read_tool(tool: Any) -> bool:
    raw = tool_name(tool).lower()
    if raw in _READ_NAMES:
        return True
    tokens = _tokens(tool)
    return bool(tokens & _READ) and not tokens & _WRITE


def task_refusal(tool: Any, arguments: Any, policy: dict[str, Any] | None) -> str:
    """The message for a refused call, or an empty string when the task may make it."""
    if not policy:
        return ""
    name = tool_name(tool)
    if loop_refusal(tool, arguments):
        return LOOP_MESSAGE.format(tool=name)
    if policy.get("read_only", True) and not is_read_tool(tool):
        return READ_ONLY_MESSAGE.format(tool=name)
    return ""


def task_tool_offered(tool: Any, policy: dict[str, Any] | None) -> bool:
    """Whether to show the tool to the model at all. Calls are still checked one by one."""
    if not policy:
        return True
    if loop_refusal(tool):
        return False
    return is_read_tool(tool) if policy.get("read_only", True) else True
