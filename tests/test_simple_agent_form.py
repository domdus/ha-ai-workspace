"""1.5: one Save tokens box under Advanced, Ollama chat-only detection, and model checks."""

from custom_components.ai_workspace.agent_flow import ollama_has_model, saves_tokens, stored_token_mode
from custom_components.ai_workspace.agents import agent_token_mode
from custom_components.ai_workspace.api_provider import chat_only_note
from custom_components.ai_workspace.const import (
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
)
from custom_components.ai_workspace.ollama_info import OllamaModel, native_root, parse_ps, parse_show


def test_old_levels_map_onto_the_box() -> None:
    assert saves_tokens({"low_token": "off"}) is False
    assert saves_tokens({"low_token": "light"}) is False
    assert saves_tokens({"low_token": "medium"}) is True
    assert saves_tokens({"low_token": "extreme"}) is True
    assert saves_tokens({"low_token": "off", "advanced": {"save_tokens": True}}) is True


def test_box_stores_medium_and_keeps_chat_only() -> None:
    assert stored_token_mode({"low_token": "off"}, True) == TOKEN_MODE_MEDIUM
    assert stored_token_mode({"low_token": "extreme"}, True) == TOKEN_MODE_EXTREME
    assert stored_token_mode({"low_token": "extreme"}, False) == TOKEN_MODE_OFF


def test_light_reads_as_off() -> None:
    assert agent_token_mode("light") == TOKEN_MODE_OFF
    assert agent_token_mode("medium") == TOKEN_MODE_MEDIUM
    assert agent_token_mode(True) == TOKEN_MODE_EXTREME


def test_ollama_model_names_match_with_and_without_tag() -> None:
    installed = ["qwen2.5:1.5b", "llama3.2:latest"]
    assert ollama_has_model(installed, "qwen2.5:1.5b")
    assert ollama_has_model(installed, "llama3.2")
    assert not ollama_has_model(installed, "qwen2.5")


def test_ollama_show_and_ps_parsing() -> None:
    show = {"capabilities": ["completion"], "model_info": {"qwen2.context_length": 32768}}
    assert parse_show(show) == (False, 32768)
    assert parse_show({"capabilities": ["completion", "tools"]}) == (True, None)
    ps = {"models": [{"name": "qwen2.5:1.5b", "context_length": 4096}, {"name": "llama3.2:latest", "context_length": 8192}]}
    assert parse_ps(ps, "qwen2.5:1.5b") == 4096
    assert parse_ps(ps, "llama3.2") == 8192
    assert parse_ps(ps, "mistral") is None
    assert native_root("http://nas:11434/v1/") == "http://nas:11434"


def test_chat_only_note_explains_why() -> None:
    assert "cannot use tools" in chat_only_note("tiny", OllamaModel(tools=False))
    small = chat_only_note("qwen2.5:1.5b", OllamaModel(tools=True, running=4096), "de")
    assert "OLLAMA_CONTEXT_LENGTH" in small and "4.096" in small
    assert chat_only_note("qwen2.5:7b", OllamaModel(tools=True, running=32768)) == ""
    # Unknown (Ollama did not answer): keep today's behavior.
    assert chat_only_note("x", OllamaModel()) == ""


def test_one_hour_cache_box_is_only_on_claude_agents() -> None:
    from custom_components.ai_workspace.agent_flow import _fields_schema, caches_an_hour, uses_claude_runtime
    from custom_components.ai_workspace.agents import agent_from_mapping

    def advanced_keys(provider, *, runtime: bool = False):
        schema = _fields_schema(
            "cloud",
            {"api_provider": provider, "use_claude_runtime": runtime},
            [],
            new=True,
        )
        section = next(value for key, value in schema.schema.items() if str(key) == "advanced")
        return {str(key) for key in section.schema.schema}

    assert advanced_keys("anthropic") == {"save_tokens", "cache_1h"}
    assert advanced_keys("anthropic", runtime=True) == {"save_tokens"}
    assert advanced_keys("openai") == {"save_tokens"}
    assert uses_claude_runtime({"api_provider": "anthropic", "use_claude_runtime": True})
    assert not uses_claude_runtime({"api_provider": "anthropic", "mode": "api"})
    assert caches_an_hour({"cache_1h": True}) is True
    assert caches_an_hour({"cache_1h": True, "advanced": {"cache_1h": False}}) is False
    assert agent_from_mapping("a", "Claude", {"api_provider": "anthropic", "cache_1h": True}).cache_1h is True
    assert agent_from_mapping(
        "r",
        "Claude RT",
        {"api_provider": "anthropic", "use_claude_runtime": True, "mode": "claude", "cache_1h": True},
    ).cache_1h is False
    assert agent_from_mapping("o", "OpenAI", {"api_provider": "openai", "cache_1h": True}).cache_1h is False
