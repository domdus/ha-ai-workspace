"""Rollback of automations, scripts, and scenes goes through Home Assistant's config API."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ai_workspace import activity_ha


def _run(kind, document, status=200, message="", authorization="Bearer user-token"):
    sent = []

    async def fake_post(hass, kind, item_id, body, auth):
        sent.append((kind, item_id, body, auth))
        return status, message

    original = activity_ha._post_config
    activity_ha._post_config = fake_post
    try:
        asyncio.run(activity_ha._rollback_one(SimpleNamespace(), document, authorization))
    finally:
        activity_ha._post_config = original
    return sent


def test_automation_is_restored_through_the_config_api() -> None:
    doc = {"kind": "automation", "id": "balcony", "item": {"id": "balcony", "alias": "Balcony", "triggers": []}}
    sent = _run("automation", doc)
    assert sent == [("automation", "balcony", {"id": "balcony", "alias": "Balcony", "triggers": []}, "Bearer user-token")]


def test_script_key_is_the_path_not_the_body() -> None:
    doc = {"kind": "script", "id": "morning", "item": {"id": "morning", "alias": "Morning", "sequence": []}}
    _kind, item_id, body, _auth = _run("script", doc)[0]
    assert item_id == "morning"
    assert "id" not in body


def test_non_admin_gets_a_clear_message() -> None:
    doc = {"kind": "scene", "id": "1", "item": {"id": "1", "name": "Movie", "entities": {}}}
    with pytest.raises(activity_ha.ActivityError, match="administrator"):
        _run("scene", doc, status=401)


def test_invalid_item_reports_home_assistants_reason() -> None:
    doc = {"kind": "automation", "id": "a", "item": {"id": "a"}}
    with pytest.raises(activity_ha.ActivityError, match="Message malformed"):
        _run("automation", doc, status=400, message="Message malformed: required key not provided")


def test_rollback_needs_the_users_sign_in() -> None:
    doc = {"kind": "automation", "id": "a", "item": {"id": "a"}}
    with pytest.raises(activity_ha.ActivityError, match="Sign in"):
        _run("automation", doc, authorization="")


def test_no_yaml_writer_is_left() -> None:
    assert not hasattr(activity_ha, "_restore_yaml")
    assert not hasattr(activity_ha, "_write_yaml")


def test_a_new_automation_is_not_summarized_as_updated_automation_automation() -> None:
    # The reload event of a new automation carries no id and there is no before-image.
    pending = SimpleNamespace(events=[("yaml", "automation", None)], yaml_docs={}, document=None, dashboard_docs={}, entity_docs={})
    doc, text = asyncio.run(activity_ha._apply_events(SimpleNamespace(), pending))
    # Left empty, so the before/after index ("Created automation Water the balcony") names it.
    assert doc is None and text == ""
    assert activity_ha._summary_from_events(pending) == "Changed an automation"
    pending.events = [("yaml", "script", None)]
    assert activity_ha._summary_from_events(pending) == "Changed a script"


def _ws_run(coro_fn, replies):
    """Run with a fake websocket: replies maps command type to a result or an ActivityError."""
    sent = []

    async def fake_ws(hass, authorization, command):
        sent.append((command, authorization))
        reply = replies.get(command["type"])
        if isinstance(reply, Exception):
            raise reply
        return reply

    original = activity_ha._ws_one
    activity_ha._ws_one = fake_ws
    try:
        result = asyncio.run(coro_fn())
    finally:
        activity_ha._ws_one = original
    return sent, result


def test_helper_rollback_updates_through_its_websocket_command() -> None:
    doc = {"kind": "helper", "domain": "input_boolean", "id": "guest", "item": {"id": "guest", "name": "Guest"}}
    sent, _ = _ws_run(
        lambda: activity_ha._rollback_one(SimpleNamespace(), doc, "Bearer admin"),
        {"input_boolean/list": [{"id": "guest", "name": "Guest mode"}], "input_boolean/update": {}},
    )
    assert sent[-1] == (
        {"type": "input_boolean/update", "input_boolean_id": "guest", "name": "Guest"},
        "Bearer admin",
    )


def test_deleted_helper_is_created_again() -> None:
    doc = {"kind": "helper", "domain": "timer", "id": "tea", "item": {"id": "tea", "name": "Tea", "duration": "0:03:00"}}
    sent, _ = _ws_run(
        lambda: activity_ha._rollback_one(SimpleNamespace(), doc, "Bearer admin"),
        {"timer/list": [], "timer/create": {"id": "tea"}},
    )
    assert sent[-1][0] == {"type": "timer/create", "name": "Tea", "duration": "0:03:00"}


def test_helper_snapshot_needs_the_users_login() -> None:
    change = activity_ha.Change(kind="helper", action="update", item_id="input_boolean.guest", label="", domain="input_boolean")
    sent, doc = _ws_run(lambda: activity_ha._snapshot_helper(SimpleNamespace(), change, ""), {})
    assert doc is None and sent == []
    sent, doc = _ws_run(
        lambda: activity_ha._snapshot_helper(SimpleNamespace(), change, "Bearer user"),
        {"input_boolean/list": [{"id": "guest", "name": "Guest"}]},
    )
    assert doc["item"]["name"] == "Guest" and doc["label"] == "Guest"


def test_dashboard_rollback_saves_through_lovelace_config_save() -> None:
    hass = SimpleNamespace(data={"lovelace": SimpleNamespace(dashboards={"energy-view": object()})})
    doc = {"kind": "dashboard", "id": "energy-view", "url_path": "energy-view", "config": {"views": [{"title": "Old"}]}}
    sent, _ = _ws_run(
        lambda: activity_ha._rollback_one(hass, doc, "Bearer admin"),
        {"lovelace/config": {"views": [{"title": "New"}]}, "lovelace/config/save": None},
    )
    assert sent[-1][0] == {"type": "lovelace/config/save", "url_path": "energy-view", "config": {"views": [{"title": "Old"}]}}


def test_deleted_dashboard_is_created_before_saving() -> None:
    hass = SimpleNamespace(data={"lovelace": SimpleNamespace(dashboards={})})
    doc = {"kind": "dashboard", "id": "garden", "url_path": "garden", "meta": {"title": "Garden"}, "config": {"views": []}}
    sent, _ = _ws_run(
        lambda: activity_ha._rollback_one(hass, doc, "Bearer admin"),
        {
            "lovelace/dashboards/create": {},
            "lovelace/config": activity_ha.ActivityError("config_not_found"),
            "lovelace/config/save": None,
        },
    )
    assert [item[0]["type"] for item in sent] == [
        "lovelace/dashboards/create",
        "lovelace/config",
        "lovelace/config/save",
    ]
    assert sent[0][0]["url_path"] == "garden" and sent[0][0]["title"] == "Garden"


def test_no_internal_collection_lookup_is_left() -> None:
    assert not hasattr(activity_ha, "_collection")
