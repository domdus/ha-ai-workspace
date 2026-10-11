import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from app.providers.cursor import (
    CursorRuntime,
    apply_handoff,
    _empty_failed_run,
    _mcp_identity,
    _run_error_text,
    _sdk_model,
)
from app.settings import Settings
from app.store import Session


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="crsr_test",
        model="composer-2.5",
        auth_mode="dev",
        host="127.0.0.1",
        port=8090,
    )


def _install_fake_sdk(monkeypatch) -> None:
    fake_sdk = ModuleType("cursor_sdk")

    class AgentNotFoundError(Exception):
        pass

    class AgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ModelParameterValue:
        def __init__(self, id, value):
            self.id = id
            self.value = value

    class ModelSelection:
        def __init__(self, id, params=()):
            self.id = id
            self.params = params

    fake_sdk.AgentNotFoundError = AgentNotFoundError
    fake_sdk.AgentOptions = AgentOptions
    fake_sdk.LocalAgentOptions = LocalAgentOptions
    fake_sdk.ModelParameterValue = ModelParameterValue
    fake_sdk.ModelSelection = ModelSelection
    monkeypatch.setitem(sys.modules, "cursor_sdk", fake_sdk)


def test_replaces_cached_agent_when_mcp_changes(tmp_path: Path, monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)

    created: list = []

    class FakeClient:
        async def create_agent(self, options):
            created.append(options)
            return SimpleNamespace(agent_id=f"agent-{len(created)}")

        async def resume_agent(self, agent_id, options):
            del options
            return SimpleNamespace(agent_id=agent_id)

    runtime = CursorRuntime(_settings(tmp_path))
    runtime._client = FakeClient()
    session = Session("s1", "u1", "cursor", "Chat", "old-agent", "t", "t")

    first, first_new = asyncio.run(runtime.open_agent(session, {}))
    second, second_new = asyncio.run(
        runtime.open_agent(
            session,
            {"home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}},
        )
    )
    assert first.agent_id == "old-agent"
    assert first_new
    assert second.agent_id == "agent-1"
    assert second_new
    assert created[0].mcp_servers == {
        "home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}
    }
    assert not hasattr(created[0], "tools") or created[0].tools is None
    assert created[0].model.id == "composer-2.5"
    assert created[0].model.params[0].id == "fast"
    assert created[0].model.params[0].value == "true"

    third, third_new = asyncio.run(
        runtime.open_agent(
            session,
            {"home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}},
            model="composer-2.6",
        )
    )
    assert third.agent_id == "agent-2"
    assert third_new
    assert created[1].model == "composer-2.6"


def test_sdk_model_pins_composer_25_standard(monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)
    model = _sdk_model("composer-2.5")
    assert model.id == "composer-2.5"
    assert model.params[0].id == "fast"
    assert model.params[0].value == "true"
    assert _sdk_model("composer-2.6") == "composer-2.6"


def test_empty_failed_run_matches_composer_fast_error() -> None:
    result = SimpleNamespace(status="error", result="", usage=None, error=None)
    assert _empty_failed_run(result)
    assert not _empty_failed_run(SimpleNamespace(status="finished", result="Hi", usage=None))


def test_run_error_text_unpacks_nested_error() -> None:
    result = SimpleNamespace(
        status="error",
        result="",
        error=SimpleNamespace(message="model produced empty output"),
        model=SimpleNamespace(id="composer-2.5", params=()),
        request_id="req-1",
    )
    assert _run_error_text(result, "run-1", "composer-2.5") == "model produced empty output"


def test_run_error_text_mentions_empty_output_when_cursor_is_silent() -> None:
    result = SimpleNamespace(status="error", result="", error=None, model=None, request_id="")
    text = _run_error_text(result, "run-040cda8d", "composer-2.5")
    assert "composer-2.5" in text
    assert "run-040cda8d" in text
    assert "no assistant text" in text
    assert "budget limit" in text
    assert "composer-2.6" not in text


def test_keeps_agent_when_only_mcp_token_changes(tmp_path: Path, monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)

    class FakeClient:
        async def create_agent(self, options):
            del options
            raise AssertionError("token rotation must not create a new agent")

        async def resume_agent(self, agent_id, options):
            del options
            return SimpleNamespace(agent_id=agent_id)

    runtime = CursorRuntime(_settings(tmp_path))
    runtime._client = FakeClient()
    session = Session("s1", "u1", "cursor", "Chat", "keep-me", "t", "t")
    url = "http://127.0.0.1:8123/api/mcp"
    first, _ = asyncio.run(
        runtime.open_agent(session, {"mcp": {"url": url, "headers": {"Authorization": "Bearer one"}}})
    )
    second, created = asyncio.run(
        runtime.open_agent(session, {"mcp": {"url": url, "headers": {"Authorization": "Bearer two"}}})
    )
    assert first.agent_id == "keep-me"
    assert second.agent_id == "keep-me"
    assert not created
    assert _mcp_identity({"mcp": {"url": url, "headers": {"Authorization": "Bearer one"}}}) == _mcp_identity(
        {"mcp": {"url": url, "headers": {"Authorization": "Bearer two"}}}
    )


def test_live_follow_up_reuses_agent_until_idle(tmp_path: Path, monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)

    created: list[str] = []

    class FakeClient:
        async def create_agent(self, options):
            del options
            created.append("new")
            return SimpleNamespace(agent_id="fresh")

        async def resume_agent(self, agent_id, options):
            del options
            return SimpleNamespace(agent_id=agent_id)

    runtime = CursorRuntime(_settings(tmp_path))
    runtime._client = FakeClient()
    session = Session("s1", "u1", "cursor", "Chat", "keep-me", "t", "t")
    first, restore = asyncio.run(runtime.open_agent(session, {}))
    second, follow = asyncio.run(runtime.open_agent(session, {}))
    assert first.agent_id == "keep-me"
    assert restore
    assert not follow
    assert created == []
    runtime._used_at[session.id] -= 200
    third, after_pause = asyncio.run(runtime.open_agent(session, {}))
    assert third.agent_id == "fresh"
    assert after_pause
    assert created == ["new"]


def test_old_chat_does_not_resume_empty_thread(tmp_path: Path, monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)
    resumed: list[str] = []

    class FakeClient:
        async def create_agent(self, options):
            del options
            return SimpleNamespace(agent_id="fresh")

        async def resume_agent(self, agent_id, options):
            del options
            resumed.append(agent_id)
            return SimpleNamespace(agent_id=agent_id)

    runtime = CursorRuntime(_settings(tmp_path))
    runtime._client = FakeClient()
    session = Session("s1", "u1", "cursor", "Chat", "old-cloud", "t", "2020-01-01T00:00:00+00:00")
    agent, fresh = asyncio.run(runtime.open_agent(session, {}))
    assert agent.agent_id == "fresh"
    assert fresh
    assert resumed == []


def test_apply_handoff_goes_with_every_follow_up() -> None:
    note = "This is the same chat.\n\nUser: Status?"
    assert apply_handoff("And now?", note, True).startswith("This is the same chat.")
    again = apply_handoff("And now?", note, False)
    assert "User: Status?" in again
    assert again.endswith("And now?")
    already = f"{note}\n\nAnd now?"
    assert apply_handoff(already, note, True) == already
    message = "System prompt about the house.\n\nWhat did we talk about?"
    placed = apply_handoff(message, note, True, question="What did we talk about?")
    assert placed.index("System prompt") < placed.index("User: Status?") < placed.index("What did we talk about?")
