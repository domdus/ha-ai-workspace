from pathlib import Path

from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider, _history_messages, _slim_mcp_tools
from custom_components.ai_workspace.const import (
    BPS_KEY_INSTRUCTIONS,
    HA_LINK_INSTRUCTIONS,
    LOW_TOKEN_MEDIUM_PROMPT,
    LOW_TOKEN_PROMPT,
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_LIGHT,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
    token_mode_checks_house,
    token_mode_history_limit,
    token_mode_of,
    token_mode_reply_limit,
)
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


class _Row:
    def __init__(self, role: str, content: str, events: str = "[]"):
        self.role = role
        self.content = content
        self.events = events


def test_token_mode_of_migrates_bool() -> None:
    assert token_mode_of(True) == TOKEN_MODE_EXTREME
    assert token_mode_of(False) == TOKEN_MODE_OFF
    assert token_mode_of("true") == TOKEN_MODE_EXTREME
    assert token_mode_of("light") == TOKEN_MODE_LIGHT
    assert token_mode_of("medium") == TOKEN_MODE_MEDIUM
    assert token_mode_of("extreme") == TOKEN_MODE_EXTREME
    assert token_mode_of("") == TOKEN_MODE_OFF


def test_extreme_prompt_skips_the_tool_instructions() -> None:
    provider = ApiProvider(None, _settings(token_mode=TOKEN_MODE_EXTREME), None)
    text = provider._system("http://homeassistant.local:8123", "de")
    assert LOW_TOKEN_PROMPT in text
    assert "Markdown" not in text
    assert HA_LINK_INSTRUCTIONS[:40] not in text
    assert len(text) < 900


def test_medium_prompt_allows_tools_without_skill_key() -> None:
    provider = ApiProvider(None, _settings(token_mode=TOKEN_MODE_MEDIUM), None)
    text = provider._system("", "en")
    assert LOW_TOKEN_MEDIUM_PROMPT in text
    assert "cannot check or change the house" not in text
    assert "BestPracticeKey" not in text
    assert "ha_get_skill_guide" not in text
    assert "Markdown" in text


def test_light_prompt_keeps_house_instructions() -> None:
    provider = ApiProvider(None, _settings(token_mode=TOKEN_MODE_LIGHT), None)
    text = provider._system("", "en")
    assert LOW_TOKEN_PROMPT not in text
    assert "ha_get_skill_guide" in text
    assert text.count(BPS_KEY_INSTRUCTIONS) == 1


def test_normal_prompt_keeps_link_rules() -> None:
    provider = ApiProvider(None, _settings(), None)
    text = provider._system("", "en")
    assert "Markdown" in text
    assert LOW_TOKEN_PROMPT not in text
    assert "ha_get_skill_guide" in text
    assert text.count(BPS_KEY_INSTRUCTIONS) == 1


def test_extreme_prompt_does_not_mention_the_skill_key() -> None:
    provider = ApiProvider(None, _settings(token_mode=TOKEN_MODE_EXTREME), None)
    text = provider._system("", "en")
    assert "BestPracticeKey" not in text


def test_house_check_and_limits_per_mode() -> None:
    assert token_mode_checks_house(TOKEN_MODE_LIGHT, False) is False
    assert token_mode_checks_house(TOKEN_MODE_LIGHT, True) is True
    assert token_mode_checks_house(TOKEN_MODE_MEDIUM, True) is True
    assert token_mode_checks_house(TOKEN_MODE_EXTREME, True) is False
    assert token_mode_checks_house(TOKEN_MODE_OFF, True) is True
    assert token_mode_checks_house(TOKEN_MODE_OFF, False) is False
    assert token_mode_history_limit(TOKEN_MODE_EXTREME) == 0
    assert token_mode_history_limit(TOKEN_MODE_MEDIUM) == 4
    assert token_mode_history_limit(TOKEN_MODE_LIGHT) == 12
    assert token_mode_reply_limit(TOKEN_MODE_EXTREME) == 256
    assert token_mode_reply_limit(TOKEN_MODE_MEDIUM) == 1024
    assert token_mode_reply_limit(TOKEN_MODE_LIGHT) is None


def test_history_messages_honors_limit() -> None:
    rows = [_Row("user", f"u{i}") if i % 2 == 0 else _Row("assistant", f"a{i}") for i in range(10)]
    rows.append(_Row("user", "current"))
    clipped = _history_messages(rows, 4)
    assert len(clipped) == 4
    assert clipped[-1]["content"] == "a9"
    assert _history_messages(rows, 0) == []


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


def test_agent_stores_token_mode() -> None:
    on = agent_from_mapping("a", "Ollama", {"api_provider": "ollama", "low_token": True})
    light = agent_from_mapping("c", "Ollama", {"api_provider": "ollama", "low_token": "light"})
    off = agent_from_mapping("b", "Ollama", {"api_provider": "ollama"})
    assert on.token_mode == TOKEN_MODE_EXTREME
    assert light.token_mode == TOKEN_MODE_LIGHT
    assert off.token_mode == TOKEN_MODE_OFF
