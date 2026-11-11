"""Claude SDK provider on the runtime: auth, tool rules, prompt shape, event mapping."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.providers import claude as claude_mod
from app.providers.claude import (
    DEFAULT_MODEL,
    MISSING_KEY,
    NOT_INSTALLED,
    PLAN_TOKEN,
    ClaudeProvider,
    claude_subprocess_env,
    is_plan_token,
    mcp_for_sdk,
    resolve_credential,
    resolve_model,
    sdk_effort,
    tool_policy,
    usage_from_result,
    user_content,
)
from app.providers.cursor import CursorRuntime, build_providers
from app.settings import Settings

API_KEY = "sk-ant-api03-runtime-key"
AGENT_KEY = "sk-ant-api03-agent-key"
PLAN = "sk-ant-oat01-plan-token"

needs_sdk = pytest.mark.skipif(
    importlib.util.find_spec("claude_agent_sdk") is None, reason="claude-agent-sdk not installed"
)


def _settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        anthropic_api_key=extra.get("anthropic", ""),
        claude_model=extra.get("claude_model", ""),
        auth_mode="dev",
        host="127.0.0.1",
        port=8090,
    )


def _session(agent_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(id="chat-1", agent_id=agent_id, updated_at="")


def _run(provider: ClaudeProvider, session, message: str = "hi", **kwargs) -> tuple[list[dict], list[str]]:
    ids: list[str] = []

    async def collect():
        return [event async for event in provider.send(session, message, ids.append, **kwargs)]

    return asyncio.run(collect()), ids


# --- credentials ---------------------------------------------------------------------------


def test_agent_key_wins_over_runtime_key(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    assert resolve_credential(settings, AGENT_KEY) == AGENT_KEY
    assert resolve_credential(settings, "  ") == API_KEY
    assert resolve_credential(_settings(tmp_path), "") == ""


def test_plan_tokens_are_recognised() -> None:
    assert is_plan_token(PLAN)
    assert is_plan_token(f"  {PLAN}  ")
    assert not is_plan_token(API_KEY)
    assert not is_plan_token("")


def test_subprocess_env_uses_only_the_api_key(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    env = claude_subprocess_env(settings, AGENT_KEY)
    assert env["ANTHROPIC_API_KEY"] == AGENT_KEY
    # Higher-priority credentials in Claude Code are blanked so nothing else can take over.
    assert env["ANTHROPIC_AUTH_TOKEN"] == ""
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert "ANTHROPIC_BASE_URL" not in env
    assert Path(env["CLAUDE_CONFIG_DIR"]) == settings.data_dir / "claude-config"
    assert Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
    assert API_KEY not in json.dumps(env)


def test_provider_info_needs_a_real_api_key(tmp_path) -> None:
    runtime = CursorRuntime(_settings(tmp_path))
    assert ClaudeProvider(_settings(tmp_path), runtime).info.available is False
    assert ClaudeProvider(_settings(tmp_path), runtime).info.reason == MISSING_KEY
    plan = ClaudeProvider(_settings(tmp_path, anthropic=PLAN), runtime).info
    assert plan.available is False and plan.reason == PLAN_TOKEN
    assert ClaudeProvider(_settings(tmp_path, anthropic=API_KEY), runtime).info.available is True


def test_send_refuses_without_key_and_with_plan_token(tmp_path, monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(claude_mod, "load_mcp_servers", lambda path: calls.append(path) or {})
    provider = ClaudeProvider(_settings(tmp_path), CursorRuntime(_settings(tmp_path)))
    events, _ = _run(provider, _session())
    assert events == [{"type": "error", "message": MISSING_KEY}]
    events, _ = _run(provider, _session(), api_key=PLAN)
    assert events == [{"type": "error", "message": PLAN_TOKEN}]
    assert calls == []  # refused before any MCP or SDK work


def test_runtime_settings_read_app_options(tmp_path, monkeypatch) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"anthropic_api_key": API_KEY, "claude_model": "claude-opus-5-5"}))
    monkeypatch.setenv("ADDON_OPTIONS", str(options))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.anthropic_api_key == API_KEY
    assert settings.claude_model == "claude-opus-5-5"
    monkeypatch.setenv("ANTHROPIC_API_KEY", AGENT_KEY)
    assert Settings.from_env().anthropic_api_key == AGENT_KEY
    assert not hasattr(settings, "openrouter_api_key")
    assert not hasattr(settings, "claude_oauth_token")


# --- model, effort, tools --------------------------------------------------------------------


def test_model_falls_back_from_agent_to_runtime_to_default(tmp_path) -> None:
    assert resolve_model(_settings(tmp_path), "claude-haiku-5-5") == "claude-haiku-5-5"
    assert resolve_model(_settings(tmp_path, claude_model="claude-opus-5-5"), "") == "claude-opus-5-5"
    assert resolve_model(_settings(tmp_path), "") == DEFAULT_MODEL


def test_effort_maps_onto_claude_code_levels() -> None:
    assert sdk_effort("") is None
    assert sdk_effort("default") is None
    assert sdk_effort("fast") == "low"
    assert sdk_effort("high") == "high"
    assert sdk_effort("high_fast") == "medium"


SERVERS = {"home": {"type": "http", "url": "http://x"}}


def test_no_tools_turn_has_no_tools_at_all() -> None:
    policy = tool_policy(no_tools=True, full_tools=True, allow_internet=True, mcp_servers=SERVERS)
    assert policy["tools"] == [] and policy["allowed_tools"] == []
    assert policy["permission_mode"] == "dontAsk"


def test_normal_users_only_get_mcp() -> None:
    policy = tool_policy(no_tools=False, full_tools=False, allow_internet=True, mcp_servers=SERVERS)
    assert policy["tools"] == []
    assert policy["allowed_tools"] == ["mcp__home__*"]
    assert policy["permission_mode"] == "dontAsk"


def test_admin_without_internet_has_files_but_no_shell_or_web() -> None:
    policy = tool_policy(no_tools=False, full_tools=True, allow_internet=False, mcp_servers=SERVERS)
    for name in ("Read", "Write", "Edit", "Glob", "Grep"):
        assert name in policy["tools"] and name in policy["allowed_tools"]
    for name in ("Bash", "WebSearch", "WebFetch"):
        assert name not in policy["tools"] and name not in policy["allowed_tools"]
        assert name in policy["disallowed_tools"]
    assert "mcp__home__*" in policy["allowed_tools"]


def test_admin_with_internet_gets_shell_and_web() -> None:
    policy = tool_policy(no_tools=False, full_tools=True, allow_internet=True, mcp_servers=SERVERS)
    for name in ("Bash", "WebSearch", "WebFetch"):
        assert name in policy["tools"] and name in policy["allowed_tools"]
        assert name not in policy["disallowed_tools"]


@pytest.mark.parametrize("full,internet", [(False, False), (True, False), (True, True)])
def test_subagents_are_never_offered(full, internet) -> None:
    policy = tool_policy(no_tools=False, full_tools=full, allow_internet=internet, mcp_servers=SERVERS)
    assert {"Task", "Agent"} <= set(policy["disallowed_tools"])
    assert not {"Task", "Agent"} & set(policy["tools"])


def test_mcp_types_match_the_sdk() -> None:
    out = mcp_for_sdk(
        {
            "a": {"type": "streamable-http", "url": "http://a"},
            "b": {"url": "http://b"},
            "c": {"type": "sse", "url": "http://c"},
        }
    )
    assert out["a"]["type"] == "http" and out["b"]["type"] == "http" and out["c"]["type"] == "sse"


def test_images_become_content_blocks() -> None:
    assert user_content("hi", None) == "hi"
    assert user_content("hi", [{"name": "x.png", "mime": "image/png", "data": ""}]) == "hi"
    blocks = user_content("what is this?", [{"name": "x.png", "mime": "image/png", "data": "AAAA"}])
    assert blocks[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    assert blocks[-1] == {"type": "text", "text": "what is this?"}


# --- usage ------------------------------------------------------------------------------------


def test_usage_reads_the_result_usage() -> None:
    message = SimpleNamespace(
        usage={"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3},
        total_cost_usd=0.0123,
        model_usage={"claude-sonnet-5-5": {"outputTokens": 5}},
        session_id="s",
    )
    event = usage_from_result(message)
    assert event["prompt_tokens"] == 10 and event["completion_tokens"] == 5
    assert event["cache_read_tokens"] == 7 and event["cache_write_tokens"] == 3
    assert event["cost_usd"] == pytest.approx(0.0123)
    assert event["model"] == "claude-sonnet-5-5"


def test_usage_falls_back_to_model_usage_dicts() -> None:
    message = SimpleNamespace(
        usage=None,
        total_cost_usd=None,
        model_usage={
            "claude-haiku-5-5": {"inputTokens": 50, "outputTokens": 2},
            "claude-sonnet-5-5": {"inputTokens": 900, "outputTokens": 300, "cacheReadInputTokens": 100},
        },
        session_id="s",
    )
    event = usage_from_result(message)
    assert event["model"] == "claude-sonnet-5-5"
    assert event["prompt_tokens"] == 950 and event["completion_tokens"] == 302
    assert event["cache_read_tokens"] == 100


def test_no_usage_means_no_event() -> None:
    assert usage_from_result(SimpleNamespace(usage={}, total_cost_usd=None, model_usage={}, session_id="")) is None


# --- providers --------------------------------------------------------------------------------


def test_build_providers_without_sdk_says_so(tmp_path, monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "claude_agent_sdk" else real(name, *a)
    )
    settings = _settings(tmp_path, anthropic=API_KEY)
    claude = build_providers(settings, CursorRuntime(settings))["claude"]
    assert claude.info.available is False
    assert claude.info.reason == NOT_INSTALLED


@needs_sdk
def test_build_providers_with_sdk(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    assert isinstance(build_providers(settings, CursorRuntime(settings))["claude"], ClaudeProvider)


# --- SDK messages and a full turn (needs claude-agent-sdk) -------------------------------------


def _result(**kw):
    from claude_agent_sdk import ResultMessage

    base = dict(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="new-sess",
        result="ok",
        usage={"input_tokens": 3, "output_tokens": 2},
    )
    base.update(kw)
    return ResultMessage(**base)


@needs_sdk
def test_map_messages() -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, UserMessage

    from app.providers.claude import map_claude_message

    assistant = AssistantMessage(
        content=[
            ThinkingBlock(thinking="hm", signature="x"),
            TextBlock(text="Hello"),
            TextBlock(text="  "),
            ToolUseBlock(id="t1", name="mcp__home__GetLiveContext", input={}),
        ],
        model="claude-sonnet-5-5",
    )
    events = map_claude_message(assistant)
    assert events[0] == {"type": "status", "text": "Thinking..."}
    assert events[1] == {"type": "text", "delta": "Hello"}
    assert events[2]["type"] == "tool" and events[2]["phase"] == "start" and events[2]["id"] == "t1"
    assert len(events) == 3

    results = map_claude_message(
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="boom", is_error=True)])
    )
    assert results == [{"type": "tool", "name": "tool", "phase": "end", "text": "Tool failed", "id": "t1"}]

    done = map_claude_message(_result())
    assert done[0] == {"type": "result", "text": "ok", "run_id": "new-sess", "status": "finished"}
    assert done[1]["type"] == "usage"

    failed = map_claude_message(_result(is_error=True, subtype="error_during_execution", result="Invalid API key"))
    assert failed[0] == {"type": "error", "message": "Invalid API key"}


def _fake_query(captured: dict, messages):
    async def fake_query(*, prompt, options):
        captured["options"] = options
        if isinstance(prompt, str):
            captured["prompt"] = prompt
        else:
            captured["prompt"] = [item async for item in prompt]
        for item in messages():  # list or generator
            if isinstance(item, Exception):
                raise item
            yield item

    return fake_query


@needs_sdk
def test_full_turn_passes_safe_options(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    runtime = CursorRuntime(settings)
    monkeypatch.setattr(runtime, "wrap_mcp", lambda servers, actor="": {"home": {"type": "http", "url": "http://p"}})
    captured: dict = {}
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query(captured, lambda: [_result()]))
    provider = ClaudeProvider(settings, runtime)
    events, ids = _run(
        provider,
        _session("old-sess"),
        "turn on the kitchen light",
        api_key=AGENT_KEY,
        effort="fast",
        mcp={"servers": {"home": {"url": "http://ha/mcp"}}},
    )
    options = captured["options"]
    assert options.resume == "old-sess"
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.model == DEFAULT_MODEL
    assert options.effort == "low"
    assert options.env["ANTHROPIC_API_KEY"] == AGENT_KEY
    assert options.mcp_servers == {"home": {"type": "http", "url": "http://p"}}
    assert options.allowed_tools == ["mcp__home__*"]
    assert options.tools == []
    assert ids == ["new-sess"]
    assert events[0] == {"type": "status", "text": "Thinking..."}
    assert any(e["type"] == "result" for e in events)
    assert any(e["type"] == "usage" for e in events)


@needs_sdk
def test_fresh_turn_does_not_resume_and_no_tools_drops_mcp(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    captured: dict = {}
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query(captured, lambda: [_result()]))
    _run(ClaudeProvider(settings, CursorRuntime(settings)), _session("old-sess"), fresh=True, no_tools=True)
    assert captured["options"].resume is None
    assert not captured["options"].mcp_servers
    assert captured["options"].tools == []


@needs_sdk
def test_images_are_streamed_as_one_user_message(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    captured: dict = {}
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query(captured, lambda: [_result()]))
    image = {"name": "a.png", "mime": "image/png", "data": "AAAA"}
    _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), "what is this?", images=[image], no_tools=True)
    (message,) = captured["prompt"]
    assert message["type"] == "user"
    content = message["message"]["content"]
    assert content[0]["type"] == "image" and content[-1] == {"type": "text", "text": "what is this?"}


@needs_sdk
def test_errors_are_redacted_and_a_missing_result_is_reported(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    provider = ClaudeProvider(settings, CursorRuntime(settings))
    monkeypatch.setattr(
        "claude_agent_sdk.query", _fake_query({}, lambda: [RuntimeError(f"bad key {API_KEY} rejected")])
    )
    events, _ = _run(provider, _session(), no_tools=True)
    assert events[-1]["type"] == "error"
    assert API_KEY not in events[-1]["message"]

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, lambda: []))
    events, ids = _run(provider, _session(), no_tools=True)
    assert events[-1] == {"type": "error", "message": "Claude stopped without an answer."}
    assert ids == []


@needs_sdk
def test_missing_cli_has_a_plain_message(tmp_path, monkeypatch) -> None:
    from claude_agent_sdk import CLINotFoundError

    settings = _settings(tmp_path, anthropic=API_KEY)
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, lambda: [CLINotFoundError("nope")]))
    events, _ = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert events[-1] == {"type": "error", "message": claude_mod.CLI_MISSING}


@needs_sdk
def test_every_option_we_pass_exists_in_the_pinned_sdk(tmp_path) -> None:
    import dataclasses

    from claude_agent_sdk import ClaudeAgentOptions

    fields = {item.name for item in dataclasses.fields(ClaudeAgentOptions)}
    policy = tool_policy(no_tools=False, full_tools=True, allow_internet=True, mcp_servers=SERVERS)
    used = {"cwd", "setting_sources", "strict_mcp_config", "model", "env", "resume", "mcp_servers", "stderr", "effort"}
    assert used | set(policy) <= fields


@needs_sdk
def test_api_errors_show_once_in_plain_words(tmp_path, monkeypatch) -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    settings = _settings(tmp_path, anthropic=API_KEY)
    failed = [
        AssistantMessage(
            content=[TextBlock(text="Invalid API key · Fix external API key")],
            model="<synthetic>",
            error="authentication_failed",
        ),
        _result(is_error=True, subtype="success", result="Invalid API key · Fix external API key", usage={}),
        RuntimeError("Claude Code returned an error result: Invalid API key (exit code: 1)"),
    ]
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, lambda: failed))
    events, _ = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert [e["type"] for e in events] == ["status", "error"]
    assert events[-1]["message"] == claude_mod.API_ERRORS["authentication_failed"]


@needs_sdk
def test_stream_is_read_to_the_end(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    drained: list[bool] = []

    def messages():
        yield _result()
        drained.append(True)

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, messages))
    events, ids = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert drained == [True]
    assert ids == ["new-sess"]
    assert sum(e["type"] == "result" for e in events) == 1
