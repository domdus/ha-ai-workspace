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
        notes = False
        notes_text = ""

    text = const.workspace_system_prompt(S(), admin=True)
    assert "Lovelace / dashboards (strict)" in text
    # Cloud agents have no file tools; only Cursor gets the file rule.
    assert "grep, glob" not in text
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
    assert "grep, glob, read, shell" in standing
    for rule in ("small talk", "Do not link the words Home Assistant", "never invent entity ids"):
        assert standing.lower().count(rule.lower()) == 1, rule


def test_workspace_prompt_teaches_ai_workspace_tasks() -> None:
    const = _load()

    class S:
        system_prompt = "Custom prompt."
        house_map = False
        notes = False
        notes_text = ""

    text = const.workspace_system_prompt(S(), admin=True)
    # Built-in rule: a custom system prompt does not drop it.
    assert text.count(const.TASK_RULES) == 1
    for part in (
        "any automation or script that hands a prompt to an AI Workspace agent",
        "ai_workspace.run_task",
        "not conversation.process",
        "self-contained",
        "allow_changes defaults to false",
        "response_variable",
        "{{ x.response }}",
        "'ok'",
        "notify field",
        "label ai_workspace",
        "add it only if missing",
    ):
        assert part in const.TASK_RULES, part
    # Ordinary automation building is not steered here, and no delivery channel is assumed.
    for steer in (
        "turn_off",
        "one-shot",
        "recurring",
        "ask before",
        "the way the user asked",
        "Plain device logic",
        "phone",
        "speaker",
        "mobile_app",
        "weather",
        "news",
    ):
        assert steer not in const.TASK_RULES, steer
    # Before the status line rule, so the rest of the prefix keeps its order.
    assert text.index(const.TASK_RULES) < text.index(const.STATUS_LINE_INSTRUCTIONS)
    assert const.TASK_RULES in const.standing_chat_prompt(S(), admin=True)
    assert const.TASK_RULES not in const.workspace_system_prompt(S(), admin=False)
