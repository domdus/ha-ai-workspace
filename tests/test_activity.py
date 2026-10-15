import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    path = ROOT / "custom_components" / "ai_workspace" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


activity = _load("ai_workspace_activity", "activity.py")
_store = _load("ai_workspace_store_activity", "store.py")
Store = _store.Store
ACTIVITY_CAP = _store.ACTIVITY_CAP


def test_automation_update_and_create():
    change = activity.classify("ha_config_set_automation", {"identifier": "automation.morning", "config": {"alias": "Morning"}})
    assert change is not None
    assert change.kind == "automation"
    assert change.action == "update"
    assert change.item_id == "automation.morning"
    assert change.label == "Morning"
    created = activity.classify("ha_config_set_automation", {"config": {"alias": "Porch"}})
    assert created is not None
    assert created.action == "create"
    assert created.label == "Porch"
    assert activity.summary(created) == "Created automation Porch"


def test_delete_script_and_dashboard():
    removed = activity.classify("ha_config_remove_script", {"identifier": "script.bed"})
    assert removed is not None
    assert (removed.kind, removed.action, removed.item_id) == ("script", "delete", "script.bed")
    board = activity.classify("ha_config_set_dashboard", {"url_path": "overview", "title": "Home"})
    assert board is not None
    assert board.kind == "dashboard"
    assert board.action == "update"
    assert board.label == "Home"
    gone = activity.classify("ha_config_delete_dashboard", {"url_path": "overview"})
    assert gone is not None
    assert gone.action == "delete"


def test_reads_and_state_stay_out():
    assert activity.classify("ha_config_get_automation", {"identifier": "automation.morning"}) is None
    assert activity.classify("ha_call_service", {"domain": "light", "service": "turn_on"}) is None
    assert activity.classify("HassTurnOn", {"name": "Kitchen"}) is None
    assert activity.watches_config("ha_config_get_automation") is False
    assert activity.watches_config("ha_call_service") is False
    assert activity.watches_config("ha_config_set_yaml") is True
    assert activity.classify("ha_config_set_yaml", {"filename": "automations.yaml"}) is None
    put = activity.classify("ha_put_automation", {"identifier": "1775990764950"})
    assert put is not None
    assert put.kind == "automation"
    assert put.item_id == "1775990764950"
    transform = activity.classify(
        "ha_config_set_automation",
        {"identifier": 1775990764950, "python_transform": "config['conditions'] = []"},
    )
    assert transform is not None
    assert transform.action == "update"
    assert transform.item_id == "1775990764950"
    assert activity.classify("ha_reload_automations", {}) is None


def test_entity_and_helper():
    entity = activity.classify("ha_set_entity", {"entity_id": "light.kitchen", "name": "Kitchen"})
    assert entity is not None
    assert (entity.kind, entity.action, entity.item_id) == ("entity", "update", "light.kitchen")
    helper = activity.classify(
        "ha_config_set_helper",
        {"helper_type": "input_boolean", "helper_id": "guest", "name": "Guest"},
    )
    assert helper is not None
    assert helper.kind == "helper"
    assert helper.domain == "input_boolean"
    assert helper.action == "update"
    fresh = activity.classify("ha_config_set_helper", {"helper_type": "timer", "name": "Tea"})
    assert fresh is not None
    assert fresh.action == "create"


def test_dashboard_store_id_maps_default_and_view_urls():
    assert activity.dashboard_store_id(None) == "lovelace"
    assert activity.dashboard_store_id("default") == "lovelace"
    assert activity.dashboard_store_id("/lovelace/home") == "lovelace"
    assert activity.dashboard_store_id("lovelace-home") == "lovelace-home"


def test_dashboard_id_ignores_json_patch_paths():
    assert activity.dashboard_id_from_args({"url_path": "default", "patch": [{"op": "replace", "path": "/views/0/title", "value": "Home"}]}) == "default"
    assert activity.dashboard_id_from_args({"path": "/views/0/sections/1"}) == ""
    assert activity.dashboard_args({"url_path": "lovelace", "python_transform": "config['views'][0]['path'] = 'home'"}) is True
    assert activity.dashboard_args({"python_transform": "config['conditions'] = []", "identifier": "automation.x"}) is False


def test_hashed_automation_tool_from_identifier():
    args = {
        "identifier": "automation.balcony_irrigation",
        "python_transform": "config['actions'].append({'action': 'notify.notify'})",
        "config_hash": "abc",
    }
    change = activity.classify("a1b2c3d4e5f6", args)
    assert change is not None
    assert change.kind == "automation"
    assert change.item_id == "automation.balcony_irrigation"
    assert activity.looks_like_config_write("a1b2c3d4e5f6", args) is True
    assert activity.yaml_kind_from_args({"script_id": "bed"}) == "script"
    assert activity.yaml_kind_from_args({"scene_id": "evening"}) == "scene"
    scene = activity.classify("a1b2c3d4e5f6", {"identifier": "scene.evening", "config": {"name": "Evening", "entities": {}}})
    assert scene is not None and scene.kind == "scene"
    assert activity.yaml_kind_from_args({"url_path": "lovelace", "identifier": "automation.x"}) == ""


def test_hashed_dashboard_tool_still_looks_like_a_write():
    args = {"url_path": "default", "python_transform": "config['views'][0]['cards'][0]['grid_options'] = {'rows': 1}"}
    change = activity.classify("a1b2c3d4e5f6", args)
    assert change is not None
    assert change.kind == "dashboard"
    assert change.item_id == "default"
    assert activity.looks_like_config_write("a1b2c3d4e5f6", args) is True
    assert activity.classify("ha_call_service", {"entity_id": "light.kitchen", "url_path": "lovelace"}) is None
    assert activity.looks_like_config_write("ha_call_service", {"entity_id": "light.kitchen"}) is False


def test_changed_index_keys():
    before = {"dashboard:lovelace": ("Home", "aaa"), "entity:light.kitchen": ("Kitchen", "one")}
    after = {"dashboard:lovelace": ("Home", "bbb"), "entity:light.kitchen": ("Kitchen", "one")}
    assert activity.changed_index_keys(before, after) == ["dashboard:lovelace"]


def test_failed_tool_result_is_not_success():
    assert activity.tool_succeeded({"content": [], "isError": True}) is False
    assert activity.tool_succeeded({"content": [{"type": "text", "text": "ok"}]}) is True


def test_describe_index_names_the_change():
    before = {"automation:1": ("Morning", "aaa")}
    after = {"automation:1": ("Morning", "bbb"), "script:bed": ("Bed", "ccc")}
    text = activity.describe_index(before, after)
    assert "Updated automation Morning" in text
    assert "+1" in text
    assert activity.describe_index(before, before) == ""
    assert activity.describe_index(before, {}) == "Deleted automation Morning"


def test_activity_rows_are_private_and_capped(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    first = store.add_activity(
        "user-1",
        "Ada",
        "Cursor",
        "Updated automation Morning",
        "ha_config_set_automation",
        '{"kind":"automation"}',
        "chat-1",
        "Morning lights",
    )
    assert first.session_id == "chat-1"
    assert first.chat == "Morning lights"
    assert first.restore_kind == "automation"
    assert store.session_title("chat-1") == ""
    store.add_activity("user-2", "Bea", "OpenAI", "Created script Bed", "ha_config_set_script", "")
    assert first.can_rollback is True
    own = store.list_activity("user-1", admin=False)
    assert [row.summary for row in own] == ["Updated automation Morning"]
    assert len(store.list_activity("user-1", admin=True)) == 2
    undone = store.mark_activity_undone(first.id)
    assert undone is not None
    assert undone.can_rollback is False
    assert store.activity_document(first.id).startswith("{")
    snapshot = store.change_path(first.id)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("id: morning\nalias: Morning\n", encoding="utf-8")
    for number in range(ACTIVITY_CAP + 1):
        store.add_activity("user-1", "Ada", "Cursor", f"Updated entity {number}", "ha_set_entity", "")
    assert len(store.list_activity("user-1", admin=True)) == ACTIVITY_CAP
    assert store.get_activity(first.id) is None
    assert snapshot.exists() is False
    store.close()


def test_restore_target_from_document():
    kind, item_id, label = _store._restore_target(
        '{"kind":"dashboard","id":"lovelace","label":"Home"}'
    )
    assert kind == "dashboard"
    assert item_id == "lovelace"
    assert label == "Home"
    kind, item_id, label = _store._restore_target(
        '{"kind":"entity","entity_id":"light.kitchen","name":"Kitchen"}'
    )
    assert kind == "entity"
    assert item_id == "light.kitchen"
    assert label == "Kitchen"
    assert _store._restore_target("") == ("", "", "")
    assert _store._restore_target("not-json") == ("", "", "")


def test_ha_mcp_is_connected():
    const = _load("ai_workspace_const", "const.py")
    assert const.ha_mcp_is_connected("ha_mcp") is True
    assert const.ha_mcp_is_connected("ha") is False
    assert const.ha_mcp_is_connected("ha", [{"kind": "ha_mcp"}]) is True
    assert const.ha_mcp_is_connected("custom", [{"kind": "ha"}]) is False
    assert const.ha_mcp_is_connected("", None) is False
