from __future__ import annotations

from typing import Any


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _tool_label(name: str) -> str:
    raw = str(name or "tool").strip() or "tool"
    if raw.lower() == "mcp":
        return "MCP"
    return raw


def map_sdk_message(message: Any) -> list[dict[str, str]]:
    kind = _get(message, "type")
    if kind == "assistant":
        content = _get(_get(message, "message"), "content") or []
        events: list[dict[str, str]] = []
        for block in content:
            block_type = _get(block, "type")
            if block_type == "text":
                text = _get(block, "text") or ""
                if text:
                    events.append({"type": "text", "delta": str(text)})
            elif block_type == "tool_use":
                name = str(_get(block, "name") or "tool")
                label = _tool_label(name)
                events.append(
                    {
                        "type": "tool",
                        "name": name,
                        "phase": "start",
                        "text": f"Calling {label}...",
                    }
                )
        return events
    if kind == "thinking":
        return [{"type": "status", "text": "Thinking..."}]
    if kind == "tool_call":
        name = str(_get(message, "name") or "tool")
        label = _tool_label(name)
        status = str(_get(message, "status") or "")
        if status == "completed":
            return [{"type": "tool", "name": name, "phase": "end", "text": f"Finished {label}"}]
        if status == "error":
            return [{"type": "tool", "name": name, "phase": "end", "text": f"{label} failed"}]
        return [{"type": "tool", "name": name, "phase": "start", "text": f"Calling {label}..."}]
    if kind == "status":
        text = str(_get(message, "message") or _get(message, "status") or "Working...")
        return [{"type": "status", "text": text[:160]}]
    return []
