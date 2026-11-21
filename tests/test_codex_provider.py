"""OpenAI Codex chats on the Runtime: a fake app-server stands in for the openai-codex SDK."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("openai_codex")

from app.plan_quota import normalize_codex_rate_limits  # noqa: E402
from app.providers.codex import (  # noqa: E402
    AUTH_FAILED_CODE,
    CONTEXT_BUDGET,
    CodexProvider,
    tool_policy,
    usage_event,
    map_notification,
    TurnState,
)
from app.providers.cursor import CursorRuntime  # noqa: E402
from test_api import settings as _settings  # noqa: E402

THREAD = "019a0000-0000-7000-8000-000000000001"


def _note(method, payload):
    return SimpleNamespace(method=method, payload=payload)


def _usage(total_in, cached, out, last_in):
    return {
        "tokenUsage": {
            "total": {"inputTokens": total_in, "cachedInputTokens": cached, "outputTokens": out, "totalTokens": total_in + out},
            "last": {"inputTokens": last_in, "cachedInputTokens": cached, "outputTokens": out, "totalTokens": last_in + out},
        }
    }


PLAN = {"rateLimits": {"primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": 1900000000}, "secondary": {"usedPercent": 85, "windowDurationMins": 10080, "resetsAt": 1900500000}}}


class FakeClient:
    """The SDK's JSON-RPC client: only account/rateLimits/read is asked for."""

    def __init__(self, log):
        self.log = log

    async def request(self, method, params, *, response_model):
        self.log.setdefault("requests", []).append(method)
        assert method == "account/rateLimits/read" and params is None
        return response_model.model_validate(PLAN)


class FakeCodex:
    def __init__(self, script, log, fail_start=None):
        self.script = script
        self.log = log
        self.fail_start = fail_start
        self._client = FakeClient(log)

    async def __aenter__(self):
        return self

    async def login_api_key(self, key):
        self.log["key"] = key

    async def thread_start(self, **kwargs):
        if self.fail_start:
            raise RuntimeError(self.fail_start)
        self.log.setdefault("calls", []).append(("start", None, kwargs))
        return self._thread()

    async def thread_resume(self, thread_id, **kwargs):
        self.log.setdefault("calls", []).append(("resume", thread_id, kwargs))
        return self._thread()

    def _thread(self):
        script, log = self.script, self.log

        class Handle:
            def stream(self):
                async def gen():
                    for note in script():
                        yield note

                return gen()

            async def interrupt(self):
                log["interrupted"] = True

        class Thread:
            id = THREAD

            async def turn(self, content, effort=None):
                log["content"] = content
                log["effort"] = effort
                return Handle()

        return Thread()

    async def close(self):
        self.log["closed"] = True


def _provider(tmp_path: Path, script, monkeypatch, *, signed_in=True, fail_start=None):
    settings = _settings(tmp_path)
    runtime = CursorRuntime(settings)
    monkeypatch.setattr(runtime, "wrap_mcp", lambda servers, actor="": {"home": {"type": "http", "url": "http://proxy/x"}})
    log: dict = {}
    provider = CodexProvider(settings, runtime, factory=lambda config: FakeCodex(script, log, fail_start))
    import app.providers.codex as codex_mod

    monkeypatch.setattr(codex_mod, "credential_source", lambda _s: "chatgpt" if signed_in else "none")
    monkeypatch.setattr(codex_mod, "cli_path", lambda: "/bin/codex")
    return provider, runtime, log


def _turn(provider, session, **kwargs):
    ids: list[str] = []

    async def go():
        return [e async for e in provider.send(session, kwargs.pop("message", "Is the light on?"), ids.append, **kwargs)]

    return asyncio.run(go()), ids


def _session(agent_id=None):
    return SimpleNamespace(id="s1", agent_id=agent_id)


def _happy():
    return [
        _note("item/started", {"item": {"type": "mcpToolCall", "id": "t1", "server": "home", "tool": "GetLiveContext"}}),
        _note("item/completed", {"item": {"type": "mcpToolCall", "id": "t1", "server": "home", "tool": "GetLiveContext", "status": "completed"}}),
        _note("item/agentMessage/delta", {"itemId": "m1", "delta": "The light "}),
        _note("item/agentMessage/delta", {"itemId": "m1", "delta": "is on."}),
        _note("item/completed", {"item": {"type": "agentMessage", "id": "m1", "text": "The light is on.", "phase": "final_answer"}}),
        _note("thread/tokenUsage/updated", _usage(12000, 8000, 300, 12000)),
        _note("turn/completed", {"turn": {"status": "completed"}}),
    ]


def test_a_turn_answers_with_tools_usage_and_plan_limits(tmp_path, monkeypatch) -> None:
    provider, runtime, log = _provider(tmp_path, _happy, monkeypatch)
    events, ids = _turn(provider, _session(), effort="fast", mcp={"servers": {"home": {"url": "http://ha/mcp"}}})
    kinds = [e["type"] for e in events]
    assert "tool" in kinds and kinds.count("text") == 2
    result = next(e for e in events if e["type"] == "result")
    assert result == {"type": "result", "text": "The light is on.", "run_id": THREAD, "status": "finished"}
    usage = next(e for e in events if e["type"] == "usage")
    # Anthropic-style: cache apart from input.
    assert usage["prompt_tokens"] == 4000 and usage["cache_read_tokens"] == 8000 and usage["completion_tokens"] == 300
    assert ids == [THREAD] and log["effort"] == "low" and log["closed"]
    start = log["calls"][0]
    assert start[0] == "start" and start[2]["config"]["mcp_servers"] == {"home": {"url": "http://proxy/x"}}
    # Codex sends plan usage outside the turn's stream, so the provider reads it once after the turn.
    assert log["requests"] == ["account/rateLimits/read"]
    snap = runtime.plan_quota.get("codex")
    assert snap["session_percent"] == 42 and snap["week_percent"] == 85 and snap["status"] == "allowed_warning"
    assert any(e["type"] in {"plan_notice", "plan_usage"} for e in events)


def test_the_next_turn_resumes_the_thread(tmp_path, monkeypatch) -> None:
    provider, _runtime, log = _provider(tmp_path, _happy, monkeypatch)
    _turn(provider, _session(THREAD))
    assert log["calls"][0][:2] == ("resume", THREAD)
    # The standing prompt and handoff only go to a new thread.
    assert log["content"] == "Is the light on?"


def test_save_tokens_keeps_a_small_thread_and_drops_a_big_one(tmp_path, monkeypatch) -> None:
    sizes = iter([12_000, CONTEXT_BUDGET + 1, 5_000])

    def script():
        size = next(sizes)
        return [_note("thread/tokenUsage/updated", _usage(size, 0, 10, size)), _note("turn/completed", {"turn": {"status": "completed"}})]

    provider, _runtime, log = _provider(tmp_path, script, monkeypatch)
    for _ in range(3):
        _turn(provider, _session(THREAD), fresh=True)
    assert [call[0] for call in log["calls"]] == ["start", "resume", "start"]


def test_tool_rules_follow_the_user() -> None:
    servers = {"home": {"type": "http", "url": "http://p"}}
    sandbox, config = tool_policy(no_tools=False, full_tools=False, allow_internet=True, servers=servers)
    assert sandbox == "read_only" and config["features"]["shell_tool"] is False and config["web_search"] == "disabled"
    assert config["mcp_servers"] == {"home": {"url": "http://p"}}
    sandbox, config = tool_policy(no_tools=False, full_tools=True, allow_internet=False, servers=servers)
    assert sandbox == "full_access" and config["features"]["shell_tool"] is False
    sandbox, config = tool_policy(no_tools=False, full_tools=True, allow_internet=True, servers=servers)
    assert sandbox == "full_access" and "shell_tool" not in config["features"] and config["web_search"] == "live"
    sandbox, config = tool_policy(no_tools=True, full_tools=True, allow_internet=True, servers=servers)
    assert sandbox == "read_only" and "mcp_servers" not in config
    assert config["project_doc_max_bytes"] == 0 and config["features"]["plugins"] is False


def test_agent_api_key_wins_and_stays_in_memory(tmp_path, monkeypatch) -> None:
    provider, _runtime, log = _provider(tmp_path, _happy, monkeypatch, signed_in=True)
    _turn(provider, _session(), api_key="sk-agent")
    assert log["key"] == "sk-agent"
    # An API key has no plan windows to read.
    assert "requests" not in log


def test_an_expired_chatgpt_sign_in_asks_to_sign_in_again(tmp_path, monkeypatch) -> None:
    expired = (
        "Your access token could not be refreshed because your refresh token has expired. "
        "Please log out and sign in again."
    )
    provider, _runtime, _log = _provider(tmp_path, _happy, monkeypatch, fail_start=expired)
    events, _ = _turn(provider, _session())
    assert events[-1]["code"] == AUTH_FAILED_CODE and "sign in with ChatGPT again" in events[-1]["message"]

    def revoked():
        return [_note("turn/completed", {"turn": {"status": "failed", "error": {"message": "Not logged in: refresh_token invalid_grant"}}})]

    provider, _runtime, _log = _provider(tmp_path, revoked, monkeypatch)
    events, _ = _turn(provider, _session())
    assert events[-1]["code"] == AUTH_FAILED_CODE


def test_no_credential_says_how_to_sign_in(tmp_path, monkeypatch) -> None:
    provider, _runtime, log = _provider(tmp_path, _happy, monkeypatch, signed_in=False)
    events, _ = _turn(provider, _session())
    assert events[0]["type"] == "error" and "Sign in with ChatGPT" in events[0]["message"] and not log


def test_refused_credential_and_full_plan(tmp_path, monkeypatch) -> None:
    def refused():
        return [_note("turn/completed", {"turn": {"status": "failed", "error": {"message": "401", "codexErrorInfo": {"responseStreamFailed": {"httpStatusCode": 401}}}}})]

    provider, _runtime, _log = _provider(tmp_path, refused, monkeypatch)
    events, _ = _turn(provider, _session())
    assert events[-1]["code"] == AUTH_FAILED_CODE

    def full():
        return [_note("turn/completed", {"turn": {"status": "failed", "error": {"message": "limit", "codexErrorInfo": "usageLimitExceeded"}}})]

    provider, _runtime, _log = _provider(tmp_path, full, monkeypatch)
    events, _ = _turn(provider, _session())
    assert events[-1]["code"] == "codex_plan_rejected" and events[-1]["message"]


def test_usage_of_a_resumed_thread_counts_only_this_turn() -> None:
    state = TurnState()
    map_notification("thread/tokenUsage/updated", _usage(50_000, 40_000, 900, 10_000), state)
    map_notification("thread/tokenUsage/updated", _usage(62_000, 50_000, 1_200, 12_000), state)
    usage = usage_event(state, "gpt-5.5-codex", THREAD)
    assert usage["prompt_tokens"] + usage["cache_read_tokens"] == 22_000 and state.context == 12_000


def test_rate_limit_windows_by_duration() -> None:
    snap = normalize_codex_rate_limits({"primary": {"usedPercent": 100, "windowDurationMins": 10080}, "rateLimitReachedType": "rateLimitReached"})
    assert snap["week_percent"] == 100 and snap["session_percent"] is None and snap["status"] == "rejected"
    assert normalize_codex_rate_limits({}) is None


def test_codex_child_env_blanks_the_runtime_secrets(tmp_path, monkeypatch) -> None:
    from app.codex_login import child_env

    for name in ("OPENAI_API_KEY", "CURSOR_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "RUNTIME_TOKEN", "SUPERVISOR_TOKEN"):
        monkeypatch.setenv(name, "secret-" + name)
    settings = _settings(tmp_path)
    env = child_env(settings)
    assert env["OPENAI_API_KEY"] == "" and env["SUPERVISOR_TOKEN"] == "" and env["CLAUDE_CODE_OAUTH_TOKEN"] == ""
    assert env["CODEX_HOME"] == str(settings.data_dir / "codex")
    assert not any(value.startswith("secret-") for value in env.values())


def test_credential_order_agent_key_then_sign_in_then_env(tmp_path) -> None:
    from dataclasses import replace

    from app.codex_login import write_auth
    from app.providers.codex import resolve_credential

    settings = replace(_settings(tmp_path), openai_api_key="sk-env")
    assert resolve_credential(settings) == ("env-api", "sk-env")
    write_auth(settings.codex_auth_path, '{"tokens": {"refresh_token": "r", "access_token": "a"}}')
    assert resolve_credential(settings) == ("chatgpt", "")
    assert resolve_credential(settings, "sk-agent") == ("agent-api", "sk-agent")
    assert oct(settings.codex_auth_path.stat().st_mode & 0o777) == "0o600"
