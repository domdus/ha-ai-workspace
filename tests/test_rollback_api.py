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
