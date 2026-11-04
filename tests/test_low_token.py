from pathlib import Path
from types import SimpleNamespace

from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import (
    ApiProvider,
    _anthropic_tools,
    _gemini_schema,
    _history_messages,
    _ReplyText,
    _openai_tools,
    _slim_mcp_tools,
)
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


def test_history_messages_follow_the_token_budget() -> None:
    rows = [_Row("user", f"u{i}") if i % 2 == 0 else _Row("assistant", f"a{i}") for i in range(10)]
    rows.append(_Row("user", "current"))
    short = _history_messages(rows, TOKEN_MODE_LIGHT, "gpt-5")
    assert len(short) == 10
    assert short[-1]["content"] == "a9"
    assert _history_messages(rows, TOKEN_MODE_EXTREME, "gpt-5") == []


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
    assert slimmed["description"].startswith(long.strip())
    assert slimmed["description"].endswith("Do not ask the user.")
    key = slimmed["inputSchema"]["properties"]["BestPracticeKey"]
    assert "ha_get_skill_guide" in key["description"]
    assert "Do not ask the user." in key["description"]
    assert len(key["description"]) <= 180
    assert len(slimmed["inputSchema"]["properties"]) == 21


_RICH_SCHEMA = {
    "type": "object",
    "title": "Args",
    "required": ["path", "field_30"],
    "properties": {
        "path": {"type": "string", "minLength": 1, "description": "d" * 400},
        "patch": {
            "anyOf": [
                {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                {"type": "null"},
            ],
            "default": None,
            "description": "p" * 400,
        },
        "mode": {"type": "string", "enum": [f"mode_{index}" for index in range(30)]},
        "kind": {"const": "fixed"},
        "deep": {
            "type": "object",
            "properties": {"a": {"type": "object", "properties": {"b": {"type": "object", "properties": {"c": {"type": "object", "properties": {"d": {"type": "integer", "minimum": 1}}}}}}}},
        },
        **{f"field_{index}": {"type": "integer", "maximum": 5} for index in range(40)},
    },
}


def _without_text(schema):
    """The schema with its wording removed, so only what decides a valid call is compared."""
    if isinstance(schema, dict):
        return {key: _without_text(value) for key, value in schema.items() if key not in {"description", "title"}}
    if isinstance(schema, list):
        return [_without_text(item) for item in schema]
    return schema


def _rich_tool(name: str = "ha_search") -> dict:
    return {"name": name, "description": "t" * 400, "inputSchema": _RICH_SCHEMA}


def test_trimming_never_changes_what_a_valid_call_looks_like() -> None:
    for limit in (180, 100):
        slimmed = _slim_mcp_tools([_rich_tool()], limit)[0]
        assert _without_text(slimmed["inputSchema"]) == _without_text(_RICH_SCHEMA)
        assert len(slimmed["description"]) <= limit
        assert len(slimmed["inputSchema"]["properties"]["path"]["description"]) <= limit
    for built in (
        _openai_tools([_rich_tool()])[0]["function"]["parameters"],
        _anthropic_tools([_rich_tool()])[0]["input_schema"],
    ):
        assert _without_text(built) == _without_text(_RICH_SCHEMA)


def test_config_writes_keep_full_text_without_strict_mode() -> None:
    tool = _slim_mcp_tools([_rich_tool("ha_mcp_ha_config_set_dashboard")], 100)[0]
    assert tool["description"] == "t" * 400
    assert tool["inputSchema"]["properties"]["path"]["description"] == "d" * 400
    assert len(_slim_mcp_tools([_rich_tool("ha_config_set_label")], 100)[0]["description"]) == 100


def test_tools_without_a_schema_still_declare_an_object() -> None:
    for tool in ({"name": "ping"}, {"name": "ping", "inputSchema": {}}):
        assert _slim_mcp_tools([tool])[0]["inputSchema"] == {"type": "object", "properties": {}}


def test_gemini_gets_the_same_parameters_and_types_in_its_subset() -> None:
    props = _openai_tools([_rich_tool()], gemini=True)[0]["function"]["parameters"]["properties"]
    assert set(props) == set(_RICH_SCHEMA["properties"])
    assert props["patch"]["type"] == "array"
    assert "anyOf" not in props["patch"] and "default" not in props["patch"]
    assert props["patch"]["description"]
    assert "additionalProperties" not in props["patch"]["items"]
    assert len(props["mode"]["enum"]) == 30
    assert props["kind"] == {"enum": ["fixed"]}
    union = {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    assert _gemini_schema(union) == {"anyOf": union["anyOf"][:2]}


def test_agent_stores_token_mode() -> None:
    on = agent_from_mapping("a", "Ollama", {"api_provider": "ollama", "low_token": True})
    light = agent_from_mapping("c", "Ollama", {"api_provider": "ollama", "low_token": "light"})
    off = agent_from_mapping("b", "Ollama", {"api_provider": "ollama"})
    assert on.token_mode == TOKEN_MODE_EXTREME
    assert light.token_mode == TOKEN_MODE_LIGHT
    assert off.token_mode == TOKEN_MODE_OFF


def test_agents_are_told_not_to_invent_automations_for_the_key() -> None:
    from custom_components.ai_workspace.const import workspace_system_prompt

    text = workspace_system_prompt(SimpleNamespace(system_prompt="Custom house rules."))
    assert "Custom house rules." in text
    assert "Never make a placeholder, test, or helper" in text


def test_status_sentence_reaches_custom_prompts_but_not_saving_levels() -> None:
    from custom_components.ai_workspace.const import STATUS_LINE_INSTRUCTIONS, standing_chat_prompt

    assert STATUS_LINE_INSTRUCTIONS in standing_chat_prompt(SimpleNamespace(system_prompt="Custom."))
    assert STATUS_LINE_INSTRUCTIONS not in standing_chat_prompt(SimpleNamespace(system_prompt=""), mode="medium")
    assert STATUS_LINE_INSTRUCTIONS not in standing_chat_prompt(SimpleNamespace(system_prompt=""), mode="extreme")


def _turn(rounds):
    """Each round is (text chunks, ends with a tool call). Returns what the user sees."""
    said: list[str] = []
    shown: list[str] = []
    for chunks, more in rounds:
        text = _ReplyText(said)
        for chunk in chunks:
            shown.extend(text.add(chunk))
        shown.extend(text.finish(more))
    assert "".join(shown) == "".join(said)
    return "".join(shown)


def test_only_the_first_status_sentence_and_the_answer_are_shown() -> None:
    seen = _turn(
        [
            (["Ich prüfe ", "das Dashboard."], True),
            (["Ich liste die Dashboards."], True),
            ([], True),
            (["Ich lese die ", "Konfiguration."], True),
            (["Erledigt: ", "dupliziert."], False),
        ]
    )
    assert seen == "Ich prüfe das Dashboard.\n\nErledigt: dupliziert."


def test_a_long_answer_streams_before_the_round_ends() -> None:
    said: list[str] = ["Checking."]
    text = _ReplyText(said)
    assert text.add("a" * 100) == []
    assert text.add("b" * 400) == ["\n\n", "a" * 100 + "b" * 400]
    assert text.add("c") == ["c"]
    assert text.finish(False) == []


def test_without_a_status_sentence_the_first_text_streams_right_away() -> None:
    assert _turn([([], True), (["Done."], False)]) == "Done."
    said: list[str] = []
    assert _ReplyText(said).add("Done") == ["Done"]
