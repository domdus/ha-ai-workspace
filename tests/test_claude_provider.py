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
    AUTH_FAILED,
    AUTH_FAILED_CODE,
    DEFAULT_MODEL,
    MISSING_KEY,
    NOT_INSTALLED,
    ClaudeProvider,
    auth_mode,
    claude_subprocess_env,
    is_auth_failure,
    is_plan_token,
    mcp_for_sdk,
    public_error,
    resolve_credential,
    resolve_model,
    runtime_credential,
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
# Claude Code session ids are UUIDs; anything else is a Cursor agent id and is not resumed.
OLD_SESSION = "0b6f3c1e-2d4a-4e8b-9c7d-5a1f2e3b4c6d"

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
        claude_oauth_token=extra.get("oauth", ""),
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


def test_agent_credential_wins_over_runtime_credentials(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY, oauth=PLAN)
    assert resolve_credential(settings, AGENT_KEY) == AGENT_KEY
    assert resolve_credential(_settings(tmp_path, oauth=PLAN), AGENT_KEY) == AGENT_KEY
    assert resolve_credential(_settings(tmp_path, anthropic=API_KEY), PLAN) == PLAN
    assert resolve_credential(settings, "  ") == PLAN  # runtime: Plan token first
    assert resolve_credential(_settings(tmp_path, anthropic=API_KEY), "") == API_KEY
    assert resolve_credential(_settings(tmp_path), "") == ""
    assert runtime_credential(_settings(tmp_path, oauth=f" {PLAN} ")) == PLAN


def test_prefix_decides_the_sign_in() -> None:
    assert is_plan_token(PLAN) and is_plan_token(f"  {PLAN}  ")
    assert not is_plan_token(API_KEY) and not is_plan_token("")
    assert auth_mode(PLAN) == "plan"
    assert auth_mode(API_KEY) == "api"


def test_api_key_env_carries_only_the_api_key(tmp_path) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY, oauth=PLAN)
    env = claude_subprocess_env(settings, AGENT_KEY)
    assert env["ANTHROPIC_API_KEY"] == AGENT_KEY
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert env["ANTHROPIC_AUTH_TOKEN"] == ""
    assert "ANTHROPIC_BASE_URL" not in env
    assert Path(env["CLAUDE_CONFIG_DIR"]) == settings.data_dir / "claude-config"
    assert Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
    assert PLAN not in json.dumps(env) and API_KEY not in json.dumps(env)


def test_plan_env_carries_only_the_plan_token(tmp_path) -> None:
    # ANTHROPIC_API_KEY outranks the OAuth token in Claude Code: it must be blank on Plan chats.
    settings = _settings(tmp_path, anthropic=API_KEY)
    env = claude_subprocess_env(settings, PLAN)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == PLAN
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_AUTH_TOKEN"] == ""
    assert API_KEY not in json.dumps(env)


def test_provider_info_with_either_runtime_credential(tmp_path) -> None:
    runtime = CursorRuntime(_settings(tmp_path))
    missing = ClaudeProvider(_settings(tmp_path), runtime).info
    assert missing.available is False and missing.reason == MISSING_KEY
    assert ClaudeProvider(_settings(tmp_path, oauth=PLAN), runtime).info.available is True
    assert ClaudeProvider(_settings(tmp_path, anthropic=API_KEY), runtime).info.available is True


def test_send_without_any_credential_stops_early(tmp_path, monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(claude_mod, "load_mcp_servers", lambda path: calls.append(path) or {})
    provider = ClaudeProvider(_settings(tmp_path), CursorRuntime(_settings(tmp_path)))
    events, _ = _run(provider, _session())
    assert events == [{"type": "error", "message": MISSING_KEY}]
    assert calls == []


def test_runtime_settings_read_env_and_old_app_options(tmp_path, monkeypatch) -> None:
    # 1.6.0b12: the App has no Claude fields. Docker uses env vars; old option values still work quietly.
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps({"anthropic_api_key": API_KEY, "claude_oauth_token": PLAN, "claude_model": "claude-opus-5-5"})
    )
    monkeypatch.setenv("ADDON_OPTIONS", str(options))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.anthropic_api_key == API_KEY
    assert settings.claude_model == "claude-opus-5-5"
    # The old options Plan token is only moved into the sign-in (app.legacy_options), never used as is.
    assert settings.claude_oauth_token == ""
    assert settings.legacy_claude_token == PLAN
    assert settings.legacy_claude_options == ("claude_oauth_token", "anthropic_api_key", "claude_model")
    assert PLAN not in repr(settings) and API_KEY not in repr(settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", AGENT_KEY)
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-env")
    env = Settings.from_env()
    assert env.anthropic_api_key == AGENT_KEY
    assert env.claude_model == "claude-haiku-5-5"
    assert env.claude_oauth_token == "sk-ant-oat01-env"
    assert env.legacy_claude_options == ("claude_oauth_token",)
    assert not hasattr(settings, "openrouter_api_key")


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
    assert failed[0] == {"type": "error", "message": AUTH_FAILED, "code": AUTH_FAILED_CODE}
    other = map_claude_message(_result(is_error=True, subtype="error_during_execution", result="Overloaded"))
    assert other[0] == {"type": "error", "message": "Overloaded"}


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
        _session(OLD_SESSION),
        "turn on the kitchen light",
        api_key=AGENT_KEY,
        effort="fast",
        mcp={"servers": {"home": {"url": "http://ha/mcp"}}},
    )
    options = captured["options"]
    assert options.resume == OLD_SESSION
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
    assert events[-1] == {"type": "error", "message": AUTH_FAILED, "code": AUTH_FAILED_CODE}


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


@needs_sdk
def test_plan_turn_reaches_claude_code_with_the_plan_token(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    captured: dict = {}
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query(captured, lambda: [_result()]))
    events, ids = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), api_key=PLAN, no_tools=True)
    env = captured["options"].env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == PLAN and env["ANTHROPIC_API_KEY"] == ""
    assert ids == ["new-sess"] and any(e["type"] == "result" for e in events)


def _worker_event(job_id: str) -> dict:
    return {
        "type": "usage",
        "worker": True,
        "engine": "claude",
        "model": "claude-sonnet-5-5",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cost_usd": 0.01,
        "run_id": f"worker:{job_id}",
    }


@needs_sdk
def test_worker_usage_from_the_mcp_proxy_reaches_the_turn(tmp_path, monkeypatch) -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    settings = _settings(tmp_path, anthropic=API_KEY)
    runtime = CursorRuntime(settings)
    proxy = runtime.proxy

    def messages():
        # The agent polls agent_job over the proxy while it streams, and once more just before it ends.
        proxy.note_worker_usage("chat-1", _worker_event("j1"))
        proxy.note_worker_usage("other-chat", _worker_event("x"))
        yield AssistantMessage(content=[TextBlock(text="Started the job.")], model="claude-sonnet-5-5")
        proxy.note_worker_usage("chat-1", _worker_event("j1"))  # same job polled again
        yield _result()
        proxy.note_worker_usage("chat-1", _worker_event("j2"))

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, messages))
    events, _ = _run(ClaudeProvider(settings, runtime), _session(), no_tools=True)
    workers = [e for e in events if e.get("worker")]
    # A poll after the queue was drained is passed on again; the integration stores each run_id once.
    assert [e["run_id"] for e in workers] == ["worker:j1", "worker:j1", "worker:j2"]
    own = [e for e in events if e["type"] == "usage" and not e.get("worker")]
    assert len(own) == 1 and own[0]["run_id"] == "new-sess"
    assert proxy.take_worker_usage("chat-1") == []
    assert [e["run_id"] for e in proxy.take_worker_usage("other-chat")] == ["worker:x"]


@needs_sdk
def test_worker_usage_still_counts_when_the_turn_fails(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, anthropic=API_KEY)
    runtime = CursorRuntime(settings)

    def messages():
        runtime.proxy.note_worker_usage("chat-1", _worker_event("j3"))
        yield RuntimeError("connection dropped")

    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, lambda: list(messages())))
    events, _ = _run(ClaudeProvider(settings, runtime), _session(), no_tools=True)
    assert [e["type"] for e in events] == ["status", "error", "usage"]
    assert events[-1]["run_id"] == "worker:j3"


# --- expired or revoked credential ------------------------------------------------------------

_REFUSED = (
    'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"OAuth token has expired."}}',
    "Invalid API key · Please run /login",
    "OAuth token has been revoked",
    "invalid x-api-key",
    "Failed to authenticate. API Error: 401",
    "Not logged in · Please run /login",
)
_NOT_REFUSED = (
    "Overloaded",
    "API Error: 529 overloaded_error",
    "rate_limit_error: Number of requests has exceeded your rate limit",
    "MCP server home: HTTP 401 Unauthorized",
    "Your credit balance is too low",
    "",
)


@pytest.mark.parametrize("text", _REFUSED)
def test_refused_credentials_are_recognised(text) -> None:
    assert is_auth_failure(text)


@pytest.mark.parametrize("text", _NOT_REFUSED)
def test_other_failures_are_not_a_sign_in_problem(text) -> None:
    assert not is_auth_failure(text)


def test_auth_failure_signals_from_the_sdk() -> None:
    assert is_auth_failure(api_error="authentication_failed")
    assert is_auth_failure(status=401)
    assert not is_auth_failure(api_error="rate_limit", status=429)


def test_public_error_turns_a_refused_credential_into_the_sign_in_hint() -> None:
    assert public_error(RuntimeError("Command failed: API Error: 401 authentication_error"), PLAN) == AUTH_FAILED
    error = RuntimeError("Command failed with exit code 1")
    error.stderr = "Invalid API key · Please run /login"
    assert public_error(error, PLAN) == AUTH_FAILED
    error = RuntimeError("Claude Code returned an error result")
    error.api_error_status = 401
    assert public_error(error, PLAN) == AUTH_FAILED
    # Anything else stays as it was, without the secret.
    assert public_error(RuntimeError(f"boom {PLAN}"), PLAN) == "boom [redacted]"
    assert "sign in" in AUTH_FAILED.lower() and PLAN not in AUTH_FAILED


@needs_sdk
def test_expired_sign_in_result_carries_the_code(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, oauth=PLAN)
    expired = [_result(is_error=True, subtype="success", result="API Error: 401", api_error_status=401, usage={})]
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query({}, lambda: expired))
    events, _ = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert events[-1] == {"type": "error", "message": AUTH_FAILED, "code": AUTH_FAILED_CODE}


@needs_sdk
def test_cli_crash_after_a_refused_credential_on_stderr(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, oauth=PLAN)

    async def fake_query(*, prompt, options):
        options.stderr("Error: OAuth token has expired. Please run /login")
        raise RuntimeError("Command failed with exit code 1 (exit code: 1)")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    events, _ = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert events[-1] == {"type": "error", "message": AUTH_FAILED, "code": AUTH_FAILED_CODE}


@needs_sdk
def test_other_cli_crash_keeps_its_message(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, oauth=PLAN)

    async def fake_query(*, prompt, options):
        options.stderr("some debug line")
        raise RuntimeError("Command failed with exit code 2")
        yield  # pragma: no cover

    monkeypatch.setattr("claude_agent_sdk.query", fake_query)
    events, _ = _run(ClaudeProvider(settings, CursorRuntime(settings)), _session(), no_tools=True)
    assert events[-1] == {"type": "error", "message": "Command failed with exit code 2"}


@needs_sdk
def test_save_tokens_keeps_the_session_until_it_grows(tmp_path, monkeypatch) -> None:
    """Save tokens once started a new Claude session every turn: no memory of tool results, no cache."""
    from claude_agent_sdk import AssistantMessage, TextBlock

    from app.providers.claude import CONTEXT_BUDGET

    settings = _settings(tmp_path, anthropic=API_KEY)
    provider = ClaudeProvider(settings, CursorRuntime(settings))
    sizes = iter([12_000, CONTEXT_BUDGET + 1, 9_000])

    def turn():
        call = {"input_tokens": 50, "cache_read_input_tokens": next(sizes) - 50}
        return [AssistantMessage(content=[TextBlock(text="ok")], model="m", usage=call), _result()]

    captured: dict = {}
    monkeypatch.setattr("claude_agent_sdk.query", _fake_query(captured, turn))
    _run(provider, _session(OLD_SESSION), fresh=True)
    assert captured["options"].resume is None  # not measured yet (e.g. after a restart): may be any size
    _run(provider, _session(OLD_SESSION), fresh=True)
    assert captured["options"].resume == OLD_SESSION  # 12k is small
    _run(provider, _session(OLD_SESSION), fresh=True)
    assert captured["options"].resume is None  # grew past the budget: new session with the HA handoff
    assert provider.keeps_session("s", fresh=False)


def test_context_is_read_from_main_model_calls_only() -> None:
    from types import SimpleNamespace

    from app.providers.claude import context_tokens

    call = {"input_tokens": 10, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 90, "output_tokens": 5}
    assert context_tokens(SimpleNamespace(usage=call, parent_tool_use_id=None)) == 1100
    assert context_tokens(SimpleNamespace(usage=call, parent_tool_use_id="t1")) == 0
    assert context_tokens(SimpleNamespace(usage=None, parent_tool_use_id=None)) == 0
