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
