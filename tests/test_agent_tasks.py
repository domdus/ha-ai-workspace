"""Agent tasks: ai_workspace.run_task, its tool limits, and the automations of the Tasks page."""

from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest
import voluptuous as vol
import yaml

from custom_components.ai_workspace import tasks
from custom_components.ai_workspace.task_guard import (
    is_read_tool,
    loop_refusal,
    task_refusal,
    task_tool_offered,
)
from custom_components.ai_workspace.tasks import (
    RUN_TASK_SCHEMA,
    RunResult,
    build_automation,
    parse_automation,
    parse_schedule,
    task_key,
    tool_policy,
)

try:  # Home Assistant 2026.x validates with probatio; cv helpers raise its Invalid.
    import probatio

    INVALID = (vol.Invalid, probatio.Invalid)
except ImportError:
    INVALID = (vol.Invalid,)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "ai_workspace"
READ_ONLY = tool_policy(False)
CHANGES = tool_policy(True)


# --- Service schema -----------------------------------------------------------------------------


def test_schema_defaults() -> None:
    data = RUN_TASK_SCHEMA({"prompt": "Anything open?"})
    assert data == {
        "prompt": "Anything open?",
        "task_name": "",
        "agent": "",
        "chat": "none",
        "notify": "",
        "allow_changes": False,
        "timeout": 600,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"prompt": "   "},
        {"prompt": "x", "chat": "task"},
        {"prompt": "x", "chat": "somewhere"},
        {"prompt": "x", "timeout": 1},
        {"prompt": "x", "timeout": 99999},
    ],
)
def test_schema_refuses(bad) -> None:
    with pytest.raises(INVALID):
        RUN_TASK_SCHEMA(bad)


def test_schema_task_chat_needs_name() -> None:
    data = RUN_TASK_SCHEMA({"prompt": "x", "chat": "task", "task_name": "Morning", "allow_changes": "on"})
    assert data["chat"] == "task" and data["allow_changes"] is True


def test_services_yaml_matches_schema_and_translations() -> None:
    services = yaml.safe_load((BASE / "services.yaml").read_text())
    fields = set(services["run_task"]["fields"])
    assert fields == {"prompt", "task_name", "agent", "chat", "notify", "allow_changes", "timeout"}
    assert services["run_task"]["fields"]["prompt"]["required"] is True
    options = services["run_task"]["fields"]["chat"]["selector"]["select"]["options"]
    for path in sorted((BASE / "translations").glob("*.json")):
        found = json.loads(path.read_text(encoding="utf-8"))
        run = found["services"]["run_task"]
        assert set(run["fields"]) == fields, path.stem
        assert all(run["fields"][name]["name"] for name in fields), path.stem
        assert set(found["selector"]["task_chat"]["options"]) == set(options), path.stem


def test_service_names_are_translated() -> None:
    english = json.loads((BASE / "translations" / "en.json").read_text())["services"]["run_task"]["name"]
    for path in sorted((BASE / "translations").glob("*.json")):
        if path.stem == "en":
            continue
        assert json.loads(path.read_text(encoding="utf-8"))["services"]["run_task"]["name"] != english, path.stem


# --- Read-only tools ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        "GetLiveContext",
        "GetDateTime",
        "ha_get_state",
        "ha_search_entities",
        "ha_get_history",
        "ha_get_logbook",
        "ha_config_get_automation",
        "home-assistant__ha_get_overview",
        "list_chats",
        "read_chat",
        "todo_get_items",
    ],
)
def test_read_tools_pass_read_only(tool) -> None:
    assert is_read_tool(tool)
    assert task_refusal(tool, {}, READ_ONLY) == ""
    assert task_tool_offered(tool, READ_ONLY)


@pytest.mark.parametrize(
    "tool",
    [
        "HassTurnOn",
        "HassTurnOff",
        "HassLightSet",
        "ha_call_service",
        "ha_config_set_helper",
        "ha_restart",
        "remember",
        "something_unknown",
        "HassListAddItem",
    ],
)
def test_writes_are_refused_read_only(tool) -> None:
    assert "read-only" in task_refusal(tool, {"domain": "light", "service": "turn_on"}, READ_ONLY)
    assert not task_tool_offered(tool, READ_ONLY)
    assert task_refusal(tool, {"domain": "light", "service": "turn_on"}, CHANGES) == ""
    assert task_tool_offered(tool, CHANGES)


def test_normal_chat_has_no_limits() -> None:
    assert task_refusal("ha_config_set_automation", {}, None) == ""
    assert task_tool_offered("ha_call_service", None)


# --- Loop protection ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("ha_config_set_automation", {"config": {"alias": "x"}}),
        ("ha_config_remove_automation", {"identifier": "automation.x"}),
        ("ha_config_set_script", {"script_id": "x"}),
        ("ha_config_remove_script", {"script_id": "x"}),
        ("ha_call_service", {"domain": "ai_workspace", "service": "run_task"}),
        ("ha_call_service", {"service": "ai_workspace.run_task"}),
        ("ha_call_service", {"domain": "automation", "service": "trigger"}),
        ("ai_workspace_run_task", {}),
        ("create_automation", {}),
    ],
)
def test_loop_protection_ignores_allow_changes(tool, args) -> None:
    assert loop_refusal(tool, args)
    assert "agent task" in task_refusal(tool, args, CHANGES)
    assert "agent task" in task_refusal(tool, args, READ_ONLY)


def test_loop_protection_leaves_other_calls() -> None:
    assert not loop_refusal("ha_call_service", {"domain": "light", "service": "turn_on"})
    assert not loop_refusal("ha_config_get_automation", {"identifier": "automation.x"})
    assert not loop_refusal("HassTurnOn", {"name": "Kitchen"})
    assert not loop_refusal("ha_call_service", json.dumps({"domain": "cover", "service": "close_cover"}))


def test_guard_ships_identical_in_runtime() -> None:
    home = (BASE / "task_guard.py").read_text()
    assert home == (ROOT / "ai_workspace" / "app" / "task_guard.py").read_text()


def test_cloud_tool_loop_refuses_under_policy() -> None:
    from custom_components.ai_workspace import api_provider

    calls = []

    class Mcp:
        def original_name(self, name):
            return name

        async def call_tool(self, name, args):
            calls.append(name)
            return {"content": []}

    async def run():
        token = api_provider._TOOL_POLICY.set(READ_ONLY)
        try:
            return await api_provider.ApiProvider._invoke_tool(SimpleNamespace(), Mcp(), "HassTurnOn", {}, None)
        finally:
            api_provider._TOOL_POLICY.reset(token)

    result = asyncio.run(run())
    assert result["isError"] is True
    assert "read-only" in result["content"][0]["text"]
    assert calls == []


def test_runtime_proxy_keeps_policy_per_turn() -> None:
    from app.mcp_proxy import McpProxy

    proxy = McpProxy.__new__(McpProxy)
    proxy.actors = OrderedDict()
    proxy.note_actor("chat-1", "user-a", "Claude", "key", tool_policy=READ_ONLY)
    assert proxy.policies["chat-1"] == READ_ONLY
    # A normal chat turn in the same chat lifts the limits again.
    proxy.note_actor("chat-1", "user-a", "Claude", "key")
    assert "chat-1" not in proxy.policies


def test_runtime_request_accepts_policy() -> None:
    from app.main import ChatRequest

    body = ChatRequest(message="hi", tool_policy=READ_ONLY)
    assert body.tool_policy == READ_ONLY
    assert ChatRequest(message="hi").tool_policy is None


def test_agent_events_pass_policy_to_cloud_agents() -> None:
    from custom_components.ai_workspace import http
    from custom_components.ai_workspace.const import DOMAIN

    seen = {}

    class Provider:
        kind = "api"

        async def send(self, session, message, on_agent_id, **kwargs):
            seen.update(kwargs)
            yield {"type": "text", "delta": "ok"}

    hass = SimpleNamespace(data={DOMAIN: {"store": object()}})
    session = SimpleNamespace(id="s", agent_id=None)

    async def run():
        return [event async for event in http.async_agent_events(hass, "u", session, Provider(), "hi", tool_policy=READ_ONLY)]

    assert asyncio.run(run()) == [{"type": "text", "delta": "ok"}]
    assert seen["tool_policy"] == READ_ONLY


# --- Agent choice -------------------------------------------------------------------------------


def _provider(agent_id: str, title: str, available: bool = True, kind: str = "api"):
    return SimpleNamespace(
        kind=kind,
        model="",
        info=SimpleNamespace(id=agent_id, title=title, label=title, available=available, reason="off"),
    )


def test_agent_chain(monkeypatch) -> None:
    one, two, off = _provider("a1", "OpenAI"), _provider("a2", "Claude"), _provider("a3", "Off", False)
    data = {"providers": {"a1": one, "a2": two, "a3": off}, "settings": SimpleNamespace(default_agent="a2")}
    hass = SimpleNamespace()
    # Fallback off: exactly one agent, never the others as a fallback.
    assert tasks.task_agent_chain(hass, data, "") == [two]
    assert tasks.task_agent_chain(hass, data, "a1") == [one]
    assert tasks.task_agent_chain(hass, data, "openai") == [one]
    with pytest.raises(Exception, match="no agent"):
        tasks.task_agent_chain(hass, data, "nobody")


def _subentries():
    """Agents in creation order, like the observed setup: OpenAI, Ollama, Gemini, Cursor, Claude."""
    return OrderedDict(
        (
            ("o", _provider("o", "OpenAI")),
            ("l", _provider("l", "Ollama")),
            ("g", _provider("g", "Gemini")),
            ("cu", _provider("cu", "Cursor", kind="cursor")),
            ("cl", _provider("cl", "Claude", kind="claude")),
        )
    )


def test_last_used_picks_first_runtime_agent_without_fallback() -> None:
    providers = _subentries()
    # Options never saved: no fallback_* keys, default agent "Last used" (stored as "").
    data = {"providers": providers, "settings": SimpleNamespace(default_agent=""), "runtime_version": tasks.TASK_RUNTIME_MIN}
    hass = SimpleNamespace()
    assert tasks.task_agent_chain(hass, data, "") == [providers["cl"]]
    assert not tasks.task_fallback_on(data)
    # Claude signed out: Cursor is next in the documented order, still alone.
    providers["cl"].info.available = False
    assert tasks.task_agent_chain(hass, data, "") == [providers["cu"]]
    # No Runtime agent can take it: the first agent that can.
    providers["cu"].info.available = False
    assert tasks.task_agent_chain(hass, data, "") == [providers["o"]]
    # A too old Runtime does not count as a Runtime agent for tasks.
    providers["cl"].info.available = True
    data["runtime_version"] = "1.6.1b5"
    assert tasks.task_agent_chain(hass, data, "") == [providers["o"]]


def test_unsaved_or_off_fallback_never_switches() -> None:
    providers = _subentries()
    hass = SimpleNamespace()
    for settings in (
        SimpleNamespace(default_agent=""),  # never saved
        SimpleNamespace(default_agent="", fallback_enabled=False, fallback_agents=("o", "g", "cu")),
        SimpleNamespace(default_agent="", fallback_enabled=True, fallback_agents=()),  # on, but no list
    ):
        data = {"providers": providers, "settings": settings, "runtime_version": tasks.TASK_RUNTIME_MIN}
        assert len(tasks.task_agent_chain(hass, data, "")) == 1
        assert tasks.task_agent_chain(hass, data, "g") == [providers["g"]]


def test_fallback_on_uses_saved_order_and_named_agent_first() -> None:
    providers = _subentries()
    settings = SimpleNamespace(default_agent="", fallback_enabled=True, fallback_agents=("cu", "o", "g"))
    data = {"providers": providers, "settings": settings}
    hass = SimpleNamespace()
    assert tasks.task_agent_chain(hass, data, "") == [providers["cu"], providers["o"], providers["g"]]
    assert tasks.task_agent_chain(hass, data, "o") == [providers["o"], providers["cu"], providers["g"]]
    # A named agent outside the list starts, then the list follows.
    assert tasks.task_agent_chain(hass, data, "cl") == [providers["cl"], providers["cu"], providers["o"], providers["g"]]


def test_old_runtime_gets_no_tasks() -> None:
    claude = _provider("c", "Claude", kind="claude")
    assert "Update the AI Workspace Runtime" in tasks._not_ready({"runtime_version": "1.6.1b5"}, claude)
    assert tasks._not_ready({"runtime_version": tasks.TASK_RUNTIME_MIN}, claude) == ""
    assert tasks._not_ready({"runtime_version": "1.6.0"}, _provider("x", "Cloud")) == ""


# --- One run ------------------------------------------------------------------------------------


class _State:
    def __init__(self) -> None:
        self.tasks: dict = {}
        self.running: set = set()

    async def load(self) -> None:
        return None

    def get(self, key):
        return dict(self.tasks.get(key) or {})

    async def update(self, key, **values):
        self.tasks.setdefault(key, {}).update(values)


class _Store:
    def __init__(self) -> None:
        self.messages: list = []
        self.deleted: list = []

    def add_message(self, session_id, role, content, events="[]"):
        self.messages.append((session_id, role, content))

    def list_messages(self, session_id):
        return []


def _hass(store):
    from custom_components.ai_workspace.const import DOMAIN

    async def executor(fn, *args):
        return fn(*args)

    return SimpleNamespace(
        data={DOMAIN: {"store": store, "providers": {}, "chat_jobs": set(), "settings": None}},
        async_add_executor_job=executor,
        config=SimpleNamespace(language="de", external_url="", internal_url=""),
    )


@pytest.fixture
def run_env(monkeypatch):
    state = _State()
    store = _Store()
    hass = _hass(store)
    turns: list = []
    sessions: list = []
    monkeypatch.setattr(tasks, "task_state", lambda hass: state)

    async def user(hass, caller):
        return "owner"

    async def open_session(hass, data, provider, user_id, chat_id, title):
        session = SimpleNamespace(id=chat_id or f"s{len(sessions)}", title=title, provider="")
        sessions.append((session.id, title))
        return session

    async def drop(hass, data, user_id, session_id):
        store.deleted.append(session_id)

    monkeypatch.setattr(tasks, "_task_user", user)
    monkeypatch.setattr(tasks, "_open_session", open_session)
    monkeypatch.setattr(tasks, "_drop_session", drop)
    return SimpleNamespace(state=state, store=store, hass=hass, turns=turns, sessions=sessions, monkeypatch=monkeypatch)


def _turns(env, *answers):
    queue = list(answers)

    async def one_turn(hass, data, provider, session, user_id, outbound, question, handoff, policy, usage):
        env.turns.append({"provider": provider, "outbound": outbound, "policy": policy, "question": question})
        tasks.add_usage(usage, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost_usd": 0.001})
        return queue.pop(0)

    env.monkeypatch.setattr(tasks, "_one_turn", one_turn)


def test_run_returns_payload_and_keeps_task_chat(run_env) -> None:
    agent = _provider("a1", "OpenAI")
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [agent])
    _turns(run_env, tasks._Turn(answer="All windows are closed."), tasks._Turn(answer="Still closed."))
    params = RUN_TASK_SCHEMA({"prompt": "Anything open?", "task_name": "Evening check", "chat": "task"})

    first = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert first["status"] == "ok"
    assert first["response"] == "All windows are closed."
    assert first["agent"] == "OpenAI"
    assert first["chat_id"] == "s0"
    assert first["usage"] == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "cost_usd": 0.001}
    assert set(first) == {"status", "response", "agent", "chat_id", "duration", "usage"}
    sent = run_env.turns[0]
    assert sent["policy"] == {"task": True, "read_only": True}
    assert "Read-only" in sent["outbound"] and sent["outbound"].endswith("Anything open?")
    assert sent["question"] == "Anything open?"
    assert run_env.store.deleted == []

    second = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert second["chat_id"] == "s0"
    assert run_env.sessions == [("s0", "Evening check"), ("s0", "Evening check")]
    row = run_env.state.tasks[task_key("Evening check")]
    assert row["last_status"] == "ok" and row["chat_id"] == "s0"


def test_run_without_chat_starts_fresh_and_cleans_up(run_env) -> None:
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [_provider("a1", "OpenAI")])
    _turns(run_env, tasks._Turn(answer="Done."))
    params = RUN_TASK_SCHEMA({"prompt": "Turn off the lights", "allow_changes": True})
    result = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert result["status"] == "ok" and result["chat_id"] is None
    assert run_env.turns[0]["policy"] == {"task": True, "read_only": False}
    assert "no memory of earlier runs" in run_env.turns[0]["outbound"]
    assert run_env.store.deleted == ["s0"]


def test_unreachable_agent_falls_back(run_env) -> None:
    first, second = _provider("a1", "Ollama"), _provider("a2", "OpenAI")
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [first, second])
    _turns(run_env, tasks._Turn(error="Ollama is down", connection=True), tasks._Turn(answer="Sunny."))
    result = asyncio.run(tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "Weather?"}))).payload()
    assert result["status"] == "ok" and result["agent"] == "OpenAI" and result["response"] == "Sunny."


def test_agent_error_is_reported(run_env) -> None:
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [_provider("a1", "OpenAI")])
    _turns(run_env, tasks._Turn(error="Bad key"))
    result = asyncio.run(tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "x"}))).payload()
    assert result["status"] == "error" and result["response"] == "Bad key"


def test_same_task_does_not_run_twice(run_env) -> None:
    run_env.state.running.add(task_key("Briefing"))
    result = asyncio.run(
        tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "x", "task_name": "Briefing"}))
    ).payload()
    assert result["status"] == "busy"
    assert run_env.turns == []


def test_timeout(run_env) -> None:
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [_provider("a1", "OpenAI")])

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    run_env.monkeypatch.setattr(tasks, "_one_turn", slow)
    params = RUN_TASK_SCHEMA({"prompt": "x", "task_name": "Slow"})
    params["timeout"] = 0.05
    result = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert result["status"] == "timeout"
    assert run_env.state.tasks[task_key("Slow")]["last_status"] == "timeout"
    assert not run_env.state.running


def test_payload_without_usage() -> None:
    payload = RunResult(status="error", error="No agent").payload()
    assert payload["response"] == "No agent"
    assert payload["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": None}


def test_short_result_for_push() -> None:
    assert tasks.short_result("a\n\n\n\nb") == "a\n\nb"
    long = tasks.short_result("word " * 400, 50)
    assert len(long) <= 50 and long.endswith("…")


# --- Automations --------------------------------------------------------------------------------


def _form(**extra):
    form = {
        "name": "Morning briefing",
        "prompt": "Weather, calendar, open windows.",
        "schedule": {"kind": "daily", "time": "7:05"},
        "target": "chat",
    }
    form.update(extra)
    return form


def test_build_daily_task() -> None:
    config = build_automation(_form())
    assert config["alias"] == "Morning briefing"
    assert config["triggers"] == [{"trigger": "time", "at": "07:05:00"}]
    assert config["conditions"] == []
    assert config["mode"] == "single"
    assert config["actions"] == [
        {
            "action": "ai_workspace.run_task",
            "data": {
                "task_name": "Morning briefing",
                "prompt": "Weather, calendar, open windows.",
                "chat": "task",
                "allow_changes": False,
            },
        }
    ]


def test_build_weekly_push_and_interval() -> None:
    weekly = build_automation(
        _form(
            schedule={"kind": "weekly", "time": "18:00", "weekdays": ["sun", "mon", "nope"]},
            target="both",
            notify="notify.mobile_app_phone",
            agent="a1",
            allow_changes=True,
        )
    )
    assert weekly["triggers"] == [{"trigger": "time", "at": "18:00:00", "weekday": ["mon", "sun"]}]
    data = weekly["actions"][0]["data"]
    assert data["notify"] == "notify.mobile_app_phone" and data["chat"] == "task" and data["agent"] == "a1"
    assert data["allow_changes"] is True
    hourly = build_automation(_form(schedule={"kind": "interval", "every": 3, "unit": "hours"}, target="push", notify="notify.x"))
    assert hourly["triggers"] == [{"trigger": "time_pattern", "hours": "/3", "minutes": 0}]
    assert hourly["actions"][0]["data"]["chat"] == "none"
    minutes = build_automation(_form(schedule={"kind": "interval", "every": 15, "unit": "minutes"}))
    assert minutes["triggers"] == [{"trigger": "time_pattern", "minutes": "/15"}]


@pytest.mark.parametrize(
    "form",
    [
        _form(name=""),
        _form(prompt=" "),
        _form(target="push"),
        _form(schedule={"kind": "daily", "time": "25:00"}),
        _form(schedule={"kind": "weekly", "time": "07:00", "weekdays": []}),
        _form(schedule={"kind": "interval", "every": 0}),
        _form(schedule={"kind": "lunar"}),
    ],
)
def test_build_refuses(form) -> None:
    with pytest.raises(ValueError):
        build_automation(form)


@pytest.mark.parametrize(
    "schedule",
    [
        {"kind": "daily", "time": "07:05"},
        {"kind": "weekly", "time": "18:00", "weekdays": ["mon", "fri"]},
        {"kind": "interval", "every": 3, "unit": "hours"},
        {"kind": "interval", "every": 20, "unit": "minutes"},
    ],
)
def test_parse_round_trip(schedule) -> None:
    form = _form(schedule=schedule, target="both", notify="notify.phone", allow_changes=True, agent="a2")
    parsed = parse_automation(build_automation(form))
    assert parsed["schedule"] == schedule
    assert parsed["editable"] and parsed["has_task"]
    assert parsed["task_name"] == "Morning briefing"
    assert parsed["prompt"] == form["prompt"]
    assert (parsed["target"], parsed["notify"], parsed["allow_changes"], parsed["agent"]) == (
        "both",
        "notify.phone",
        True,
        "a2",
    )


def test_editor_changes_stay_valid() -> None:
    """A condition, an extra step and a second trigger added in the automation editor survive a save on the page."""
    edited = build_automation(_form())
    edited["triggers"].append({"trigger": "state", "entity_id": "person.me", "to": "home"})
    edited["conditions"] = [{"condition": "state", "entity_id": "input_boolean.away", "state": "off"}]
    edited["actions"].append({"action": "light.turn_on", "target": {"entity_id": "light.hall"}})
    edited["id"] = "ai_workspace_task_x"
    parsed = parse_automation(edited)
    assert parsed["schedule"] == {"kind": "custom"}
    assert parsed["editable"]

    saved = build_automation(_form(prompt="New prompt", schedule={"kind": "custom"}), edited)
    assert "id" not in saved
    assert saved["triggers"] == edited["triggers"]
    assert saved["conditions"] == edited["conditions"]
    assert saved["actions"][0]["data"]["prompt"] == "New prompt"
    assert saved["actions"][1] == {"action": "light.turn_on", "target": {"entity_id": "light.hall"}}


def test_parse_other_automations() -> None:
    plain = parse_automation({"alias": "Lights", "triggers": [{"trigger": "sun", "event": "sunset"}], "actions": []})
    assert plain == {"name": "Lights", "schedule": {"kind": "custom"}, "editable": False, "has_task": False}
    legacy = parse_automation(
        {
            "alias": "Old",
            "trigger": {"platform": "time", "at": "06:30:00"},
            "action": [{"service": "ai_workspace.run_task", "data": {"prompt": "Hi", "task_name": "Old"}}],
        }
    )
    assert legacy["schedule"] == {"kind": "daily", "time": "06:30"} and legacy["editable"]
    twice = parse_automation({"actions": [{"action": "ai_workspace.run_task", "data": {"prompt": "a"}}] * 2})
    assert twice["has_task"] and not twice["editable"]


def test_parse_schedule_all_weekdays_is_daily() -> None:
    assert parse_schedule([{"trigger": "time", "at": "08:00:00", "weekday": list(tasks.WEEKDAYS)}]) == {
        "kind": "daily",
        "time": "08:00",
    }
    assert parse_schedule([{"trigger": "time_pattern", "hours": "/2", "minutes": 30}]) == {"kind": "custom"}


def test_task_key() -> None:
    assert task_key("Morning Briefing!") == "morning_briefing"
    assert task_key("Öffnungs-Check") == task_key("öffnungs check")
    assert task_key("") == "task"


# --- Label filtering ----------------------------------------------------------------------------


def test_only_labelled_automations_are_listed(monkeypatch) -> None:
    from custom_components.ai_workspace import tasks_http

    rows = [
        SimpleNamespace(domain="automation", entity_id="automation.briefing", unique_id="a1", labels={"ai_workspace"}),
        SimpleNamespace(domain="script", entity_id="script.x", unique_id="s1", labels={"ai_workspace"}),
    ]
    asked = []

    def by_label(registry, label_id):
        asked.append(label_id)
        return [row for row in rows if label_id in row.labels]

    monkeypatch.setattr(tasks_http.er, "async_get", lambda hass: object())
    monkeypatch.setattr(tasks_http.er, "async_entries_for_label", by_label)
    found = tasks_http.labelled_automations(SimpleNamespace(), "ai_workspace")
    assert [row.entity_id for row in found] == ["automation.briefing"]
    assert tasks_http.labelled_automations(SimpleNamespace(), "") == []
    assert asked == ["ai_workspace"]


def test_task_rows(monkeypatch) -> None:
    from custom_components.ai_workspace import tasks_http

    config = {"id": "a1", **build_automation(_form())}
    entry = SimpleNamespace(domain="automation", entity_id="automation.morning_briefing", unique_id="a1")
    state = _State()
    state.tasks[task_key("Morning briefing")] = {"last_status": "ok", "last_run": 1.0, "chat_id": "c1"}
    monkeypatch.setattr(tasks_http, "task_state", lambda hass: state)
    monkeypatch.setattr(tasks_http, "task_label_id", lambda hass, create=False: "ai_workspace")
    monkeypatch.setattr(tasks_http, "labelled_automations", lambda hass, label: [entry])
    monkeypatch.setattr(tasks_http, "_raw_config", lambda hass, entity_id: config)
    live = SimpleNamespace(state="off", name="Morning briefing", attributes={"last_triggered": "2026-11-20T07:05:00"})
    hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: live))
    (row,) = tasks_http.task_rows(hass)
    assert row["id"] == "a1" and row["enabled"] is False and row["available"] is True
    assert row["last_status"] == "ok" and row["chat_id"] == "c1"
    assert row["schedule"] == {"kind": "daily", "time": "07:05"} and row["editable"]
    state.running.add(task_key("Morning briefing"))
    assert tasks_http.task_rows(hass)[0]["last_status"] == "running"


# --- Page ---------------------------------------------------------------------------------------


def test_page_strings_complete() -> None:
    text = (BASE / "www" / "tasks_i18n.js").read_text(encoding="utf-8")
    keys = re.findall(r'"([a-z_]+)"', text[text.index("const KEYS") : text.index("];")])
    body = text[text.index("const VALUES") : text.index("export const TASK_I18N")]
    blocks = re.findall(r'^  "?([A-Za-z-]+)"?: \[(.*?)^  \],', body, re.S | re.M)
    langs = {path.stem for path in (BASE / "translations").glob("*.json")}
    assert {lang for lang, _ in blocks} == langs
    for lang, block in blocks:
        values = re.findall(r'"((?:[^"\\]|\\.)*)"', block)
        assert len(values) == len(keys), lang
        assert all(values), lang


def test_panel_routes_tasks_page() -> None:
    chat = (BASE / "www" / "chat.js").read_text(encoding="utf-8")
    assert '"/ai-workspace/tasks"' in chat
    assert "tasks_page.js" in chat
    assert "user?.is_admin" in chat[chat.index("const tasksAllowed") : chat.index("const tasksAllowed") + 120]
    page = (BASE / "www" / "tasks_page.js").read_text(encoding="utf-8")
    assert "config/automation/config/" in page
    assert "/label" in page


# --- Fallback chain (agent fallback feature) ----------------------------------------------------


def test_agent_chain_follows_fallback_list(monkeypatch) -> None:
    from custom_components.ai_workspace.fallback import KIND_LIMIT, Failure
    from custom_components.ai_workspace.fallback_ha import book_of

    one, two, three = _provider("a1", "OpenAI"), _provider("a2", "Claude"), _provider("a3", "Cursor")
    settings = SimpleNamespace(fallback_enabled=True, fallback_agents=["a3", "a1", "gone"])
    data = {"providers": {"a1": one, "a2": two, "a3": three}, "settings": settings}
    hass = SimpleNamespace()
    assert tasks.task_agent_chain(hass, data, "") == [three, one]
    book_of(hass, data).mark_failed("a3", Failure(KIND_LIMIT))
    assert tasks.task_agent_chain(hass, data, "") == [one, three]
    # A named agent starts; with Fallback on the list follows (a1 before a3: a3 is waiting).
    assert tasks.task_agent_chain(hass, data, "a2") == [two, one, three]


def test_limit_hands_over_with_journal_and_marks_agent(run_env) -> None:
    from custom_components.ai_workspace.const import DOMAIN
    from custom_components.ai_workspace.fallback import KIND_LIMIT, Failure
    from custom_components.ai_workspace.fallback_ha import book_of

    first, second = _provider("a1", "Claude"), _provider("a2", "OpenAI")
    data = run_env.hass.data[DOMAIN]
    data["providers"] = {"a1": first, "a2": second}
    data["settings"] = SimpleNamespace(fallback_enabled=True, fallback_agents=["a1", "a2"])
    data["fallback_loaded"] = True
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [first, second])
    failed = tasks._Turn(
        error="Claude hit its usage limit",
        failure=Failure(KIND_LIMIT),
        events=[{"type": "tool", "name": "HassTurnOff", "phase": "end", "text": "done"}],
    )
    _turns(run_env, failed, tasks._Turn(answer="Lights are off."))
    params = RUN_TASK_SCHEMA({"prompt": "Turn off the lights", "allow_changes": True})
    result = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert result["status"] == "ok" and result["agent"] == "OpenAI" and result["response"] == "Lights are off."
    handed = run_env.turns[1]["outbound"]
    assert "[Agent handoff]" in handed and "HassTurnOff" in handed and "Turn off the lights" in handed
    book = book_of(run_env.hass, data)
    assert book.blocked("a1") and not book.blocked("a2")


def test_tool_or_refusal_errors_do_not_switch(run_env) -> None:
    first, second = _provider("a1", "Claude"), _provider("a2", "OpenAI")
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [first, second])
    _turns(run_env, tasks._Turn(error="The MCP tool failed"), tasks._Turn(answer="never"))
    result = asyncio.run(tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "x"}))).payload()
    assert result["status"] == "error" and result["agent"] == "Claude" and len(run_env.turns) == 1


# --- Result text and push (1.6.1b12) -------------------------------------------------------------


def test_final_answer_drops_status_line_before_tools() -> None:
    report = "**Wetter heute**\n\n- 18 °C, sonnig"
    # Streamed text only (API providers): the line before the tool call is a status line.
    assert tasks.final_answer(["Wetterdaten aus Home Assistant einlesen.", report]) == report
    # Engine result repeats the whole reply (Cursor) or only the last part (Claude, Codex).
    joined = f"Wetterdaten aus Home Assistant einlesen.\n\n{report}"
    assert tasks.final_answer(["Wetterdaten aus Home Assistant einlesen.", report], joined) == report
    assert tasks.final_answer(["Wetterdaten aus Home Assistant einlesen.", report], report) == report
    # Whitespace differs between the stream and the result.
    squashed = f"Wetterdaten aus Home Assistant einlesen.{report}"
    assert tasks.final_answer(["Wetterdaten aus Home Assistant einlesen.\n", report], squashed) == report
    # No tools: the whole text is the answer; answer written before a last tool call stays.
    assert tasks.final_answer(["Alles zu."], "Alles zu.") == "Alles zu."
    assert tasks.final_answer(["Prüfe.", "Alles zu.", ""]) == "Alles zu."
    assert tasks.final_answer([""], "Nur Ergebnis.") == "Nur Ergebnis."
    assert tasks.final_answer([""]) == ""


def test_one_turn_keeps_only_text_after_last_tool(monkeypatch) -> None:
    from custom_components.ai_workspace import conversation, http

    events = [
        {"type": "status", "text": "Thinking..."},
        {"type": "text", "delta": "Wetterdaten aus Home Assistant einlesen."},
        {"type": "tool", "name": "GetLiveContext", "phase": "start", "text": "Calling..."},
        {"type": "tool", "name": "GetLiveContext", "phase": "end", "text": "ok"},
        {"type": "text", "delta": "Heute **sonnig**, "},
        {"type": "text", "delta": "18 °C."},
        {"type": "result", "text": "Wetterdaten aus Home Assistant einlesen.\n\nHeute **sonnig**, 18 °C."},
    ]

    async def agent_events(*args, **kwargs):
        for event in events:
            yield event

    async def token(hass, user_id):
        return "t"

    monkeypatch.setattr(http, "async_agent_events", agent_events)
    monkeypatch.setattr(conversation, "_login_token", token)
    hass = _hass(_Store())
    data = hass.data["ai_workspace"]
    session = SimpleNamespace(id="s1")
    turn = asyncio.run(tasks._one_turn(hass, data, _provider("a1", "Cursor"), session, "u", "x", "x", "", {}, {}))
    assert turn.answer == "Heute **sonnig**, 18 °C."
    assert len(turn.tools) == 2


def test_task_prompt_forbids_status_lines() -> None:
    note = tasks.task_preamble("Wetter", False, False)
    assert "no status or progress sentences" in note and "output only the result" in note


def test_markdown_to_plain_for_push() -> None:
    md = (
        "## Wetterbericht\n\n\n\n"
        "**Heute:** sonnig, _18 °C_ und `kein` Regen.\n"
        "- Wind: [DWD](https://dwd.de/x_(y)) meldet __schwach__\n"
        "* Morgen: ~~Regen~~ bewölkt\n"
        "  - Abends klar\n"
        "1. erst\n"
        "> Hinweis\n"
        "---\n"
        "| Tag | Temp |\n|---|---|\n| Mo | 18 |\n"
        "```\ncode\n```\n"
        "snake_case_name bleibt, 2*3*4 bleibt"
    )
    plain = tasks.markdown_to_plain(md)
    for marker in ("**", "__", "`", "##", "](", "~~"):
        assert marker not in plain
    lines = plain.split("\n")
    assert lines[0] == "Wetterbericht" and lines[1] == ""
    assert "Heute: sonnig, 18 °C und kein Regen." in lines
    assert "• Wind: DWD meldet schwach" in lines
    assert "• Morgen: Regen bewölkt" in lines
    assert "  • Abends klar" in lines
    assert "1. erst" in lines and "Hinweis" in lines
    assert "Tag · Temp" in lines and "Mo · 18" in lines and "code" in lines
    assert "snake_case_name bleibt, 2*3*4 bleibt" in lines
    assert "\n\n\n" not in plain


def test_push_text_cuts_at_line_or_word() -> None:
    text = "\n".join(f"- Zeile {i} mit etwas **Text**" for i in range(100))
    push = tasks.push_text(text, 200)
    assert len(push) <= 200 and push.endswith("…") and "**" not in push
    assert push[:-1].split("\n")[-1].startswith("• Zeile")  # whole lines only
    assert tasks.push_text("wort " * 100, 50).endswith("wort…")
    assert tasks.push_text("**kurz**") == "kurz"


def test_push_is_plain_but_response_keeps_markdown(run_env) -> None:
    sent: list = []

    async def notify(hass, target, title, message):
        sent.append((target, title, message))

    run_env.monkeypatch.setattr(tasks, "async_notify", notify)
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [_provider("a1", "OpenAI")])
    _turns(run_env, tasks._Turn(answer="**Sonnig**, 18 °C"))
    params = RUN_TASK_SCHEMA(
        {"prompt": "Wetter?", "task_name": "Wetterbericht 19 Uhr", "notify": "notify.mobile_app_x"}
    )
    result = asyncio.run(tasks.async_run_task(run_env.hass, params)).payload()
    assert result["response"] == "**Sonnig**, 18 °C"
    assert sent == [("notify.mobile_app_x", "Wetterbericht 19 Uhr", "Sonnig, 18 °C")]
    assert run_env.store.messages[-1][2] == "**Sonnig**, 18 °C"


def test_fallback_switch_and_finish_are_logged(run_env, caplog) -> None:
    import logging

    first, second = _provider("a1", "OpenAI"), _provider("a2", "Claude")
    run_env.monkeypatch.setattr(tasks, "task_agent_chain", lambda hass, data, wanted: [first, second])
    _turns(run_env, tasks._Turn(error="down", connection=True), tasks._Turn(answer="Sonnig."))
    with caplog.at_level(logging.WARNING, logger=tasks._LOGGER.name):
        asyncio.run(tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "x", "task_name": "W"})))
    text = caplog.text
    assert "fallback switched from OpenAI" in text and "to Claude" in text
    assert "finished with fallback agent Claude" in text


# --- Agent choice without Fallback (1.6.1b13) ----------------------------------------------------


def test_fallback_off_failure_ends_the_task_without_switching(run_env, caplog) -> None:
    import logging

    from custom_components.ai_workspace.const import DOMAIN
    from custom_components.ai_workspace.fallback import KIND_AUTH, Failure

    providers = _subentries()
    data = run_env.hass.data[DOMAIN]
    data["providers"] = providers
    data["settings"] = SimpleNamespace(default_agent="")
    data["runtime_version"] = tasks.TASK_RUNTIME_MIN
    _turns(run_env, tasks._Turn(error="Claude sign-in expired", failure=Failure(KIND_AUTH)), tasks._Turn(answer="never"))
    with caplog.at_level(logging.INFO, logger=tasks._LOGGER.name):
        result = asyncio.run(tasks.async_run_task(run_env.hass, RUN_TASK_SCHEMA({"prompt": "x", "task_name": "Morning"}))).payload()
    assert result["status"] == "error" and result["agent"] == "Claude" and "sign-in" in result["response"]
    assert [turn["provider"] for turn in run_env.turns] == [providers["cl"]]
    assert "task Morning: agent Claude (fallback off)" in caplog.text
    assert "fallback switched" not in caplog.text
