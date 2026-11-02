"""Keep large MCP listings small enough for a chat model, and leave everything else alone.

Only a live entity listing (items with entity_id and state) is condensed: to a
state-only list, or to an area map of ids when that is still too long. Guides,
dashboards, automations and any other result reach the model exactly as sent,
because it may need every field, or write the value back. A result past LIMIT
keeps its beginning and says plainly that it is incomplete.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

PASS = 6000
CEILING = 24000
LIMIT = 100000
UNCHANGED = "unchanged"
AREA_MAP = "area-map"
TRUNCATED = "truncated"
OFF = "off"
_ENTITY_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
_AREA_NOTE = (
    "States and attributes were left out. Ask for one area or one entity id to load them."
)
_CUT_NOTE = (
    "\n[Result cut: showing {shown} of {total} characters. It is incomplete, so do not "
    "write it back. Ask for a narrower result.]"
)

logger = logging.getLogger(__name__)


def classify_shorten(before: str, after: str) -> str:
    if before == after:
        return UNCHANGED
    return AREA_MAP if _AREA_NOTE in after else TRUNCATED


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
        parsed = _try_json(result.strip())
        if parsed is None or len(result) <= PASS:
            return result if len(result) <= LIMIT else _cut(result)
        fitted = _fit(parsed)
        if fitted == parsed:
            return result if len(result) <= LIMIT else _cut(result)
        return _cap(fitted)
    if len(_dump(result)) <= PASS:
        return result
    return _cap(_fit(result))


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
                data = line[5:].strip()
                compacted = _compact_data(data)
                lines.append(line if compacted == data else f"data: {compacted}")
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
    fitted = _shorten_value(payload["result"])
    if fitted == payload["result"]:
        return text
    payload["result"] = fitted
    return json.dumps(payload, ensure_ascii=False)


def _fit(value: Any) -> Any:
    """Condense entity listings at any depth. Everything else keeps its exact value."""
    if isinstance(value, dict) and _is_envelope(value):
        out = dict(value)
        out["content"] = [_fit_block(block) for block in value["content"]]
        if isinstance(out.get("structuredContent"), (dict, list)):
            out["structuredContent"] = _fit(out["structuredContent"])
        return out
    if isinstance(value, list):
        if _entity_list(value) and len(_dump(value)) > PASS:
            return _fit_entities(value)
        return [_fit(item) if isinstance(item, (dict, list)) else item for item in value]
    if isinstance(value, dict):
        return {key: _fit(item) if isinstance(item, (dict, list)) else item for key, item in value.items()}
    return value


def _is_envelope(value: dict) -> bool:
    content = value.get("content")
    return isinstance(content, list) and any(isinstance(block, dict) and "text" in block for block in content)


def _fit_block(block: Any) -> Any:
    if not isinstance(block, dict) or not isinstance(block.get("text"), str):
        return block
    text = block["text"]
    parsed = _try_json(text.strip())
    if parsed is None or len(text) <= PASS:
        return block
    fitted = _fit(parsed)
    if fitted == parsed:
        return block
    copied = dict(block)
    copied["text"] = _dump(fitted)
    return copied


def _cap(value: Any) -> Any:
    """Past LIMIT: keep the beginning as text. A missing end must not look like a whole result."""
    if len(_dump(value)) <= LIMIT:
        return value
    if isinstance(value, dict) and _is_envelope(value):
        out = {key: item for key, item in value.items() if key != "structuredContent"}
        out["content"] = [
            {**block, "text": _cut(block["text"])} if isinstance(block, dict) and isinstance(block.get("text"), str) else block
            for block in value["content"]
        ]
        return out
    return {"content": [{"type": "text", "text": _cut(_dump(value))}]}


def _cut(text: str) -> str:
    if len(text) <= LIMIT:
        return text
    window = text[:LIMIT]
    end = window.rfind("\n")
    if end < LIMIT // 2:
        end = LIMIT
    return text[:end].rstrip() + _CUT_NOTE.format(shown=end, total=len(text))


def _fit_entities(items: list) -> Any:
    projected = [_project_entity(item) for item in items]
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
    out: dict[str, Any] = {"entity_id": item["entity_id"]}
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
    # Automations, scripts and scenes: the prompts build edit links from this id.
    attributes = item.get("attributes")
    if isinstance(attributes, dict) and isinstance(attributes.get("id"), (str, int)):
        out["id"] = attributes["id"]
    return out


def _entity_list(items: list) -> bool:
    return bool(items) and all(_entity_id(item) and "state" in item for item in items)


def _entity_id(item: Any) -> str:
    """Only entity_id counts: dashboards use "entity" and "id" for config that must stay whole."""
    value = item.get("entity_id") if isinstance(item, dict) else None
    return value if isinstance(value, str) and _ENTITY_ID.match(value) else ""


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


def _try_json(text: str) -> Any | None:
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
