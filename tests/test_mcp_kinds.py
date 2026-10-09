import importlib.util
from pathlib import Path


def _const():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "const.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_const", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_assist_defaults_on_for_existing_off_for_new() -> None:
    const = _const()
    assert const.assist_enabled({}) is True
    assert const.assist_enabled({}, new=True) is False
    assert const.assist_enabled({"assist": False}) is False
    assert const.assist_enabled({"assist": True}, new=True) is True
    assert const.assist_enabled({"assist": False}, new=True) is False


def test_mcp_dropdown_keeps_detected_saved_and_custom() -> None:
    const = _const()
    assert const.mcp_kind_options({"ha"}, current="coolver") == ["ha", "coolver", "custom"]
    assert const.mcp_kind_options({"ha", "ha_mcp"}) == ["ha", "ha_mcp", "custom"]
    assert const.mcp_kind_options(set()) == ["custom"]
    assert const.mcp_kind_options(set(), current="custom") == ["custom"]
