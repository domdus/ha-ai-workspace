"""Claude SDK agents in the integration: stored data, YAML, runtime routing, and the agent form."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

agents = pytest.importorskip("custom_components.ai_workspace.agents")
from custom_components.ai_workspace import agent_flow, discovery, http  # noqa: E402
from custom_components.ai_workspace.const import (  # noqa: E402
    API_ANTHROPIC,
    COMPOSE_RUNTIME_URLS,
    CONF_CLAUDE_API_KEY,
    CONF_RUNTIME_URL,
    MODE_CLAUDE,
    MODE_CURSOR,
    api_key_url,
    api_model_choices,
    default_api_model,
)
from custom_components.ai_workspace.yaml_config import AGENT_SCHEMA, agent_payload  # noqa: E402


def test_stored_agent_becomes_a_claude_sdk_agent() -> None:
    agent = agents.agent_from_mapping("a1", "", {"mode": MODE_CLAUDE, CONF_CLAUDE_API_KEY: " sk-ant-api03-x "})
    assert agent.mode == MODE_CLAUDE and agent.provider == MODE_CLAUDE
    assert agent.claude_api_key == "sk-ant-api03-x"
    assert agent.label().startswith("Claude SDK")
    provider = agents.ClaudeAgent(agent, True, None)
    assert provider.kind == "claude"
    assert provider.api_key == "sk-ant-api03-x"
    assert provider.info.model == default_api_model(MODE_CLAUDE)


def test_claude_sdk_lists_anthropic_models_only() -> None:
    models = api_model_choices(MODE_CLAUDE)
    assert models[0] == "claude-sonnet-5-5"
    assert all(name.startswith("claude-") and "/" not in name for name in models)
    assert set(api_model_choices(API_ANTHROPIC)) <= set(models)


def test_key_link_goes_to_the_claude_console() -> None:
    assert api_key_url(MODE_CLAUDE) == "https://console.anthropic.com/settings/keys"


def test_old_compose_service_name_is_still_found() -> None:
    assert "http://ai-workspace-runtime:8090" in COMPOSE_RUNTIME_URLS
    assert "http://cursor-sdk:8090" in COMPOSE_RUNTIME_URLS


def test_yaml_claude_agent() -> None:
    row = AGENT_SCHEMA({"provider": "claude", "claude_api_key": "sk-ant-api03-y", "model": "claude-opus-5-5"})
    payload = agent_payload(row, "claude-sdk")
    data = payload["data"]
    assert payload["title"] == "Claude SDK"
    assert data["mode"] == MODE_CLAUDE and data["api_provider"] == MODE_CLAUDE
    assert data[CONF_CLAUDE_API_KEY] == "sk-ant-api03-y"
    assert data["api_key"] == "" and data["cursor_api_key"] == ""
    # A Claude SDK agent read back from YAML is the same kind as one made in the form.
    agent = agents.agent_from_mapping("claude-sdk", payload["title"], data)
    assert agent.mode == MODE_CLAUDE and agent.claude_api_key == "sk-ant-api03-y"


@dataclass
class _Info:
    available: bool
    reason: str | None = None
    notice: object = None
    notice_key: str | None = None
    notice_params: dict | None = None


def test_old_runtime_only_blocks_claude_agents() -> None:
    cursor = SimpleNamespace(kind="cursor", info=_Info(False, "x"))
    claude = SimpleNamespace(kind="claude", info=_Info(False, "x"))
    bucket = {"providers": {"c": cursor, "k": claude}}
    discovery.apply_runtime_to_providers(bucket, "http://r:8090", None, None, claude_reason=discovery.CLAUDE_RUNTIME_OLD)
    assert cursor.info.available is True and cursor.info.reason is None
    assert claude.info.available is False and claude.info.reason == discovery.CLAUDE_RUNTIME_OLD
    discovery.apply_runtime_to_providers(bucket, "http://r:8090", None, None)
    assert claude.info.available is True


def test_runtime_session_is_created_for_the_agent_kind(monkeypatch) -> None:
    sent: list[dict] = []

    class _Resp:
        status = 200

        async def json(self):
            return {"id": "s1"}

        def release(self):
            pass

    class _Http:
        async def post(self, url, json=None, headers=None, timeout=None):
            sent.append(json)
            return _Resp()

    hass = SimpleNamespace(data={http.DOMAIN: {"runtime_url": "http://r:8090"}})
    monkeypatch.setattr(http, "async_get_clientsession", lambda hass_: _Http())
    monkeypatch.setattr(http, "_runtime_headers_for", lambda *a, **k: {})
    assert asyncio.run(http._create_runtime_session(hass, "u1", provider="claude")) == "s1"
    assert asyncio.run(http._create_runtime_session(hass, "u1", provider="bogus")) == "s1"
    assert [item["provider"] for item in sent] == ["claude", "cursor"]
    assert http._is_runtime_provider(SimpleNamespace(kind="claude"))
    assert not http._is_runtime_provider(SimpleNamespace(kind="api"))


# --- agent form validation ------------------------------------------------------------------


def _flow(monkeypatch, health, check=None):
    flow = object.__new__(agent_flow.AgentSubentryFlow)
    flow.hass = SimpleNamespace()
    checked: list[tuple] = []

    async def resolve(hass, url):
        return "http://r:8090"

    async def probe(hass, url):
        return health

    async def check_key(hass, provider, key, base, version):
        checked.append((provider, key))
        return check

    monkeypatch.setattr(agent_flow, "async_resolve_runtime_url", resolve)
    monkeypatch.setattr(agent_flow, "async_runtime_health", probe)
    monkeypatch.setattr("custom_components.ai_workspace.api_provider.async_check_api_key", check_key)
    return flow, checked


def _errors(flow, key):
    return asyncio.run(flow._claude_errors(key, ""))


def test_form_refuses_plan_tokens_without_calling_anthropic(monkeypatch) -> None:
    flow, checked = _flow(monkeypatch, {"claude": True})
    assert _errors(flow, "sk-ant-oat01-abc") == {CONF_CLAUDE_API_KEY: "claude_plan_token"}
    assert checked == []


def test_form_needs_a_key_unless_the_runtime_has_one(monkeypatch) -> None:
    flow, _ = _flow(monkeypatch, {"claude": False})
    assert _errors(flow, "") == {CONF_CLAUDE_API_KEY: "required"}
    flow, checked = _flow(monkeypatch, {"claude": True})
    assert _errors(flow, "") == {}
    assert checked == []


def test_form_checks_the_key_with_anthropic(monkeypatch) -> None:
    flow, checked = _flow(monkeypatch, {"claude": False})
    assert _errors(flow, "sk-ant-api03-good") == {}
    assert checked == [(API_ANTHROPIC, "sk-ant-api03-good")]
    flow, _ = _flow(monkeypatch, {"claude": False}, check="invalid_auth")
    assert _errors(flow, "sk-ant-api03-bad") == {CONF_CLAUDE_API_KEY: "invalid_auth"}
    flow, _ = _flow(monkeypatch, {"claude": False}, check="cannot_connect")
    assert _errors(flow, "sk-ant-api03-x") == {"base": "cannot_connect"}


def test_form_explains_old_and_missing_runtimes(monkeypatch) -> None:
    flow, _ = _flow(monkeypatch, {"cursor": True})
    assert _errors(flow, "sk-ant-api03-x") == {CONF_RUNTIME_URL: "claude_runtime_old"}
    flow, _ = _flow(monkeypatch, None)
    assert _errors(flow, "sk-ant-api03-x") == {CONF_RUNTIME_URL: "no_runtime"}


def test_claude_form_fields() -> None:
    schema = agent_flow._fields_schema("claude", {}, [], models=api_model_choices(MODE_CLAUDE))
    names = {str(key) for key in schema.schema}
    assert {CONF_RUNTIME_URL, "runtime_token", CONF_CLAUDE_API_KEY, "model"} <= names
    assert "api_key" not in names and "cursor_api_key" not in names


def test_runtime_modes_skip_cloud_only_settings() -> None:
    assert agent_flow._title(MODE_CLAUDE, set()) == "Claude SDK"
    assert agent_flow._title(MODE_CLAUDE, {"Claude SDK"}) == "Claude SDK 2"
    assert agent_flow._title(MODE_CURSOR, set()) == "Cursor"
