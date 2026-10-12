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
    assert "small talk" in text
    assert "Do not link the words Home Assistant" in text
    assert "Never write that origin" in text
    assert "This user's Home Assistant UI is" not in text
    assert "Call tools silently" in text
    assert "small talk" in const.DEFAULT_SYSTEM_PROMPT
    assert "call a Home Assistant tool" in const.DEFAULT_SYSTEM_PROMPT
