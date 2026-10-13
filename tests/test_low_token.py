from pathlib import Path

from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider, _slim_mcp_tools
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
    assert "ha_get_skill_guide" in text
    assert "Do not ask the user for it." in text


def test_low_token_prompt_does_not_mention_the_skill_key() -> None:
    provider = ApiProvider(None, _settings(low_token=True), None)
    text = provider._system("", "en")
    assert "BestPracticeKey" not in text


def test_write_tool_keeps_the_skill_key_instruction() -> None:
    long = (
        "Create or update a Home Assistant automation.\n\n"
        "Supports three modes: full config replacement, surgical python_transform, "
        "or take_control_of_blueprint. " * 4
        + "For schema details, see ha_get_skill_guide or your locally installed skills."
    )
    props = {f"field_{index}": {"type": "string", "description": "x" * 400} for index in range(20)}
    props["BestPracticeKey"] = {
        "type": "string",
        "description": (
            "Read-receipt for the home-assistant-best-practices skill; "
            "required when strict best-practices mode is enabled. Not a secret. "
            "The current value is published at the top of the skill content served by ha_get_skill_guide."
        ),
    }
    slimmed = _slim_mcp_tools(
        [{"name": "ha_config_set_automation", "description": long, "inputSchema": {"type": "object", "properties": props}}]
    )[0]
    assert len(slimmed["description"]) <= 180
    assert "ha_get_skill_guide" in slimmed["description"]
    assert "BestPracticeKey" in slimmed["description"]
    assert "Do not ask the user." in slimmed["description"]
    assert "locally installed skills" not in slimmed["description"]
    key = slimmed["inputSchema"]["properties"]["BestPracticeKey"]
    assert "ha_get_skill_guide" in key["description"]
    assert "Do not ask the user." in key["description"]
    assert len(key["description"]) <= 180
    assert len(slimmed["inputSchema"]["properties"]) == 17


def test_agent_stores_low_token() -> None:
    on = agent_from_mapping("a", "Ollama", {"api_provider": "ollama", "low_token": True})
    off = agent_from_mapping("b", "Ollama", {"api_provider": "ollama"})
    assert on.low_token is True
    assert off.low_token is False
