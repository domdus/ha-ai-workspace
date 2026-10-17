"""Keep MCP tool results valid and small enough for a chat model.

A short result is returned unchanged. A long entity listing becomes an area
map of ids, or a state-only list when there are only a few entities. Other
long JSON drops whole items or whole fields. Strings inside JSON are never
sliced, so the model always receives a complete value.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

PASS = 6000
CEILING = 24000
UNCHANGED = "unchanged"
AREA_MAP = "area-map"
TRUNCATED = "truncated"
OFF = "off"
_ENTITY_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
_BULKY = {
    "attributes",
    "context",
    "last_changed",
    "last_updated",
    "last_reported",
    "options",
    "capabilities",
    "supported_features",
    "restored",
}
_AREA_NOTE = (
    "States and attributes were left out. Ask for one area or one entity id to load them."
)
_LIST_NOTE = "Further items were left out. Ask for a narrower list."
_TEXT_NOTE = "\n[Further text was left out. Ask for a narrower question.]"

logger = logging.getLogger(__name__)


def classify_shorten(before: str, after: str) -> str:
    if before == after:
        return UNCHANGED
    if _AREA_NOTE in after:
        return AREA_MAP
    return TRUNCATED


def shorten_tool_value(result: Any, *, enabled: bool = True) -> tuple[Any, str]:
    if not enabled:
        return result, OFF
    before = result if isinstance(result, str) else _dump(result)
    fitted = _shorten_value(result)
    after = fitted if isinstance(fitted, str) else _dump(fitted)
    return fitted, classify_shorten(before, after)


def shorten_tool_result(result: Any, *, enabled: bool = True) -> tuple[str, str]:
    fitted, kind = shorten_tool_value(result, enabled=enabled)
    text = fitted if isinstance(fitted, str) else _dump(fitted)
    logger.debug("mcp proxy tool result: %s", kind)
    return text, kind


def shorten_mcp_response(
    request_body: bytes, response_body: bytes, content_type: str, *, enabled: bool = True
) -> tuple[bytes, str]:
    if not enabled:
        return response_body, OFF
    if _request_method(request_body) != "tools/call":
        return response_body, UNCHANGED
    if _is_sse(response_body, content_type):
        compacted = _compact_sse(response_body)
        return compacted, classify_shorten(
            response_body.decode("utf-8", "replace"), compacted.decode("utf-8", "replace")
        )
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return response_body, UNCHANGED
    if not isinstance(payload, dict) or "result" not in payload:
        return response_body, UNCHANGED
    before = _dump(payload["result"])
    fitted, kind = shorten_tool_value(payload["result"])
    payload["result"] = fitted
    return json.dumps(payload, ensure_ascii=False).encode(), kind or classify_shorten(
        before, fitted if isinstance(fitted, str) else _dump(fitted)
    )


def _shorten_value(result: Any) -> Any:
    if isinstance(result, str):
        stripped = result.strip()
        parsed = _try_json(stripped)
        if parsed is None:
            return _fit_plain(result)
        if len(stripped) <= PASS:
            return result
        return _fit(parsed)
    if len(_dump(result)) <= PASS:
        return result
    return _fit(result)


def _request_method(body: bytes) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("method") or "")
    return ""


def _is_sse(body: bytes, content_type: str) -> bool:
    if "text/event-stream" in (content_type or ""):
        return True
    head = body.lstrip()[:24]
    return head.startswith(b"event:") or head.startswith(b"data:")


def _compact_sse(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="replace")
    pieces = text.split("\n\n")
    rebuilt = []
    for piece in pieces:
        if not piece:
            rebuilt.append(piece)
            continue
        lines = []
        for line in piece.split("\n"):
            if line.startswith("data:"):
                lines.append("data: " + _compact_data(line[5:].strip()))
            else:
                lines.append(line)
        rebuilt.append("\n".join(lines))
    body = "\n\n".join(rebuilt)
    if text.endswith("\n\n") and not body.endswith("\n\n"):
        body += "\n\n"
    return body.encode("utf-8")


def _compact_data(text: str) -> str:
    if not text or text == "[DONE]":
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(payload, dict) or "result" not in payload:
        return text
    payload["result"] = _shorten_value(payload["result"])
    return json.dumps(payload, ensure_ascii=False)


def _fit(value: Any) -> Any:
    if isinstance(value, dict) and _is_envelope(value):
        out = dict(value)
        out["content"] = [_fit_block(block) for block in value["content"]]
        structured = out.get("structuredContent")
        if isinstance(structured, (dict, list)):
            out["structuredContent"] = _fit(structured)
        if len(_dump(out)) > CEILING:
            return _enforce(out)
        return out
    if isinstance(value, list):
        if _entity_list(value) and (len(value) >= 8 or len(_dump(value)) > PASS):
            return _fit_entities(value)
        return _fit_list(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        wide = len(_dump(value)) > PASS
        for key, item in value.items():
            if isinstance(item, list) and _entity_list(item) and (len(item) >= 8 or len(_dump(item)) > PASS):
                out[key] = _fit_entities(item)
            elif isinstance(item, (dict, list)) and len(_dump(item)) > PASS:
                out[key] = _fit(item)
            elif isinstance(item, str) and wide and len(item) > 1500:
                out[key] = f"[omitted {len(item)} characters]"
            else:
                out[key] = item
        if len(_dump(out)) > CEILING:
            return _enforce(out)
        return out
    if isinstance(value, str) and len(value) > CEILING:
        return _fit_plain(value)
    return value


def _is_envelope(value: dict) -> bool:
    content = value.get("content")
    return isinstance(content, list) and any(isinstance(block, dict) and "text" in block for block in content)


def _fit_block(block: Any) -> Any:
    if not isinstance(block, dict) or not isinstance(block.get("text"), str):
        return block
    text = block["text"]
    parsed = _try_json(text.strip())
    if parsed is None:
        if len(text) <= CEILING:
            return block
        copied = dict(block)
        copied["text"] = _fit_plain(text)
        return copied
    if len(text) <= PASS:
        return block
    copied = dict(block)
    fitted = _fit(parsed)
    copied["text"] = fitted if isinstance(fitted, str) else _dump(fitted)
    return copied


def _fit_entities(items: list) -> Any:
    projected = [_project_entity(item) if isinstance(item, dict) else item for item in items]
    if len(_dump(projected)) <= CEILING:
        return projected
    return _area_map(items)


def _area_map(items: list) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity_id = _entity_id(item)
        if not entity_id:
            continue
        area = _area_name(item)
        if area not in groups:
            groups[area] = []
            order.append(area)
        groups[area].append(entity_id)
    omitted = 0
    while len(_dump(_map_body(groups, order, omitted))) > CEILING:
        largest = max(order, key=lambda name: len(groups[name]), default="")
        if not largest or len(groups[largest]) <= 1:
            break
        groups[largest].pop()
        omitted += 1
    return _map_body(groups, order, omitted)


def _map_body(groups: dict[str, list[str]], order: list[str], omitted: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "areas": {area: groups[area] for area in order if groups[area]},
        "entities": sum(len(groups[area]) for area in order),
        "note": _AREA_NOTE,
    }
    if omitted:
        body["omitted"] = omitted
    return body


def _project_entity(item: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    entity_id = _entity_id(item)
    if entity_id:
        out["entity_id"] = entity_id
    for key in ("name", "friendly_name", "state", "area", "area_name", "domain", "device_class", "unit_of_measurement"):
        value = item.get(key)
        if isinstance(value, str) and value and len(value) <= 200:
            out[key] = value
        elif isinstance(value, (int, float, bool)):
            out[key] = value
    if "area" not in out and "area_name" not in out:
        area = _area_name(item)
        if area != "Unassigned":
            out["area"] = area
    return out or {"entity_id": entity_id}


def _fit_list(items: list) -> list:
    fitted = []
    for item in items:
        if isinstance(item, (dict, list)) and len(_dump(item)) > PASS:
            fitted.append(_fit(item))
        else:
            fitted.append(item)
    if len(_dump(fitted)) <= CEILING:
        return fitted
    projected = [_project_generic(item) if isinstance(item, dict) else item for item in fitted]
    return _prefix(projected)


def _prefix(items: list) -> list:
    if len(_dump(items)) <= CEILING:
        return items
    kept: list = []
    for index, item in enumerate(items):
        rest = len(items) - index
        if len(_dump(kept + [item])) > CEILING:
            if not kept and isinstance(item, (dict, list)):
                kept.append(_enforce(item))
                if index + 1 < len(items):
                    kept.append({"omitted": len(items) - index - 1, "note": _LIST_NOTE})
                return kept
            kept.append({"omitted": rest, "note": _LIST_NOTE})
            return kept
        kept.append(item)
    return kept


def _project_generic(item: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in item.items():
        if key in _BULKY:
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, str):
            out[key] = value if len(value) <= 400 else f"[omitted {len(value)} characters]"
        elif isinstance(value, list):
            if _entity_list(value):
                out[key] = _fit_entities(value)
            elif len(_dump(value)) <= 800:
                out[key] = value
            else:
                out[key] = {"count": len(value), "note": _LIST_NOTE}
        elif isinstance(value, dict) and len(_dump(value)) <= 400:
            out[key] = value
        if len(out) >= 16:
            break
    return out or {"note": _LIST_NOTE}


def _enforce(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _BULKY:
                if key == "attributes" and isinstance(item, dict):
                    slim = _slim_attributes(item)
                    if slim:
                        out[key] = slim
                continue
            if isinstance(item, str) and len(item) > 400:
                out[key] = f"[omitted {len(item)} characters]"
            elif isinstance(item, list):
                out[key] = _prefix([_enforce(entry) if isinstance(entry, (dict, list)) else entry for entry in item])
            elif isinstance(item, dict):
                out[key] = _enforce(item)
            else:
                out[key] = item
        return out
    if isinstance(value, list):
        return _prefix([_enforce(item) if isinstance(item, (dict, list)) else item for item in value])
    if isinstance(value, str) and len(value) > 400:
        return f"[omitted {len(value)} characters]"
    return value


def _slim_attributes(attrs: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, str) and len(value) <= 200:
            out[key] = value
        elif isinstance(value, list):
            out[key] = {"count": len(value)}
        elif isinstance(value, dict) and len(_dump(value)) <= 300:
            out[key] = value
        if len(out) >= 24:
            break
    return out


def _entity_list(items: list) -> bool:
    if not items:
        return False
    found = sum(1 for item in items if _entity_id(item))
    return found > 0 and found / len(items) >= 0.6


def _entity_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("entity_id", "entity"):
        value = item.get(key)
        if isinstance(value, str) and _ENTITY_ID.match(value):
            return value
    raw = item.get("id")
    if isinstance(raw, str) and _ENTITY_ID.match(raw) and "alias" not in item:
        return raw
    return ""


def _area_name(item: dict) -> str:
    for key in ("area_name", "area"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = value.get("name") or value.get("area_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    raw = item.get("area_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "Unassigned"


def _fit_plain(text: str) -> str:
    if len(text) <= CEILING:
        return text
    window = text[:CEILING]
    cut = window.rfind("\n")
    if cut < CEILING // 2:
        cut = window.rfind(" ")
    if cut < CEILING // 2:
        cut = CEILING
    return text[:cut].rstrip() + _TEXT_NOTE


def _try_json(text: str) -> Any | None:
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
