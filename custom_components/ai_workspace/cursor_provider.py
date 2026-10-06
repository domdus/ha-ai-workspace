from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from .const import with_ui_context
from .events import map_sdk_message
from .images import cursor_payload
from .models import ProviderInfo, Settings
from .redact import redact
from .store import Session
from .unavailable import UnavailableProvider

logger = logging.getLogger(__name__)

_MISSING_KEY = (
    "Cursor API key is not set. Create a user API key at "
    "https://cursor.com/dashboard/integrations and add it in the AI Workspace integration."
)


class CursorRuntime:
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
        kwargs = {
            "model": self.settings.model,
            "api_key": self.settings.cursor_api_key,
            "name": f"ha-{session.id[:8]}",
            "local": LocalAgentOptions(cwd=str(self.settings.workspace_dir)),
            "mcp_servers": mcp_servers,
            "tools": ["mcp"],
        }
        try:
            options = AgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("tools", None)
            options = AgentOptions(**kwargs)
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
        access_token: str | None = None,
        frontend_origin: str | None = None,
        images: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        del access_token
        outbound = with_ui_context(message, frontend_origin or "")
        if not self.settings.cursor_api_key:
            yield {"type": "error", "message": _MISSING_KEY}
            return
        mcp_servers = self.settings.mcp_servers
        if not mcp_servers:
            logger.warning("no MCP servers configured")
        else:
            logger.info("mcp servers: %s", ", ".join(sorted(mcp_servers)))
        try:
            agent = await self.runtime.open_agent(session, mcp_servers)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key, self.settings.mcp_token)}
            return
        agent_id = getattr(agent, "agent_id", None)
        if agent_id:
            on_agent_id(str(agent_id))
        try:
            run = await agent.send(cursor_payload(outbound, images))
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key, self.settings.mcp_token)}
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
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key, self.settings.mcp_token)}
            return
        status = getattr(result, "status", "")
        final = getattr(result, "result", None) or ""
        if status == "error":
            yield {
                "type": "error",
                "message": _public_error(Exception(final or f"Run failed ({run_id})"), self.settings.cursor_api_key, self.settings.mcp_token),
            }
            return
        if final:
            yield {"type": "result", "text": str(final), "run_id": str(run_id), "status": str(status)}


def _public_error(exc: Exception, api_key: str, mcp_token: str = "") -> str:
    retryable = getattr(exc, "is_retryable", None)
    text = redact(str(exc), [api_key, mcp_token])
    if retryable:
        return f"{text} (retryable)"
    return text


def build_providers(settings: Settings, runtime: CursorRuntime) -> dict:
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
