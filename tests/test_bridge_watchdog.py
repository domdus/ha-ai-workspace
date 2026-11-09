"""A new agent that never reaches its MCP servers gets a fresh bridge and one more try."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.providers import cursor as cursor_mod
from app.providers.cursor import CursorProvider, CursorRuntime
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


class _Run:
    def __init__(self, runtime, session_id, connects):
        self.id = f"run-{id(self)}"
        self.runtime = runtime
        self.session_id = session_id
        self.connects = connects
        self.cancelled = asyncio.Event()

    async def cancel(self):
        self.cancelled.set()

    async def wait(self):
        return SimpleNamespace(status="finished", result="Done", duration_ms=1, model=None)


def _setup(tmp_path, monkeypatch, plan):
    """plan: one bool per run, True when the run's agent reaches the proxy."""
    monkeypatch.setattr(cursor_mod, "_MCP_CONNECT_GRACE", 0.05)
    runtime = CursorRuntime(_settings(tmp_path))
    provider = CursorProvider(_settings(tmp_path), runtime)
    opened = []
    runs = []

    async def fake_open(session, servers, **kwargs):
        opened.append(kwargs.get("fresh"))

        class Agent:
            agent_id = f"agent-{len(opened)}"

            async def send(self, payload, options=None):
                run = _Run(runtime, session.id, plan[len(runs)])
                runs.append(run)
                return run

        return Agent(), True

    async def fake_iter(run):
        if run.connects:
            run.runtime.proxy.note_hit(run.session_id)
            yield {"type": "text", "text": "Answer"}
            return
        yield {"type": "text", "text": "Checking..."}
        try:
            await asyncio.wait_for(run.cancelled.wait(), 2)
        except asyncio.TimeoutError:
            pass
        yield {"type": "text", "text": "late"}

    async def no_usage(*args, **kwargs):
        return None

    monkeypatch.setattr(runtime, "open_agent", fake_open)
    monkeypatch.setattr(runtime, "wrap_mcp", lambda servers, actor="": servers)
    monkeypatch.setattr(cursor_mod, "_iter_messages", fake_iter)
    monkeypatch.setattr(cursor_mod, "_cursor_usage", no_usage)
    session = Session("s1", "u1", "cursor", "Chat", None, "t", "t")
    mcp = {"servers": {"ha": {"type": "http", "url": "http://ha:8123/api/mcp"}}}

    async def go():
        return [
            event
            async for event in provider.send(
                session, "Ist die Bewässerung gelaufen?", lambda _id: None, mcp=mcp, question="Ist das Licht an?"
            )
        ]

    return runtime, opened, runs, go


def test_stuck_bridge_is_restarted_and_the_turn_is_sent_again(tmp_path, monkeypatch) -> None:
    runtime, opened, runs, go = _setup(tmp_path, monkeypatch, [False, True])
    events = asyncio.run(go())
    texts = [e.get("text") for e in events]
    assert "Reconnecting tools..." in texts
    assert texts[-1] == "Done"
    assert "late" not in texts
    assert opened == [False, True]
    assert runs[0].cancelled.is_set()
    assert runtime._restart_pending


def test_healthy_run_leaves_the_bridge_alone(tmp_path, monkeypatch) -> None:
    runtime, opened, runs, go = _setup(tmp_path, monkeypatch, [True])
    events = asyncio.run(go())
    assert [e.get("text") for e in events][-1] == "Done"
    assert opened == [False]
    assert not runtime._restart_pending


def test_second_stall_gives_up_with_a_clear_message(tmp_path, monkeypatch) -> None:
    runtime, opened, runs, go = _setup(tmp_path, monkeypatch, [False, False])
    events = asyncio.run(go())
    assert opened == [False, True]
    assert events[-1]["type"] == "error"
    assert "could not connect" in events[-1]["message"]


def test_restart_cooldown(tmp_path) -> None:
    runtime = CursorRuntime(_settings(tmp_path))
    assert runtime.request_bridge_restart("first")
    assert not runtime.request_bridge_restart("again")


def test_pending_restart_waits_for_other_runs(tmp_path) -> None:
    runtime = CursorRuntime(_settings(tmp_path))
    closed = []

    class Client:
        async def aclose(self):
            closed.append(True)

    runtime._client = Client()
    runtime._restart_pending = True
    runtime.run_started()

    async def get():
        return await runtime.client()

    assert isinstance(asyncio.run(get()), Client) and closed == []
    runtime.run_ended()

    class Launched:
        pass

    async def launch(**kwargs):
        return Launched()

    import sys
    from types import ModuleType

    fake = ModuleType("cursor_sdk")
    fake.AsyncClient = SimpleNamespace(launch_bridge=launch)
    sys.modules["cursor_sdk"] = fake
    try:
        assert isinstance(asyncio.run(get()), Launched)
    finally:
        sys.modules.pop("cursor_sdk", None)
    assert closed == [True] and not runtime._restart_pending
