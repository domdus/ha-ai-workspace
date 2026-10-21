import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace"
PKG = "ai_workspace_prompt"


def _load():
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
    full = f"{PKG}.const"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, ROOT / "const.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = PKG
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_workspace_system_prompt_includes_lovelace_rules() -> None:
    const = _load()

    class S:
        system_prompt = ""
        house_map = False

    text = const.workspace_system_prompt(S(), admin=True)
    assert "Lovelace / dashboards (strict)" in text
    assert "grep, glob, read, shell" in text
    assert "twelve MCP calls" in text.lower() or "twelve MCP" in text
    assert "BestPracticeKey" in text
    assert "ha_get_skill_guide" in text
    assert "Do not ask the user for a key." in text
    assert "Do not call a tool that is not listed." in text
    standing = const.standing_chat_prompt(S(), admin=True, language="de", origin="http://ha.example")
    assert standing.count(const.BPS_KEY_INSTRUCTIONS) == 1
    assert "/config/automation/edit/" in standing
    assert "answer in German" in standing
    assert "The browser origin is http://ha.example" in standing
    assert standing.startswith(text)
