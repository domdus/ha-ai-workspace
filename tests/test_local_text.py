"""Texts the integration builds itself exist in every shipped language."""

from pathlib import Path

import pytest

from custom_components.ai_workspace import local_text
from custom_components.ai_workspace.api_provider import chat_only_note
from custom_components.ai_workspace.discovery import runtime_form_placeholders
from custom_components.ai_workspace.ollama_info import OllamaModel, OllamaServer, ollama_form_note

SHIPPED = sorted(p.stem for p in (Path(__file__).resolve().parents[1] / "custom_components/ai_workspace/translations").glob("*.json"))


@pytest.mark.parametrize(
    "table",
    [
        local_text.CHAT_ONLY,
        local_text.OLLAMA_FORM,
        local_text.RUNTIME_FORM,
        local_text.CLAUDE_SIGNIN,
        local_text.CLAUDE_AUTH_FAILED,
        local_text.CURSOR_KEY_NOTE,
    ],
)
def test_every_table_covers_every_language(table) -> None:
    assert sorted(table) == SHIPPED == sorted(local_text.LANGUAGES)


@pytest.mark.parametrize("language", SHIPPED)
def test_every_text_formats(language) -> None:
    assert "{" not in chat_only_note("m", OllamaModel(tools=False), language)
    small = chat_only_note("m", OllamaModel(tools=True, running=4096), language)
    assert "OLLAMA_CONTEXT_LENGTH" in small and "{" not in small
    assert "0.12" in ollama_form_note(OllamaServer(True, "0.12", 3), "http://x", language)
    assert "http://x" in ollama_form_note(OllamaServer(False), "http://x", language)
    assert runtime_form_placeholders(live=True, auto=True, language=language)["runtime_url_note"].startswith("✅")


def test_language_codes_resolve() -> None:
    table = local_text.RUNTIME_FORM
    assert local_text.pick(table, "de-CH") == table["de"]
    assert local_text.pick(table, "zh-Hant") == table["zh-Hant"]
    assert local_text.pick(table, "zh-TW") == table["zh-Hant"]
    assert local_text.pick(table, "zh-CN") == table["zh-Hans"]
    assert local_text.pick(table, "pt-BR") == table["en"]
    assert local_text.pick(table, "") == table["en"]


@pytest.mark.parametrize("language", SHIPPED)
def test_claude_sign_in_texts_format(language) -> None:
    words = local_text.CLAUDE_SIGNIN[language]
    assert set(words) == set(local_text.CLAUDE_SIGNIN["en"])
    settings = local_text.claude_signin_text({"credential": "settings", "kind": "plan"}, False, language)
    assert "Claude Plan" in settings and "{" not in settings
    old = local_text.claude_signin_text({"credential": "settings", "kind": "api", "overridden": True}, False, language)
    assert words["overridden"] in old
    assert "Runtime" in words["overridden"]
    assert "{" not in local_text.claude_auth_failed_text(language)


def _tables() -> dict[str, dict]:
    """Every language table in local_text (a dict with an "en" entry), so a new one is checked too."""
    return {
        name: value
        for name, value in vars(local_text).items()
        if name.isupper() and isinstance(value, dict) and "en" in value
    }


@pytest.mark.parametrize("name", sorted(_tables()))
def test_every_local_table_is_complete(name) -> None:
    import re

    table = _tables()[name]
    assert sorted(table) == SHIPPED, name
    marks = re.compile(r"\{[a-z_]+\}")

    def parts(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, (tuple, list)):
            return dict(enumerate(value))
        return {0: value}

    english = parts(table["en"])
    for language, value in table.items():
        own = parts(value)
        assert own.keys() == english.keys(), (name, language)
        for key, text in own.items():
            assert str(text).strip() or not str(english[key]).strip(), (name, language, key)
            assert sorted(marks.findall(str(text))) == sorted(marks.findall(str(english[key]))), (name, language, key)


@pytest.mark.parametrize("language", SHIPPED)
def test_plan_rejected_reads_in_every_language(language) -> None:
    text = local_text.plan_rejected_text(language, engine="codex", window="week", reset="09:00")
    assert "Codex" in text and "09:00" in text and "{" not in text
    assert "Claude" in local_text.claude_plan_rejected_text(language, reset="09:00")


@pytest.mark.parametrize("language", SHIPPED)
def test_mcp_form_notes_read_in_the_ha_language(language) -> None:
    from custom_components.ai_workspace.config_flow import _form_placeholders

    found = _form_placeholders(mcp_url="http://ha:8123/api/mcp", mcp_auto=True, language=language)
    assert found["mcp_url_note"] == local_text.MCP_FORM[language][3]
    assert found["mcp_url_mark"] == local_text.MCP_FORM[language][5]
    assert _form_placeholders(none_found=True, language=language)["mcp_url_note"] == local_text.MCP_FORM[language][1]
    if language != "en":
        assert _form_placeholders(language=language)["mcp_url_note"] != local_text.MCP_FORM["en"][0]


def test_codex_plan_limit_reads_in_the_chat_language() -> None:
    http = pytest.importorskip("custom_components.ai_workspace.http")
    event = {"type": "error", "code": "codex_plan_rejected", "engine": "codex", "window": "week", "message": "x"}
    # Without a reset time Codex's own message says more.
    assert http._localized_runtime_error(None, event, "de") is event
    out = http._localized_runtime_error(None, {**event, "reset_at": "x"}, "de")
    assert out["message"].startswith("Codex-Wochenlimit ist voll.")
    claude = http._localized_runtime_error(None, {"type": "error", "code": "claude_plan_rejected"}, "fr")
    assert claude["message"].startswith("La session Claude est pleine.")
