import importlib.util
from pathlib import Path


def _const():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "const.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_const", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_runtime_user_message_includes_automation_edit_links() -> None:
    const = _const()
    text = const.with_ui_context("Welche Automatisierungen gibt es?")
    assert "/config/automation/edit/" in text
    assert "Welche Automatisierungen gibt es?" in text
    assert "markdown table" in text.lower() or "Markdown link" in text
    assert "ha_config_get_automation" in text
    assert "1–3 MCP calls" in text or "1-3 MCP calls" in text


def test_unclear_prompt_falls_back_to_ha_language() -> None:
    const = _const()
    text = const.with_language_rule(const.DEFAULT_SYSTEM_PROMPT, "de")
    assert "answer in German" in text
    assert "Do not assume English." in text
    assert text.count("Always answer in the same language") == 1


def test_editable_system_prompt_omits_editor_link_rules() -> None:
    const = _const()
    assert "/config/automation/edit/" not in const.DEFAULT_SYSTEM_PROMPT
    assert "Markdown link" not in const.DEFAULT_SYSTEM_PROMPT


def test_small_talk_stays_plain() -> None:
    const = _const()
    text = const.ui_link_instructions("http://127.0.0.1:8123")
    assert "Do not link the words Home Assistant" in text
    assert text.count("Do not link the words Home Assistant") == 1
    assert "Never write that origin" in text
    assert "This user's Home Assistant UI is" not in text
    # It contradicted the one status sentence before tools.
    assert "Call tools silently" not in text

    class S:
        system_prompt = "Custom prompt."
        house_map = False

    # Kept when the user replaces the built-in prompt.
    full = const.workspace_system_prompt(S())
    assert "small talk" in full
    assert "call a Home Assistant tool" in full
    assert "Never announce that you are looking at Home Assistant" in const.STATUS_LINE_INSTRUCTIONS
    assert "not for any topic" in const.STATUS_LINE_INSTRUCTIONS
    assert "Do not write that you are looking at Home Assistant" in const.CHECK_HOUSE_NOTE
    assert "not for any topic" in const.CHECK_HOUSE_NOTE
    assert "weather" in const.CHECK_HOUSE_NOTE
    assert "Never announce that look" in const.HOUSE_RULES
    assert "not for any topic" in const.HOUSE_RULES
    assert "weather" in const.HOUSE_RULES
