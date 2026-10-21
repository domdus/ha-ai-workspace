from pathlib import Path

import yaml

from custom_components.ai_workspace.const import (
    CONF_API_PROVIDER,
    CONF_ASSIST,
    CONF_ASSIST_STT,
    CONF_ASSIST_TTS,
    CONF_CHECK_HOUSE,
    CONF_HA_USAGE_SENSORS,
    CONF_LOW_TOKEN,
    CONF_TRACK_USAGE,
    MODE_CURSOR,
    TOKEN_MODE_EXTREME,
)
from custom_components.ai_workspace.yaml_config import (
    YAML_SCHEMA,
    agent_payload,
    agent_unique_id,
    agents_from_yaml,
    connections_from_yaml,
    entry_from_yaml,
    options_from_yaml,
)


def test_docs_example_matches_schema() -> None:
    text = Path("docs/configuration.example.yaml").read_text(encoding="utf-8")
    text = text.replace("!secret ", "")
    loaded = yaml.safe_load(text)
    conf = YAML_SCHEMA(loaded["ai_workspace"])
    assert len(conf["connections"]) == 2
    assert [row["provider"] for row in conf["agents"]][-1] == "cursor"


def test_schema_accepts_full_example() -> None:
    conf = YAML_SCHEMA(
        {
            "enable_sidebar": True,
            "ha_usage_sensors": False,
            "low_token": "light",
            "ui_theme": "ha_components",
            "keep_chats": 12,
            "connections": [
                {"kind": "ha_mcp", "name": "HA-MCP", "url": "", "primary": True},
                {"kind": "custom", "name": "github", "url": "https://api.githubcopilot.com/mcp/", "token": "pat"},
            ],
            "agents": [
                {"id": "openai", "provider": "openai", "api_key": "sk", "model": "gpt-5", "assist": True},
                {"id": "cursor", "provider": "cursor", "cursor_api_key": "crsr", "model": "composer-2.5"},
                {
                    "id": "azure",
                    "provider": "azure",
                    "api_key": "az",
                    "api_base": "https://example.openai.azure.com",
                    "model": "gpt-4o",
                },
            ],
        }
    )
    assert conf["low_token"] == "light"
    assert conf["agents"][1]["provider"] == "cursor"


def test_partial_options_do_not_fill_defaults() -> None:
    patch = options_from_yaml({"ha_usage_sensors": True, "low_token": "extreme"})
    assert patch == {CONF_HA_USAGE_SENSORS: True, CONF_LOW_TOKEN: TOKEN_MODE_EXTREME}
    filled = options_from_yaml({"ha_usage_sensors": True}, fill_defaults=True)
    assert filled[CONF_HA_USAGE_SENSORS] is True
    assert filled[CONF_TRACK_USAGE] is True


def test_connections_mark_one_primary() -> None:
    rows = connections_from_yaml(
        {
            "connections": [
                {"kind": "ha", "name": "Home Assistant"},
                {"kind": "custom", "name": "github", "url": "https://example/mcp", "primary": True},
            ]
        }
    )
    assert [row["data"]["primary"] for row in rows] == [False, True]
    assert connections_from_yaml({}) == []
    default = connections_from_yaml({}, fill_default=True)
    assert len(default) == 1 and default[0]["data"]["mcp_kind"] == "ha"


def test_agents_get_stable_ids_and_cursor_mode() -> None:
    used: set[str] = set()
    assert agent_unique_id({"id": "openai", "provider": "openai"}, used) == "openai"
    assert agent_unique_id({"id": "openai", "provider": "openai"}, used) == "openai-2"
    cursor = agent_payload({"provider": "cursor", "cursor_api_key": "k", "model": "composer-2.5"}, "cursor")
    assert cursor["data"][CONF_API_PROVIDER] == MODE_CURSOR
    assert cursor["data"]["api_key"] == ""
    assert cursor["data"]["cursor_api_key"] == "k"
    openai = agent_payload({"provider": "openai", "api_key": "sk", "assist": True}, "openai")
    assert openai["data"][CONF_ASSIST] is True
    silent = agent_payload({"provider": "anthropic", "api_key": "x"}, "claude")
    assert silent["data"][CONF_ASSIST] is False
    gemini = agent_payload({"provider": "gemini", "api_key": "g"}, "gemini")
    assert gemini["data"][CONF_ASSIST_TTS] is False
    assert gemini["data"][CONF_ASSIST_STT] is False
    spoken = agent_payload(
        {
            "provider": "gemini",
            "api_key": "g",
            "assist_stt": True,
            "assist_tts": True,
            "tts_voice": "Puck",
        },
        "gemini-2",
    )
    assert spoken["data"][CONF_ASSIST_STT] is True
    assert spoken["data"][CONF_ASSIST_TTS] is True
    assert spoken["data"]["tts_voice"] == "Puck"
    assert spoken["data"]["tts_speed"] == "1"


def test_entry_from_yaml_includes_default_connection() -> None:
    options, subentries = entry_from_yaml({"ha_usage_sensors": True, "agents": [{"provider": "openai", "api_key": "sk"}]})
    kinds = [row["subentry_type"] for row in subentries]
    assert kinds.count("mcp") == 1
    assert kinds.count("agent") == 1
    assert kinds.count("usage") == 1
    assert options[CONF_HA_USAGE_SENSORS] is True
    assert options[CONF_CHECK_HOUSE] is True
    assert agents_from_yaml({}) == []
    off, _subs = entry_from_yaml(
        {
            "agents": [
                {"provider": "openai", "api_key": "sk", "check_house": False},
                {"provider": "anthropic", "api_key": "x", "check_house": False},
            ]
        }
    )
    assert off[CONF_CHECK_HOUSE] is False
