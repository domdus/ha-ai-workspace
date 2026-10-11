from pathlib import Path

from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider
from custom_components.ai_workspace.const import HA_LINK_INSTRUCTIONS, LOW_TOKEN_PROMPT
from custom_components.ai_workspace.models import Settings


def _settings(**overrides) -> Settings:
    values = {
        "data_dir": Path("/tmp"),
        "workspace_dir": Path("/tmp/workspace"),
        "state_dir": Path("/tmp/state"),
        "cursor_api_key": "",
        "model": "qwen2.5:0.5b",
        "mcp_servers": {},
        "api_provider": "ollama",
    }
    values.update(overrides)
    return Settings(**values)


def test_low_token_prompt_skips_the_tool_instructions() -> None:
    provider = ApiProvider(None, _settings(low_token=True), None)
    text = provider._system("http://homeassistant.local:8123", "de")
    assert LOW_TOKEN_PROMPT in text
    assert "Markdown" not in text
    assert HA_LINK_INSTRUCTIONS[:40] not in text
    assert len(text) < 900


def test_normal_prompt_keeps_link_rules() -> None:
    provider = ApiProvider(None, _settings(), None)
    text = provider._system("", "en")
    assert "Markdown" in text
    assert LOW_TOKEN_PROMPT not in text


def test_agent_stores_low_token() -> None:
    on = agent_from_mapping("a", "Ollama", {"api_provider": "ollama", "low_token": True})
    off = agent_from_mapping("b", "Ollama", {"api_provider": "ollama"})
    assert on.low_token is True
    assert off.low_token is False
