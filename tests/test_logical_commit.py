import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace"
PKG = "ai_workspace_lc"


def _load(name: str, file: str):
    if "homeassistant" not in sys.modules:
        ha = types.ModuleType("homeassistant")
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.core"] = core
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [str(ROOT)]
        pkg.__package__ = PKG
        sys.modules[PKG] = pkg
    full = f"{PKG}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = PKG
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_queue_starts_orphan_commit_when_missing() -> None:
    lc = _load("logical_commit", "logical_commit.py")
    hass = types.SimpleNamespace(data={})
    assert lc.queue_activity_fragment(
        hass,
        user_id="u",
        user_name="Ada",
        agent="Cursor",
        session_id="s",
        chat="Move cards",
        summary="Updated dashboard Home",
        tool="ha_config_set_dashboard",
        document={"kind": "dashboard", "id": "lovelace"},
    ) is True
    row = lc.turn_bucket(hass, "u", "s")
    assert row is not None
    assert row.orphan is True
    assert [item.summary for item in row.fragments] == ["Updated dashboard Home"]
    assert lc.active_commit_id(hass, "u", "s")


def test_merge_logical_summary_and_targets() -> None:
    lc = _load("logical_commit", "logical_commit.py")
    frags = [
        lc.ActivityFragment("Updated dashboard", "ha_config_set_dashboard", {"kind": "dashboard", "id": "lovelace"}),
        lc.ActivityFragment("Updated automation", "ha_config_set_automation", {"kind": "automation", "id": "abc"}),
    ]
    summary = lc.merge_logical_summary(frags)
    assert "2 changes" in summary or "Updated dashboard" in summary
    doc = lc.merge_logical_document(frags)
    raw = __import__("json").dumps(doc)
    targets = lc.restore_targets(raw)
    assert len(targets) == 2
    assert any(t[0] == "dashboard" for t in targets)
    docs = lc.documents_to_restore(doc)
    assert [item.get("kind") for item in docs] == ["dashboard", "automation"]
    assert lc.documents_to_restore({"kind": "dashboard", "id": "lovelace"}) == [
        {"kind": "dashboard", "id": "lovelace"}
    ]
