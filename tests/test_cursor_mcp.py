import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from app.providers.cursor import CursorRuntime
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


def test_replaces_cached_agent_when_mcp_changes(tmp_path: Path, monkeypatch) -> None:
    fake_sdk = ModuleType("cursor_sdk")

    class AgentNotFoundError(Exception):
        pass

    class AgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_sdk.AgentNotFoundError = AgentNotFoundError
    fake_sdk.AgentOptions = AgentOptions
    fake_sdk.LocalAgentOptions = LocalAgentOptions
    monkeypatch.setitem(sys.modules, "cursor_sdk", fake_sdk)

    created: list[dict] = []

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

    first = asyncio.run(runtime.open_agent(session, {}))
    second = asyncio.run(
        runtime.open_agent(
            session,
            {"home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}},
        )
    )
    assert first.agent_id == "old-agent"
    assert second.agent_id == "agent-1"
    assert created[0].mcp_servers == {
        "home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}
    }
    assert not hasattr(created[0], "tools") or created[0].tools is None
    assert created[0].model == "composer-2.5"

    third = asyncio.run(
        runtime.open_agent(
            session,
            {"home-assistant": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/x"}},
            model="composer-2.6",
        )
    )
    assert third.agent_id == "agent-2"
    assert created[1].model == "composer-2.6"
