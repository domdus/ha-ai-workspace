"""One huge text inside a JSON result must not push every other section out."""

import json

from app.tool_result import LIMIT, TRUNCATED, shorten_mcp_response


def _overview(note_chars: int) -> dict:
    # The shape of HA-MCP's ha_get_overview on a real home: one integration's notification was 139k.
    return {
        "success": True,
        "system_summary": {"total_entities": 1830},
        "domain_stats": {f"sensor_{i}": {"count": i, "states": {"on": i}} for i in range(300)},
        "system_info": {"version": "2026.11.0"},
        "notification_count": 1,
        "notifications": [{"notification_id": "vacuum_replace", "title": "L40s Pro Ultra", "message": "x" * note_chars}],
        "repair_count": 2,
        "repairs": [{"issue_id": "midea_offline"}, {"issue_id": "db_size"}],
        "ha_mcp_update": {"available": False},
    }


def _call(overview: dict) -> tuple[dict, str]:
    text = json.dumps(overview)
    body = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": text}], "structuredContent": overview}}
    request = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ha_get_overview"}}).encode()
    raw, kind = shorten_mcp_response(request, json.dumps(body).encode(), "application/json")
    return json.loads(raw)["result"], kind


def test_huge_notification_is_shortened_and_every_section_stays() -> None:
    result, kind = _call(_overview(139_000))
    assert kind == TRUNCATED
    text = result["content"][0]["text"]
    assert len(text) <= LIMIT
    data = json.loads(text)  # still valid JSON
    assert data["repairs"] == [{"issue_id": "midea_offline"}, {"issue_id": "db_size"}]
    assert data["ha_mcp_update"] == {"available": False}
    assert data["system_info"]["version"] == "2026.11.0"
    message = data["notifications"][0]["message"]
    assert "more characters left out" in message and "do not write it back" in message
    # Names where the bulk came from, so the agent can tell the user.
    assert "notifications[0].message" in message
    assert "notification_id vacuum_replace" in message and "title L40s Pro Ultra" in message
    assert len(message) < 21_000
    # The duplicate structured copy is dropped once the text had to be shortened.
    assert "structuredContent" not in result


def test_result_that_fits_is_untouched() -> None:
    overview = _overview(2_000)
    result, kind = _call(overview)
    assert json.loads(result["content"][0]["text"]) == overview


def test_many_mid_size_values_fall_back_to_the_cut_with_a_clear_note() -> None:
    # 400 texts of 1,000 characters each: clipping long strings alone cannot fit it.
    big = {"items": [{"text": "y" * 1000, "n": i} for i in range(400)]}
    result, kind = _call(big)
    text = result["content"][0]["text"]
    assert kind == TRUNCATED
    assert "do not repeat it" in text and "Result cut" in text


def test_entity_attribute_names_its_entity() -> None:
    # One entity, as ha_get_state returns it (listings are already reduced to plain states).
    entity = {"entity_id": "camera.l40s_pro_ultra_map", "state": "idle", "attributes": {"map": "m" * 120_000, "rooms": 9}}
    result, _ = _call(entity)
    data = json.loads(result["content"][0]["text"])
    clipped = data["attributes"]["map"]
    assert data["attributes"]["rooms"] == 9
    assert "attributes.map" in clipped and "entity_id camera.l40s_pro_ultra_map" in clipped
