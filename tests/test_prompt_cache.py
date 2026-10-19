from pathlib import Path
from types import SimpleNamespace

from custom_components.ai_workspace.__init__ import _workspace_prompt_cache
from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider, _strip_prompt_cache
from custom_components.ai_workspace.const import SUBENTRY_AGENT
from custom_components.ai_workspace.models import Settings


def _settings(provider: str, **overrides) -> Settings:
    values = {
        "data_dir": Path("/tmp"),
        "workspace_dir": Path("/tmp/workspace"),
        "state_dir": Path("/tmp/state"),
        "cursor_api_key": "",
        "model": "m",
        "mcp_servers": {},
        "api_provider": provider,
        "api_key": "k",
        "agent_id": "agent-1",
    }
    values.update(overrides)
    return Settings(**values)


def test_agent_defaults_prompt_cache_on() -> None:
    on = agent_from_mapping("a", "OpenAI", {"api_provider": "openai"})
    off = agent_from_mapping("b", "OpenAI", {"api_provider": "openai", "prompt_cache": False})
    assert on.prompt_cache is True
    assert off.prompt_cache is False


def _entry(*agents, options=None):
    subs = {}
    for index, raw in enumerate(agents):
        subs[f"sub-{index}"] = SimpleNamespace(
            subentry_type=SUBENTRY_AGENT,
            subentry_id=f"sub-{index}",
            unique_id=f"agent-{index}",
            title=raw.get("title", "Agent"),
            data=raw,
        )
    return SimpleNamespace(options=options or {}, subentries=subs)


def test_workspace_prompt_cache_defaults_on() -> None:
    assert _workspace_prompt_cache(_entry(), {}) is True
    assert _workspace_prompt_cache(_entry({"api_provider": "openai"}), {}) is True


def test_workspace_prompt_cache_uses_shared_option() -> None:
    entry = _entry({"api_provider": "openai", "prompt_cache": True}, options={"prompt_cache": False})
    assert _workspace_prompt_cache(entry, {"prompt_cache": False}) is False


def test_workspace_prompt_cache_migrates_all_agents_off() -> None:
    entry = _entry(
        {"api_provider": "openai", "prompt_cache": False},
        {"api_provider": "anthropic", "prompt_cache": False},
        {"api_provider": "cursor"},
    )
    assert _workspace_prompt_cache(entry, {}) is False


def test_anthropic_marks_system_and_last_tool() -> None:
    provider = ApiProvider(None, _settings("anthropic"), None)
    payload = provider._apply_prompt_cache(
        {
            "model": "claude-sonnet-4-5",
            "system": "You help with this Home Assistant.",
            "tools": [{"name": "one", "input_schema": {}}, {"name": "two", "input_schema": {}}],
        }
    )
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in payload["tools"][0]
    assert payload["tools"][1]["cache_control"] == {"type": "ephemeral"}


def test_openai_sets_prompt_cache_key() -> None:
    provider = ApiProvider(None, _settings("openai"), None)
    payload = provider._apply_prompt_cache({"model": "gpt-5", "messages": [{"role": "system", "content": "Hi"}]})
    assert payload["prompt_cache_key"] == "ai-workspace:agent-1:openai"
    assert payload["messages"][0]["content"] == "Hi"


def test_openrouter_marks_system_and_tools() -> None:
    provider = ApiProvider(None, _settings("openrouter"), None)
    payload = provider._apply_prompt_cache(
        {
            "model": "anthropic/claude-sonnet-4-5",
            "messages": [{"role": "system", "content": "Hi"}],
            "tools": [{"type": "function", "function": {"name": "one"}}],
        }
    )
    assert payload["prompt_cache_key"].startswith("ai-workspace:")
    assert payload["messages"][0]["content"][0]["cache_control"]["type"] == "ephemeral"
    assert payload["tools"][0]["cache_control"]["type"] == "ephemeral"


def test_ollama_and_toggle_off_skip_cache() -> None:
    ollama = ApiProvider(None, _settings("ollama"), None)
    payload = ollama._apply_prompt_cache({"model": "llama3.2", "system": "Hi"})
    assert "cache_control" not in payload
    assert "prompt_cache_key" not in payload
    off = ApiProvider(None, _settings("anthropic", prompt_cache=False), None)
    skipped = off._apply_prompt_cache({"system": "Hi", "tools": [{"name": "one"}]})
    assert "cache_control" not in skipped
    assert "cache_control" not in skipped["tools"][0]


def test_strip_prompt_cache_clears_nested_markers() -> None:
    body = {
        "cache_control": {"type": "ephemeral"},
        "prompt_cache_key": "x",
        "system": [{"type": "text", "text": "Hi", "cache_control": {"type": "ephemeral"}}],
        "tools": [{"name": "one", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "system", "content": [{"type": "text", "text": "Hi", "cache_control": {"type": "ephemeral"}}]}],
    }
    assert _strip_prompt_cache(body) is True
    assert "cache_control" not in body
    assert "prompt_cache_key" not in body
    assert "cache_control" not in body["system"][0]
    assert "cache_control" not in body["tools"][0]
    assert "cache_control" not in body["messages"][0]["content"][0]
    assert _strip_prompt_cache(body) is False
