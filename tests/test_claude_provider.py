from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.providers.claude import (
    ClaudeProvider,
    claude_subprocess_env,
    detect_auth_mode,
    map_claude_message,
)
from app.providers.cursor import CursorRuntime, build_providers
from app.settings import Settings


def _settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        openrouter_api_key=extra.get("openrouter", ""),
        claude_oauth_token=extra.get("oauth", ""),
        anthropic_api_key=extra.get("anthropic", ""),
        anthropic_base_url=extra.get("base", ""),
        claude_model=extra.get("claude_model", ""),
        auth_mode="dev",
        host=extra.get("host", "127.0.0.1"),
        port=8090,
    )


def test_detect_auth_mode_openrouter(tmp_path) -> None:
    settings = _settings(tmp_path, openrouter="sk-or-test")
    assert detect_auth_mode("", settings) == "openrouter"
    assert detect_auth_mode("sk-or-chat", settings) == "openrouter"
    settings2 = _settings(tmp_path, base="https://openrouter.ai/api/v1")
    assert detect_auth_mode("any", settings2) == "openrouter"


def test_detect_auth_mode_plan_and_api(tmp_path) -> None:
    settings = _settings(tmp_path, oauth="sk-ant-oat-xx")
    assert detect_auth_mode("", settings) == "plan"
    assert detect_auth_mode("sk-ant-oat-yy", _settings(tmp_path)) == "plan"
    settings3 = _settings(tmp_path, anthropic="sk-ant-api")
    assert detect_auth_mode("", settings3) == "api"


def test_openrouter_subprocess_env_empty_api_key(tmp_path) -> None:
    settings = _settings(tmp_path, openrouter="sk-or-test", claude_model="anthropic/claude-sonnet-4.5")
    env = claude_subprocess_env(settings, "sk-or-chat", "anthropic/claude-sonnet-4.5")
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-chat"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "anthropic/claude-sonnet-4.5"


def test_plan_subprocess_env_no_api_keys(tmp_path) -> None:
    settings = _settings(tmp_path, oauth="sk-ant-oat-token")
    env = claude_subprocess_env(settings, "sk-ant-oat-token", "claude-sonnet-5-5")
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat-token"
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_api_subprocess_env(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic="sk-ant-api")
    env = claude_subprocess_env(settings, "sk-ant-api", "claude-sonnet-5-5")
    assert env.get("ANTHROPIC_API_KEY") == "sk-ant-api"


def test_map_assistant_text_and_result() -> None:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    events = map_claude_message(AssistantMessage(content=[TextBlock(text="Hi")], model="claude-sonnet-5-5"))
    assert events == [{"type": "text", "delta": "Hi"}]
    result = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="sess-abc",
        total_cost_usd=0.01,
        usage={"input_tokens": 10, "output_tokens": 5},
        result="Done",
    )
    out = map_claude_message(result)
    assert any(e.get("type") == "result" for e in out)
    assert any(e.get("type") == "usage" for e in out)


@pytest.mark.asyncio
async def test_send_fresh_skips_resume(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic="sk-ant-api")
    runtime = CursorRuntime(settings)
    provider = ClaudeProvider(settings, runtime)
    session = SimpleNamespace(id="chat-1", agent_id="old-session", updated_at="")
    captured: dict = {}

    async def fake_query(*, prompt, options):
        captured["resume"] = options.resume
        captured["mcp"] = options.mcp_servers
        from claude_agent_sdk import ResultMessage

        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="new-sess",
            result="ok",
        )

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    ids: list[str] = []

    async for _ in provider.send(session, "hi", ids.append, fresh=True, no_tools=True):
        pass
    assert captured.get("resume") is None
    assert not captured.get("mcp")


def test_build_providers_claude_available(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic="sk-ant-api")
    runtime = CursorRuntime(settings)
    providers = build_providers(settings, runtime)
    assert providers["claude"].info.available is True


def test_health_claude_provider_info(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic="sk-ant-key")
    providers = build_providers(settings, CursorRuntime(settings))
    assert providers["claude"].info.available is True
