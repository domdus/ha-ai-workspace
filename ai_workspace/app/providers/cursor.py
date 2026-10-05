from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from app.events import map_sdk_message
from app.mcp_config import McpConfigError, load_mcp_servers
from app.providers.base import ProviderInfo
from app.redact import redact
from app.settings import Settings
from app.store import Session

logger = logging.getLogger(__name__)

_MISSING_KEY = (
    "Cursor API key is not set. Create a user API key at "
    "https://cursor.com/dashboard/integrations and put it in CURSOR_API_KEY "
    "or the addon option cursor_api_key."
)


class CursorRuntime:
    """One local Cursor bridge for the process. Agent handles stay open so follow-ups keep context."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None
        self._agents: dict[str, Any] = {}
        self._start_lock = None

    def _lock(self):
        import asyncio

        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        return self._start_lock

    async def client(self) -> Any:
        async with self._lock():
            if self._client is None:
                from cursor_sdk import AsyncClient

                logger.info("starting cursor bridge workspace=%s", self.settings.workspace_dir)
                self._client = await AsyncClient.launch_bridge(
                    workspace=str(self.settings.workspace_dir),
                    state_root=str(self.settings.state_dir),
                    timeout=180,
                )
            return self._client

    async def open_agent(self, session: Session, mcp_servers: dict) -> Any:
        from cursor_sdk import AgentNotFoundError, AgentOptions, LocalAgentOptions

        cached = self._agents.get(session.id)
        if cached is not None:
            return cached
        client = await self.client()
        options = AgentOptions(
            model=self.settings.model,
            api_key=self.settings.cursor_api_key,
            name=f"ha-{session.id[:8]}",
            local=LocalAgentOptions(cwd=str(self.settings.workspace_dir)),
            mcp_servers=mcp_servers,
        )
        agent = None
        if session.agent_id:
            try:
                agent = await client.resume_agent(session.agent_id, options)
            except AgentNotFoundError:
                logger.info("agent %s missing, creating a new one", session.agent_id)
                agent = None
        if agent is None:
            agent = await client.create_agent(options)
        self._agents[session.id] = agent
        return agent

    def drop(self, session_id: str) -> None:
        self._agents.pop(session_id, None)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._agents.clear()
        if client is not None:
            await client.aclose()


class CursorProvider:
    def __init__(self, settings: Settings, runtime: CursorRuntime) -> None:
        self.settings = settings
        self.runtime = runtime

    @property
    def info(self) -> ProviderInfo:
        if not self.settings.cursor_api_key:
            return ProviderInfo("cursor", "Cursor", False, _MISSING_KEY)
        return ProviderInfo("cursor", "Cursor", True, None)

    async def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
    ) -> AsyncIterator[dict]:
        if not self.settings.cursor_api_key:
            yield {"type": "error", "message": _MISSING_KEY}
            return
        try:
            mcp_servers = load_mcp_servers(self.settings.mcp_config_path)
        except McpConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        if not mcp_servers:
            yield {"type": "status", "text": "No MCP servers configured."}
        else:
            names = ", ".join(sorted(mcp_servers))
            yield {"type": "status", "text": f"MCP: {names}"}
        try:
            agent = await self.runtime.open_agent(session, mcp_servers)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        agent_id = getattr(agent, "agent_id", None)
        if agent_id:
            on_agent_id(str(agent_id))
        try:
            run = await agent.send(message)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        run_id = getattr(run, "id", "")
        logger.info("run started session=%s agent=%s run=%s", session.id, agent_id, run_id)
        yield {"type": "status", "text": "Thinking..."}
        try:
            async for sdk_message in run.messages():
                for event in map_sdk_message(sdk_message):
                    yield event
            result = await run.wait()
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        status = getattr(result, "status", "")
        final = getattr(result, "result", None) or ""
        if status == "error":
            yield {
                "type": "error",
                "message": _public_error(Exception(final or f"Run failed ({run_id})"), self.settings.cursor_api_key),
            }
            return
        if final:
            yield {"type": "result", "text": str(final), "run_id": str(run_id), "status": str(status)}


def _public_error(exc: Exception, api_key: str) -> str:
    retryable = getattr(exc, "is_retryable", None)
    text = redact(str(exc), [api_key])
    if retryable:
        return f"{text} (retryable)"
    return text


def build_providers(settings: Settings, runtime: CursorRuntime) -> dict:
    from app.providers.unavailable import UnavailableProvider

    return {
        "cursor": CursorProvider(settings, runtime),
        "claude": UnavailableProvider(
            ProviderInfo(
                "claude",
                "Claude",
                False,
                "Claude uses the Claude Agent SDK in a later adapter. The chat shell is the same.",
            )
        ),
        "openai": UnavailableProvider(
            ProviderInfo(
                "openai",
                "ChatGPT",
                False,
                "ChatGPT uses the OpenAI Agents SDK in a later adapter. The chat shell is the same.",
            )
        ),
    }
