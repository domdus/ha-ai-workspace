from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable

from app.events import map_sdk_message
from app.images import cursor_payload
from app.mcp_config import McpConfigError, load_mcp_servers, merge_mcp_servers, servers_from_chat_mcp
from app.providers.base import ProviderInfo
from app.redact import redact
from app.settings import Settings
from app.store import Session
from app.titles import clean_title, title_prompt

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
        self._mcp_by_session: dict[str, str] = {}
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

    def _agent_options(
        self,
        name: str,
        mcp_servers: dict,
        tools: list[str] | None = None,
        model: str | None = None,
    ) -> Any:
        from cursor_sdk import AgentOptions, LocalAgentOptions

        kwargs: dict[str, Any] = {
            "model": (model or "").strip() or self.settings.model,
            "api_key": self.settings.cursor_api_key,
            "name": name,
            "local": LocalAgentOptions(cwd=str(self.settings.workspace_dir)),
        }
        if mcp_servers:
            kwargs["mcp_servers"] = mcp_servers
        if tools is not None:
            kwargs["tools"] = tools
        try:
            return AgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("tools", None)
            return AgentOptions(**kwargs)

    async def open_agent(self, session: Session, mcp_servers: dict, model: str | None = None) -> Any:
        from cursor_sdk import AgentNotFoundError

        resolved_model = (model or "").strip() or self.settings.model
        fingerprint = json.dumps(
            {"mcp": mcp_servers, "model": resolved_model},
            sort_keys=True,
            default=str,
        )
        cached = self._agents.get(session.id)
        previous = self._mcp_by_session.get(session.id)
        if cached is not None and previous == fingerprint:
            logger.info("reuse agent session=%s", session.id)
            return cached
        if cached is not None:
            logger.info("mcp servers or model changed, replacing agent session=%s", session.id)
            self._agents.pop(session.id, None)
        client = await self.client()
        options = self._agent_options(f"ha-{session.id[:8]}", mcp_servers, model=resolved_model)
        agent = None
        resume_id = session.agent_id if previous in (None, fingerprint) else None
        if resume_id:
            try:
                logger.info("resume agent session=%s agent=%s", session.id, resume_id)
                agent = await client.resume_agent(resume_id, options)
            except AgentNotFoundError:
                logger.info("agent %s missing, creating a new one", resume_id)
                agent = None
        if agent is None:
            logger.info("create agent session=%s model=%s", session.id, resolved_model)
            agent = await client.create_agent(options)
        self._agents[session.id] = agent
        self._mcp_by_session[session.id] = fingerprint
        return agent

    async def warm(self) -> None:
        try:
            await self.client()
            logger.info("cursor bridge ready")
        except Exception:
            logger.warning("cursor bridge warmup failed", exc_info=True)

    def drop(self, session_id: str) -> None:
        self._agents.pop(session_id, None)
        self._mcp_by_session.pop(session_id, None)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._agents.clear()
        self._mcp_by_session.clear()
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
        images: list[dict] | None = None,
        mcp: dict | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        if not self.settings.cursor_api_key:
            yield {"type": "error", "message": _MISSING_KEY}
            return
        try:
            file_servers = load_mcp_servers(self.settings.mcp_config_path)
            mcp_servers = merge_mcp_servers(file_servers, servers_from_chat_mcp(mcp))
        except McpConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        if not mcp_servers:
            logger.warning("no MCP servers in %s or chat request", self.settings.mcp_config_path)
        else:
            logger.info(
                "mcp servers: %s",
                ", ".join(
                    f"{name}={cfg.get('url') or cfg.get('command')}"
                    for name, cfg in sorted(mcp_servers.items())
                ),
            )
        used_model = (model or "").strip() or self.settings.model
        logger.info("cursor model=%s", used_model)
        yield {"type": "status", "text": "Thinking..."}
        try:
            agent = await self.runtime.open_agent(session, mcp_servers, model=model)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        agent_id = getattr(agent, "agent_id", None)
        if agent_id:
            on_agent_id(str(agent_id))
        try:
            run = await _start_run(agent, message, images, mcp_servers, model)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        run_id = getattr(run, "id", "")
        logger.info("run started session=%s agent=%s run=%s model=%s", session.id, agent_id, run_id, used_model)
        stream_error: str | None = None
        try:
            async for sdk_message in run.messages():
                for event in map_sdk_message(sdk_message):
                    if event.get("type") == "error" and not stream_error:
                        stream_error = str(event.get("message") or "")
                    yield event
            result = await run.wait()
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        status = str(getattr(result, "status", "") or "")
        final = getattr(result, "result", None) or ""
        if status == "error":
            logger.warning(
                "cursor run error run=%s model=%s duration=%s result=%r",
                run_id,
                getattr(result, "model", used_model),
                getattr(result, "duration_ms", None),
                result,
            )
            yield {
                "type": "error",
                "message": _run_error_text(result, run_id, used_model, stream_error),
            }
            return
        if final:
            yield {"type": "result", "text": str(final), "run_id": str(run_id), "status": str(status)}

    async def suggest_title(self, user: str, assistant: str = "") -> str | None:
        if not self.settings.cursor_api_key:
            return None
        try:
            client = await self.runtime.client()
            options = self.runtime._agent_options("ha-title", {}, tools=[])
            agent = await client.create_agent(options)
            run = await agent.send(title_prompt(user, assistant))
            result = await run.wait()
            if getattr(result, "status", "") == "error":
                return None
            return clean_title(str(getattr(result, "result", None) or "")) or None
        except Exception:
            logger.debug("cursor title generation failed", exc_info=True)
            return None


def _model_id(value: Any) -> str:
    if value is None:
        return ""
    ident = getattr(value, "id", None)
    if ident:
        return str(ident).strip()
    if isinstance(value, dict):
        return str(value.get("id") or "").strip()
    return str(value).strip()


def _run_error_text(result: Any, run_id: str, model: str, stream_error: str | None = None) -> str:
    for attr in ("result", "error", "message", "error_message", "failure_reason"):
        value = getattr(result, attr, None)
        text = str(value or "").strip()
        if text and text.lower() not in {"error", "none"}:
            return text
    if stream_error:
        return stream_error
    used = _model_id(getattr(result, "model", None)) or model
    suffix = f" ({run_id})" if run_id else ""
    if used and used.lower() not in {"auto", "default", "auto-smart"}:
        return (
            f"Run failed{suffix}. Cursor returned no details. Named model {used} often fails "
            "this way when the account is limited to Auto — set CURSOR_MODEL=auto and recreate the container."
        )
    return f"Run failed{suffix}."


async def _start_run(agent: Any, message: str, images: list[dict] | None, mcp_servers: dict, model: str | None):
    payload = cursor_payload(message, images)
    options: dict[str, Any] = {}
    if mcp_servers:
        options["mcp_servers"] = mcp_servers
    if (model or "").strip():
        options["model"] = model.strip()
    if options:
        try:
            return await agent.send(payload, options)
        except TypeError:
            pass
    return await agent.send(payload)


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
