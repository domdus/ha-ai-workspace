"""Texts the integration builds itself exist in every shipped language."""

from pathlib import Path

import pytest

from custom_components.ai_workspace import local_text
from custom_components.ai_workspace.api_provider import chat_only_note
from custom_components.ai_workspace.discovery import runtime_form_placeholders
from custom_components.ai_workspace.ollama_info import OllamaModel, OllamaServer, ollama_form_note

SHIPPED = sorted(p.stem for p in (Path(__file__).resolve().parents[1] / "custom_components/ai_workspace/translations").glob("*.json"))


@pytest.mark.parametrize("table", [local_text.CHAT_ONLY, local_text.OLLAMA_FORM, local_text.RUNTIME_FORM])
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
