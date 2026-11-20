"""Plan vs API billing per agent (the chat header shows plan limits instead of $) and plan sensors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

agents = pytest.importorskip("custom_components.ai_workspace.agents")
sensor = pytest.importorskip("custom_components.ai_workspace.sensor")
from custom_components.ai_workspace.const import (  # noqa: E402
    CONF_CLAUDE_API_KEY,
    CONF_CODEX_API_KEY,
    CONF_CURSOR_API_KEY,
    MODE_CLAUDE,
)


def _claude(key: str = ""):
    raw = {"mode": MODE_CLAUDE, **({CONF_CLAUDE_API_KEY: key} if key else {})}
    return agents.ClaudeAgent(agents.agent_from_mapping("a1", "", raw), True, None)


def test_claude_billing_follows_the_credential() -> None:
    # No key of its own: the Runtime's credential (a plan sign-in or an API key; plan data decides).
    assert _claude().info.billing == "runtime"
    assert _claude("sk-ant-oat01-abc").info.billing == "plan"
    assert _claude("sk-ant-api03-abc").info.billing == "api_key"
    assert _claude().info.as_dict()["billing"] == "runtime"


def test_codex_and_cursor_billing() -> None:
    codex = agents.agent_from_mapping("c1", "", {"api_provider": "openai", "use_codex_runtime": True})
    assert agents.CodexAgent(codex, True, None).info.billing == "runtime"
    keyed = agents.agent_from_mapping(
        "c2", "", {"api_provider": "openai", "use_codex_runtime": True, CONF_CODEX_API_KEY: "sk-x"}
    )
    assert agents.CodexAgent(keyed, True, None).info.billing == "api_key"
    # Cursor has no plan sign-in: its key (the agent's or the Runtime's) is always an API key.
    for raw in ({"api_provider": "cursor"}, {"api_provider": "cursor", CONF_CURSOR_API_KEY: "key"}):
        cursor = agents.CursorAgent(agents.agent_from_mapping("u1", "Cursor", raw), True, None)
        assert cursor.info.billing == "api_key"


def test_plan_reset_is_an_aware_datetime() -> None:
    # A timestamp sensor needs a datetime; an ISO string left sensor.*_plan_session_reset unavailable.
    when = sensor.reset_datetime(1774918800)
    assert isinstance(when, datetime) and when.tzinfo is not None
    assert when == datetime.fromtimestamp(1774918800, tz=timezone.utc)
    assert sensor.reset_datetime("1774918800") == when
    for empty in (None, "", 0, "x", True):
        assert sensor.reset_datetime(empty) is None


# ---- runtime billing resolved with what the Runtime reports (1.6.1b16) ----------------------------

billing = pytest.importorskip("custom_components.ai_workspace.billing")
from custom_components.ai_workspace.plan_quota import credential_id  # noqa: E402

_SUB = {"claude": {"kind": "subscription", "source": "env-plan", "id": "cRUN"}}


def test_runtime_with_subscription_shows_plan() -> None:
    out = billing.resolve_billing("runtime", "claude", "", _SUB)
    assert out == {"billing": "plan", "billing_source": "runtime", "plan_credential": "cRUN"}


def test_runtime_with_env_api_key_shows_dollars() -> None:
    runtime = {"claude": {"kind": "api_key", "source": "env-api", "id": ""}}
    assert billing.resolve_billing("runtime", "claude", "", runtime)["billing"] == "api_key"
    codex = {"codex": {"kind": "api_key", "source": "env-api", "id": ""}}
    assert billing.resolve_billing("runtime", "codex", "", codex)["billing"] == "api_key"


def test_runtime_with_both_follows_what_the_runtime_reports() -> None:
    # The Runtime resolves plan token vs API key itself (precedence in its app/credentials.py) and
    # reports the one it really uses; Home Assistant follows that report, it does not guess.
    both = billing.credentials_from_health(
        {"credentials": {"claude": {"kind": "subscription", "source": "env-plan", "id": "cRUN"}}}
    )
    assert billing.resolve_billing("runtime", "claude", "", both)["billing"] == "plan"


def test_runtime_unreachable_or_silent_shows_dollars() -> None:
    hass = type("H", (), {"data": {}})()
    billing.store_runtime_credentials(hass, None)  # unreachable
    assert billing.resolve_billing("runtime", "claude", "", billing.cached_runtime_credentials(hass)) == {
        "billing": "unknown",
        "billing_source": "runtime",
        "plan_credential": "",
    }
    billing.store_runtime_credentials(hass, {"ok": True})  # an older Runtime without "credentials"
    assert billing.resolve_billing("runtime", "claude", "", billing.cached_runtime_credentials(hass))["billing"] == "unknown"
    # A subscription row without an ID cannot be attributed: $.
    odd = billing.credentials_from_health({"credentials": {"claude": {"kind": "subscription"}}})
    assert billing.resolve_billing("runtime", "claude", "", odd)["billing"] == "unknown"
    bad = billing.credentials_from_health({"credentials": {"claude": {"kind": "plan?", "id": "x"}}})
    assert billing.resolve_billing("runtime", "claude", "", bad)["billing"] == "unknown"


def test_plan_data_of_another_engine_is_not_used() -> None:
    codex_only = {"codex": {"kind": "subscription", "source": "auth-json", "id": "cCODEX"}}
    assert billing.resolve_billing("runtime", "claude", "", codex_only)["billing"] == "unknown"
    assert billing.resolve_billing("runtime", "codex", "", codex_only)["plan_credential"] == "cCODEX"


def test_own_plan_token_is_its_own_credential() -> None:
    token = "sk-ant-oat01-" + "a" * 40
    out = billing.resolve_billing("plan", "claude", token, _SUB)
    assert out == {"billing": "plan", "billing_source": "agent", "plan_credential": credential_id(token)}
    assert out["plan_credential"] != "cRUN"
    # API keys and cloud providers are untouched.
    assert billing.resolve_billing("api_key", "cursor", "k", _SUB)["billing"] == "api_key"
    assert billing.resolve_billing("api", "openai", "", _SUB)["billing"] == "api"


def test_provider_rows_are_resolved() -> None:
    agent = _claude()
    row = agent.info.as_dict()
    billing.resolve_row(row, agent, {"claude": {"kind": "api_key", "source": "env-api", "id": ""}})
    assert row["billing"] == "api_key" and row["plan_credential"] == ""
    row = agent.info.as_dict()
    billing.resolve_row(row, agent, _SUB)
    assert row["billing"] == "plan" and row["plan_credential"] == "cRUN"
