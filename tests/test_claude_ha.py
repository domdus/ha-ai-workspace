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
    CONF_USE_CLAUDE_RUNTIME,
    MODE_CLAUDE,
    MODE_CURSOR,
    api_key_url,
    api_model_choices,
    default_api_model,
)
from custom_components.ai_workspace.yaml_config import AGENT_SCHEMA, agent_payload  # noqa: E402


def test_stored_agent_becomes_a_claude_sdk_agent() -> None:
    agent = agents.agent_from_mapping("a1", "", {"mode": MODE_CLAUDE, CONF_CLAUDE_API_KEY: " sk-ant-api03-x "})
    # Claude SDK is the Claude (Anthropic) provider with the runtime switch on.
    assert agent.mode == MODE_CLAUDE and agent.provider == API_ANTHROPIC and agent.use_claude_runtime
    assert agent.claude_api_key == "sk-ant-api03-x"
    assert agent.title == "Claude"
    provider = agents.ClaudeAgent(agent, True, None)
    assert provider.kind == "claude"
    assert provider.api_key == "sk-ant-api03-x"
    assert provider.info.model == default_api_model(MODE_CLAUDE)


def test_claude_sdk_lists_anthropic_models_only() -> None:
    models = api_model_choices(MODE_CLAUDE)
    assert models[0] == "claude-sonnet-5-5"
    assert all(name.startswith("claude-") and "/" not in name for name in models)
    assert set(api_model_choices(API_ANTHROPIC)) <= set(models)


def test_agent_choices_single_claude_row() -> None:
    choices = agent_flow._agent_choices()
    assert MODE_CLAUDE not in choices
    assert choices[API_ANTHROPIC] == "Claude (Anthropic)"


def test_cloud_claude_agents_stay_cloud_claude_agents() -> None:
    agent = agents.agent_from_mapping("c", "Claude", {"api_provider": API_ANTHROPIC, "mode": "api", "effort": "high"})
    assert agent.mode == "api" and not agent.use_claude_runtime
    assert agent.effort == "high"


def test_key_link_goes_to_the_claude_console() -> None:
    assert api_key_url(MODE_CLAUDE) == "https://console.anthropic.com/settings/keys"


def test_old_compose_service_name_is_still_found() -> None:
    assert "http://ai-workspace-runtime:8090" in COMPOSE_RUNTIME_URLS
    assert "http://cursor-sdk:8090" in COMPOSE_RUNTIME_URLS


def test_yaml_claude_agent() -> None:
    row = AGENT_SCHEMA({"provider": "claude", "claude_api_key": "sk-ant-api03-y", "model": "claude-opus-5-5"})
    payload = agent_payload(row, "claude-sdk")
    data = payload["data"]
    assert payload["title"] == "Claude"
    # Written in the same shape the migration makes, so YAML and the migration never undo each other.
    assert data["mode"] == MODE_CLAUDE and data["api_provider"] == API_ANTHROPIC
    assert data[CONF_USE_CLAUDE_RUNTIME] is True
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


def test_form_accepts_plan_tokens_without_an_api_key_check(monkeypatch) -> None:
    flow, checked = _flow(monkeypatch, {"claude": False})
    assert _errors(flow, "sk-ant-oat01-abc") == {}
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


def _names(schema) -> set[str]:
    return {str(key) for key in schema.schema}


def _section(schema, name):
    return next(value for key, value in schema.schema.items() if str(key) == name)


def _advanced(schema) -> set[str]:
    return {str(key) for key in _section(schema, "advanced").schema.schema}


def test_claude_form_fields() -> None:
    runtime = agent_flow._fields_schema(
        "cloud", {"api_provider": API_ANTHROPIC, CONF_USE_CLAUDE_RUNTIME: True}, [], models=api_model_choices(MODE_CLAUDE)
    )
    names = _names(runtime)
    assert {agent_flow.SECTION_CLAUDE_RUNTIME, "model", "effort"} <= names
    # The experimental switch sits under Advanced, never at the top of the form.
    assert CONF_USE_CLAUDE_RUNTIME not in names
    assert _advanced(runtime) == {"save_tokens", CONF_USE_CLAUDE_RUNTIME}
    assert "api_key" not in names and "cursor_api_key" not in names
    section = _section(runtime, agent_flow.SECTION_CLAUDE_RUNTIME)
    assert {str(key) for key in section.schema.schema} == {
        CONF_RUNTIME_URL, "runtime_token", CONF_CLAUDE_API_KEY, agent_flow.CONF_CLAUDE_SIGN_IN,
    }
    # Open, so the Plan token field is visible as soon as the switch is on.
    assert section.options.get("collapsed") is False
    cloud = agent_flow._fields_schema("cloud", {"api_provider": API_ANTHROPIC}, [])
    names = _names(cloud)
    assert {"api_key", "model", "effort"} <= names
    assert agent_flow.SECTION_CLAUDE_RUNTIME not in names
    assert _advanced(cloud) == {"save_tokens", "cache_1h", CONF_USE_CLAUDE_RUNTIME}
    # Other cloud providers have no runtime switch.
    assert CONF_USE_CLAUDE_RUNTIME not in _advanced(agent_flow._fields_schema("cloud", {"api_provider": "openai"}, []))


def test_runtime_modes_skip_cloud_only_settings() -> None:
    assert agent_flow._title(API_ANTHROPIC, set()) == "Claude"
    assert agent_flow._title(API_ANTHROPIC, {"Claude"}) == "Claude 2"
    assert agent_flow._title(MODE_CURSOR, set()) == "Cursor"


# --- the whole form step ----------------------------------------------------------------------


class _Entry:
    def __init__(self, subs=()):
        self.data = {}
        self.options = {}
        self.subentries = {sub.subentry_id: sub for sub in subs}


def _form(monkeypatch, *, health=None, editing=None):
    """A Claude (Anthropic) agent form with the runtime and Anthropic faked; returns (flow, calls)."""
    flow = object.__new__(agent_flow.AgentSubentryFlow)
    flow.hass = SimpleNamespace(config=SimpleNamespace(language="en"))
    flow._provider = API_ANTHROPIC
    flow._editing = editing is not None
    flow._current = dict(editing.data) if editing else {}
    entry = _Entry([editing] if editing else [])
    calls: dict[str, list] = {"shown": [], "saved": [], "key_checks": [], "runtime_stored": []}

    async def resolve(hass, url):
        return "http://r:8090"

    async def runtime_health(hass, url):
        return {"cursor": True, "claude": False} if health is None else health

    async def form_url(hass, saved):
        return "http://r:8090", True, True

    async def check_key(hass, provider, key, base, version):
        calls["key_checks"].append(key)
        return None

    async def models(provider, current):
        return None

    async def store_runtime(url, token):
        calls["runtime_stored"].append((url, token))

    monkeypatch.setattr(agent_flow, "async_resolve_runtime_url", resolve)
    monkeypatch.setattr(agent_flow, "async_runtime_health", runtime_health)
    monkeypatch.setattr(agent_flow, "async_runtime_form_url", form_url)
    monkeypatch.setattr(agent_flow, "borrowed_setups", lambda hass: [])
    monkeypatch.setattr(agent_flow, "borrow_by_id", lambda hass, key: None)
    monkeypatch.setattr(agent_flow, "entry_agents", lambda entry: [])
    monkeypatch.setattr("custom_components.ai_workspace.api_provider.async_check_api_key", check_key)
    flow._get_entry = lambda: entry
    flow._get_reconfigure_subentry = lambda: editing
    flow._model_choices = models
    flow._store_runtime = store_runtime

    def show_form(**kwargs):
        calls["shown"].append(kwargs)
        return {"type": "form", **kwargs}

    def create(**kwargs):
        calls["saved"].append(kwargs)
        return {"type": "create_entry", **kwargs}

    def update(entry_, sub, **kwargs):
        calls["saved"].append(kwargs)
        return {"type": "abort", **kwargs}

    flow.async_show_form = show_form
    flow.async_create_entry = create
    flow.async_update_and_abort = update
    return flow, calls


def _step(flow, user_input):
    return asyncio.run(flow._async_step_fields("cloud", user_input))


def _cloud_input(runtime=False, **extra):
    return {"api_key": "", "model": "", "effort": "default", "advanced": {CONF_USE_CLAUDE_RUNTIME: runtime}, **extra}


def test_turning_the_switch_on_shows_the_runtime_fields_before_saving(monkeypatch) -> None:
    # The Runtime already has a credential, so a save would succeed: it must still not save yet.
    flow, calls = _form(monkeypatch, health={"cursor": True, "claude": True})
    result = _step(flow, _cloud_input(runtime=True))
    assert result["type"] == "form" and result["errors"] == {}
    assert calls["saved"] == [] and calls["key_checks"] == []
    shown = _names(result["data_schema"])
    assert agent_flow.SECTION_CLAUDE_RUNTIME in shown and "api_key" not in shown
    # Second submit with the section filled in saves a Claude SDK agent with the Plan token.
    result = _step(
        flow,
        {
            agent_flow.SECTION_CLAUDE_RUNTIME: {CONF_RUNTIME_URL: "", "runtime_token": "", CONF_CLAUDE_API_KEY: "sk-ant-oat01-p"},
            "model": "",
            "effort": "high",
            "advanced": {CONF_USE_CLAUDE_RUNTIME: True},
        },
    )
    assert result["type"] == "create_entry" and result["title"] == "Claude"
    data = result["data"]
    assert data["mode"] == MODE_CLAUDE and data["api_provider"] == API_ANTHROPIC and data[CONF_USE_CLAUDE_RUNTIME]
    assert data[CONF_CLAUDE_API_KEY] == "sk-ant-oat01-p" and data["api_key"] == ""
    assert data["effort"] == "high" and "cache_1h" not in data
    assert calls["runtime_stored"] == [("", "")]


def test_turning_the_switch_off_shows_the_api_key_field_without_an_error(monkeypatch) -> None:
    flow, calls = _form(monkeypatch)
    flow._current = {"api_provider": API_ANTHROPIC, CONF_USE_CLAUDE_RUNTIME: True}
    result = _step(
        flow,
        {
            agent_flow.SECTION_CLAUDE_RUNTIME: {CONF_RUNTIME_URL: "", "runtime_token": "", CONF_CLAUDE_API_KEY: ""},
            "model": "",
            "effort": "default",
            "advanced": {CONF_USE_CLAUDE_RUNTIME: False},
        },
    )
    assert result["type"] == "form" and result["errors"] == {}
    shown = _names(result["data_schema"])
    assert "api_key" in shown and agent_flow.SECTION_CLAUDE_RUNTIME not in shown
    assert calls["saved"] == []


def test_cloud_claude_agents_keep_their_effort(monkeypatch) -> None:
    flow, calls = _form(monkeypatch)
    result = _step(flow, _cloud_input(api_key="sk-ant-api03-k", effort="high_fast"))
    assert result["type"] == "create_entry" and result["title"] == "Claude"
    data = result["data"]
    assert data["mode"] == "api" and data[CONF_USE_CLAUDE_RUNTIME] is False
    assert data["effort"] == "high_fast" and data["api_key"] == "sk-ant-api03-k"
    assert data[CONF_CLAUDE_API_KEY] == "" and "cache_1h" in data
    assert calls["key_checks"] == ["sk-ant-api03-k"] and calls["runtime_stored"] == []


def _sub(title, data):
    return SimpleNamespace(subentry_id="s1", subentry_type="agent", unique_id="u1", title=title, data=data)


def test_flipping_the_switch_keeps_the_name(monkeypatch) -> None:
    runtime = {"api_provider": API_ANTHROPIC, "mode": MODE_CLAUDE, CONF_USE_CLAUDE_RUNTIME: True, "agent_id": "u1"}
    flow, calls = _form(monkeypatch, editing=_sub("Kitchen Claude", runtime))
    _step(flow, {**_cloud_input(api_key="sk-ant-api03-k"), agent_flow.SECTION_CLAUDE_RUNTIME: {}})
    _step(flow, _cloud_input(api_key="sk-ant-api03-k"))
    assert calls["saved"][-1]["title"] == "Kitchen Claude"
    assert calls["saved"][-1]["data"][CONF_USE_CLAUDE_RUNTIME] is False


def test_old_claude_sdk_agents_are_migrated_once(monkeypatch) -> None:
    from custom_components.ai_workspace import _migrate_unified_claude_agent

    old = _sub("Claude SDK", {"api_provider": MODE_CLAUDE, "mode": MODE_CLAUDE, CONF_CLAUDE_API_KEY: "sk-ant-oat01-x"})
    cloud = SimpleNamespace(**{**vars(_sub("Claude", {"api_provider": API_ANTHROPIC, "mode": "api"})), "subentry_id": "s2"})
    entry = _Entry([old, cloud])
    updates: list[tuple] = []

    def update_subentry(entry_, sub, data):
        updates.append((sub.subentry_id, data))
        sub.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_subentry=update_subentry))
    _migrate_unified_claude_agent(hass, entry)
    assert [sid for sid, _ in updates] == ["s1"]
    data = updates[0][1]
    assert data["api_provider"] == API_ANTHROPIC and data["mode"] == MODE_CLAUDE and data[CONF_USE_CLAUDE_RUNTIME]
    assert data[CONF_CLAUDE_API_KEY] == "sk-ant-oat01-x"
    assert agents.agent_from_mapping("a", "Claude SDK", data).use_claude_runtime
    _migrate_unified_claude_agent(hass, entry)
    assert len(updates) == 1


def test_runtime_problems_show_at_the_top_of_the_form(monkeypatch) -> None:
    # Home Assistant draws no errors on fields inside a section, so they must land on "base".
    section = {CONF_RUNTIME_URL: "", "runtime_token": "", CONF_CLAUDE_API_KEY: ""}
    runtime_input = {agent_flow.SECTION_CLAUDE_RUNTIME: section,
                     "model": "", "effort": "default", "advanced": {CONF_USE_CLAUDE_RUNTIME: True}}
    for health, code in ((None, "claude_key_required"), ({"cursor": True}, "claude_runtime_old")):
        flow, calls = _form(monkeypatch, health=health)
        flow._current = {"api_provider": API_ANTHROPIC, CONF_USE_CLAUDE_RUNTIME: True}
        result = _step(flow, runtime_input)
        assert result["type"] == "form" and result["errors"] == {"base": code}
        assert calls["saved"] == []
    assert agent_flow._runtime_section_errors({CONF_RUNTIME_URL: "no_runtime"}) == {"base": "no_runtime"}
    assert agent_flow._runtime_section_errors({CONF_CLAUDE_API_KEY: "invalid_auth"}) == {"base": "invalid_auth"}
    assert agent_flow._runtime_section_errors({"base": "cannot_connect"}) == {"base": "cannot_connect"}


# --- Sign in with Claude --------------------------------------------------------------------------

PLAN = "sk-ant-oat01-" + "x" * 40


def _login_runtime(monkeypatch, *, start_problem="", codes=None):
    """The runtime's sign-in, faked: each start gives a new link; codes maps code -> (token, problem)."""
    calls = {"start": [], "finish": []}

    async def start(hass, base, token):
        calls["start"].append((base, token))
        if start_problem:
            return None, start_problem
        return {"id": f"L{len(calls['start'])}", "url": f"https://claude.com/cai/oauth/authorize?n={len(calls['start'])}"}, ""

    async def finish(hass, base, token, login_id, code):
        calls["finish"].append((login_id, code))
        return (codes or {}).get(code, ("", "code_rejected"))

    monkeypatch.setattr(agent_flow, "async_start_login", start)
    monkeypatch.setattr(agent_flow, "async_finish_login", finish)
    return calls


def _sign_in_input():
    return {
        agent_flow.SECTION_CLAUDE_RUNTIME: {
            CONF_RUNTIME_URL: "", "runtime_token": "", CONF_CLAUDE_API_KEY: "", agent_flow.CONF_CLAUDE_SIGN_IN: True,
        },
        "model": "",
        "effort": "default",
        "advanced": {CONF_USE_CLAUDE_RUNTIME: True},
    }


def _runtime_flow(monkeypatch):
    flow, calls = _form(monkeypatch)
    flow._current = {"api_provider": API_ANTHROPIC, CONF_USE_CLAUDE_RUNTIME: True}
    flow._get_entry().options = {"runtime_token": "saved-secret"}
    return flow, calls


def test_sign_in_with_claude_fills_in_the_plan_token(monkeypatch) -> None:
    flow, calls = _runtime_flow(monkeypatch)
    login = _login_runtime(monkeypatch, codes={"good#s": (PLAN, ""), "typo": ("", "bad_code")})
    result = _step(flow, _sign_in_input())
    assert result["step_id"] == "claude_login" and result["errors"] == {}
    assert result["description_placeholders"]["login_url"].endswith("n=1")
    # The saved Runtime password is used when none is typed.
    assert login["start"] == [("http://r:8090", "saved-secret")]
    assert calls["saved"] == []
    # A mistyped code keeps the same sign-in.
    result = asyncio.run(flow.async_step_claude_login({"code": "typo"}))
    assert result["errors"] == {"base": "claude_code_bad"} and len(login["start"]) == 1
    # A refused code needs a new link.
    result = asyncio.run(flow.async_step_claude_login({"code": "used-already"}))
    assert result["errors"] == {"base": "claude_code_rejected"}
    assert result["description_placeholders"]["login_url"].endswith("n=2")
    result = asyncio.run(flow.async_step_claude_login({"code": "good#s"}))
    assert login["finish"][-1] == ("L2", "good#s")
    assert result["type"] == "create_entry" and result["title"] == "Claude"
    data = result["data"]
    assert data[CONF_CLAUDE_API_KEY] == PLAN and data["mode"] == MODE_CLAUDE and data[CONF_USE_CLAUDE_RUNTIME]
    assert "claude_sign_in" not in data and "code" not in data


def test_sign_in_problems_show_on_the_form(monkeypatch) -> None:
    for problem, shown in (
        ("cli_missing", "claude_login_unavailable"),
        ("runtime_token", "runtime_refused"),
        ("no_link", "claude_login_failed"),
    ):
        flow, calls = _runtime_flow(monkeypatch)
        _login_runtime(monkeypatch, start_problem=problem)
        result = _step(flow, _sign_in_input())
        assert result["type"] == "form" and result["step_id"] == "provider_cloud"
        assert result["errors"] == {"base": shown} and calls["saved"] == []


def test_a_typed_token_wins_over_sign_in(monkeypatch) -> None:
    flow, calls = _runtime_flow(monkeypatch)
    login = _login_runtime(monkeypatch)
    pasted = _sign_in_input()
    pasted[agent_flow.SECTION_CLAUDE_RUNTIME][CONF_CLAUDE_API_KEY] = PLAN
    result = _step(flow, pasted)
    assert result["type"] == "create_entry" and login["start"] == []


def test_sign_in_box_is_in_the_runtime_section() -> None:
    schema = agent_flow._fields_schema("cloud", {"api_provider": API_ANTHROPIC, CONF_USE_CLAUDE_RUNTIME: True}, [])
    section = _section(schema, agent_flow.SECTION_CLAUDE_RUNTIME)
    assert agent_flow.CONF_CLAUDE_SIGN_IN in {str(key) for key in section.schema.schema}


def test_runtime_answers_become_form_problems() -> None:
    from custom_components.ai_workspace import claude_login as client

    assert client._problem(None, {}) == "no_runtime"
    assert client._problem(401, {}) == "runtime_token"
    assert client._problem(404, {}) == "cli_missing"
    assert client._problem(400, {"detail": "code_rejected"}) == "code_rejected"
    assert client._problem(500, {"detail": "<html>"}) == "login_failed"
