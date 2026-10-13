from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from app.events import map_sdk_message
from app.images import cursor_payload
from app.mcp_config import McpConfigError, load_mcp_servers, merge_mcp_servers, servers_from_chat_mcp
from app.mcp_fit import FitRegistry
from app.providers.base import ProviderInfo
from app.redact import redact
from app.settings import Settings
from app.small_talk import wants_house_tools
from app.store import Session
from app.titles import clean_title, title_prompt

logger = logging.getLogger(__name__)

_MISSING_KEY = (
    "Cursor API key is not set. Create a user API key at "
    "https://cursor.com/dashboard/integrations and put it in CURSOR_API_KEY "
    "or the addon option cursor_api_key."
)


# After this pause the saved Cursor thread is often empty, so open a new agent.
# The HA transcript is still pasted on every turn, including a quick follow-up.
_IDLE_RESTORE = 120.0


class CursorRuntime:
    """One local Cursor bridge for the process. Agent handles stay open so follow-ups keep context."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None
        self._agents: dict[str, Any] = {}
        self._mcp_by_session: dict[str, str] = {}
        self._used_at: dict[str, float] = {}
        self._with_tools: set[str] = set()
        self._start_lock = None
        self.fit = FitRegistry(settings.data_dir / "mcp-fit-secret")

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
        effort: str = "",
        api_key: str = "",
    ) -> Any:
        from cursor_sdk import AgentOptions, LocalAgentOptions

        resolved = (model or "").strip() or (self.settings.model or "").strip()
        kwargs: dict[str, Any] = {
            "api_key": (api_key or "").strip() or self.settings.cursor_api_key,
            "name": name,
            "local": LocalAgentOptions(cwd=str(self.settings.workspace_dir)),
        }
        if resolved:
            kwargs["model"] = _sdk_model(resolved, effort)
        if mcp_servers:
            kwargs["mcp_servers"] = mcp_servers
        if tools is not None:
            kwargs["tools"] = tools
        try:
            return AgentOptions(**kwargs)
        except TypeError:
            kwargs.pop("tools", None)
            try:
                return AgentOptions(**kwargs)
            except TypeError:
                if resolved:
                    kwargs["model"] = resolved
                return AgentOptions(**kwargs)

    async def open_agent(
        self,
        session: Session,
        mcp_servers: dict,
        model: str | None = None,
        effort: str = "",
        api_key: str = "",
        config_key: str | None = None,
    ) -> tuple[Any, bool]:
        from cursor_sdk import AgentNotFoundError

        resolved_model = (model or "").strip() or self.settings.model
        resolved_key = (api_key or "").strip() or self.settings.cursor_api_key
        key_tag = hashlib.sha256(resolved_key.encode()).hexdigest()[:16] if resolved_key else ""
        fingerprint = config_key or _agent_fingerprint(mcp_servers, resolved_model, effort, key_tag)
        cached = self._agents.get(session.id)
        previous = self._mcp_by_session.get(session.id)
        cold = self._cold(session)
        if cached is not None and previous == fingerprint and not cold:
            self._touch(session.id)
            logger.info("reuse agent session=%s", session.id)
            return cached, False
        if cached is not None:
            if cold:
                logger.info("chat idle, opening a fresh agent session=%s", session.id)
            else:
                logger.info("mcp servers or model changed, replacing agent session=%s", session.id)
            self.drop(session.id)
        client = await self.client()
        options = self._agent_options(
            f"ha-{session.id[:8]}", mcp_servers, model=resolved_model, effort=effort, api_key=resolved_key
        )
        agent = None
        # A cold cloud thread often comes back empty. Start a new agent and let the HA transcript resume the chat.
        resume_id = None if cold else (session.agent_id if previous in (None, fingerprint) else None)
        if resume_id:
            try:
                logger.info("resume agent session=%s agent=%s", session.id, resume_id)
                agent = await client.resume_agent(resume_id, options)
            except AgentNotFoundError:
                logger.info("agent %s missing, creating a new one", resume_id)
                agent = None
        if agent is None:
            logger.info("create agent session=%s model=%s", session.id, _model_fingerprint(resolved_model))
            agent = await client.create_agent(options)
        self._agents[session.id] = agent
        self._mcp_by_session[session.id] = fingerprint
        self._touch(session.id)
        if mcp_servers:
            self._with_tools.add(session.id)
        else:
            self._with_tools.discard(session.id)
        return agent, True

    async def warm(self) -> None:
        try:
            await self.client()
            logger.info("cursor bridge ready")
        except Exception:
            logger.warning("cursor bridge warmup failed", exc_info=True)

    def wrap_mcp(self, servers: dict, actor: str = "") -> dict:
        return self.fit.wrap(servers, f"http://127.0.0.1:{self.settings.port}", actor)

    def _touch(self, session_id: str) -> None:
        self._used_at[session_id] = time.monotonic()

    def _idle(self, session_id: str) -> bool:
        last = self._used_at.get(session_id)
        if last is None:
            return True
        return (time.monotonic() - last) >= _IDLE_RESTORE

    def _cold(self, session: Session) -> bool:
        """True when this chat's Cursor thread should not be trusted."""
        if session.id in self._used_at:
            return self._idle(session.id)
        return _session_idle(getattr(session, "updated_at", ""))

    def drop(self, session_id: str) -> None:
        self._agents.pop(session_id, None)
        self._mcp_by_session.pop(session_id, None)
        self._used_at.pop(session_id, None)
        self._with_tools.discard(session_id)

    def forget(self, session: Session) -> None:
        """Drop a dead Cursor thread so the next turn creates a new agent."""
        self.drop(session.id)
        session.agent_id = None

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._agents.clear()
        self._mcp_by_session.clear()
        self._used_at.clear()
        self._with_tools.clear()
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
        effort: str = "",
        api_key: str = "",
        handoff: str = "",
        question: str = "",
    ) -> AsyncIterator[dict]:
        key = (api_key or "").strip() or self.settings.cursor_api_key
        if not key:
            yield {"type": "error", "message": _MISSING_KEY}
            return
        try:
            exclusive = bool((mcp or {}).get("exclusive"))
            file_servers = {} if exclusive else load_mcp_servers(self.settings.mcp_config_path)
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
        key_tag = hashlib.sha256(key.encode()).hexdigest()[:16] if key else ""
        config_key = _agent_fingerprint(mcp_servers, used_model, effort, key_tag)
        wrapped = self.runtime.wrap_mcp(mcp_servers, session.id)
        asked = (question or "").strip()
        attach_tools = bool(images) or wants_house_tools(asked or message)
        if attach_tools and session.id not in self.runtime._with_tools:
            self.runtime.drop(session.id)
        run_servers = wrapped if attach_tools else {}
        logger.info("cursor model=%s tools=%s", used_model, "on" if attach_tools else "off")
        yield {"type": "status", "text": "Thinking..."}
        try:
            agent, created = await self.runtime.open_agent(
                session,
                run_servers,
                model=used_model,
                effort=effort,
                api_key=key,
                config_key=config_key,
            )
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        agent_id = getattr(agent, "agent_id", None)
        if agent_id:
            on_agent_id(str(agent_id))
        outbound = apply_handoff(message, handoff, created, question=asked or question)
        logger.info(
            "cursor outbound session=%s chars=%s handoff=%s tools=%s created=%s",
            session.id,
            len(outbound),
            len(handoff or ""),
            "on" if attach_tools else "off",
            created,
        )
        try:
            run = await _start_run(agent, outbound, images, run_servers)
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        run_id = getattr(run, "id", "")
        logger.info("run started session=%s agent=%s run=%s model=%s", session.id, agent_id, run_id, used_model)
        stream_error: str | None = None
        try:
            async for event in _iter_messages(run):
                if event.get("type") == "error" and not stream_error:
                    stream_error = str(event.get("message") or "")
                yield event
            result = await run.wait()
            logger.info(
                "cursor run finished session=%s run=%s status=%s duration=%s created=%s",
                session.id,
                run_id,
                getattr(result, "status", None),
                getattr(result, "duration_ms", None),
                created,
            )
        except Exception as exc:
            self.runtime.forget(session)
            yield {"type": "error", "message": _public_error(exc, self.settings.cursor_api_key)}
            return
        status = str(getattr(result, "status", "") or "")
        final = getattr(result, "result", None) or ""
        if status == "error":
            logger.warning(
                "cursor run error run=%s request=%s model=%s duration=%s usage=%r error=%r result=%r",
                run_id,
                _request_id(result),
                getattr(result, "model", used_model),
                getattr(result, "duration_ms", None),
                getattr(result, "usage", None),
                getattr(result, "error", None),
                result,
            )
            await _log_conversation(run, run_id)
            self.runtime.forget(session)
            on_agent_id("")
            yield {
                "type": "error",
                "message": _run_error_text(result, run_id, used_model, stream_error),
            }
            return
        if final:
            yield {"type": "result", "text": str(final), "run_id": str(run_id), "status": str(status)}

    async def suggest_title(
        self,
        user: str,
        assistant: str = "",
        *,
        api_key: str = "",
        model: str = "",
    ) -> str | None:
        key = (api_key or "").strip() or self.settings.cursor_api_key
        if not key:
            return None
        used = (model or "").strip() or self.settings.model
        try:
            client = await self.runtime.client()
            try:
                options = self.runtime._agent_options("ha-title", {}, tools=[], model=used, api_key=key)
                agent = await client.create_agent(options)
            except Exception:
                logger.debug("title agent without tools failed, retrying", exc_info=True)
                options = self.runtime._agent_options("ha-title", {}, model=used, api_key=key)
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


def _sdk_model(ident: str, effort: str = "") -> Any:
    name = (ident or "").strip()
    if not name:
        return None
    effort = (effort or "").strip()
    composer = name.lower() in {"composer-2.5", "composer-2"}
    if not composer and not effort:
        return name
    fast = "false" if effort == "high" else "true"
    params = [{"id": "fast", "value": fast}]
    if effort in {"high", "high_fast"}:
        params.append({"id": "effort", "value": "high"})
    model_id = "composer-2.5" if composer else name
    try:
        from cursor_sdk import ModelParameterValue, ModelSelection

        return ModelSelection(
            id=model_id,
            params=[ModelParameterValue(id=item["id"], value=item["value"]) for item in params],
        )
    except Exception:
        return {"id": model_id, "params": params}


def _mcp_identity(servers: dict) -> dict[str, dict[str, str]]:
    """Stable MCP shape: names and endpoints, not rotating Bearer tokens."""
    out: dict[str, dict[str, str]] = {}
    for name, cfg in sorted((servers or {}).items()):
        raw = dict(cfg or {})
        out[str(name)] = {
            "url": str(raw.get("url") or ""),
            "type": str(raw.get("type") or ""),
            "command": str(raw.get("command") or ""),
        }
    return out


def _agent_fingerprint(servers: dict, model: str, effort: str, key_tag: str) -> str:
    return json.dumps(
        {
            "mcp": _mcp_identity(servers),
            "model": _model_fingerprint(model, effort),
            "effort": effort,
            "key": key_tag,
        },
        sort_keys=True,
        default=str,
    )


def _session_idle(updated_at: str) -> bool:
    raw = str(updated_at or "").strip()
    if not raw:
        return False
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() >= _IDLE_RESTORE


def apply_handoff(message: str, handoff: str, fresh: bool = True, question: str = "") -> str:
    """Paste the HA transcript above the question.

    A follow-up a few seconds later can still land on an agent that has no
    memory of the previous turn, so the transcript goes out every time.
    """
    del fresh
    note = (handoff or "").strip()
    if not note:
        return message
    marker = note.split("\n", 1)[0].strip()
    body = message or ""
    if marker and marker in body:
        return body
    asked = (question or "").strip()
    if asked:
        at = body.rfind(asked)
        if at >= 0:
            head = body[:at].rstrip()
            tail = body[at:]
            return f"{head}\n\n{note}\n\n{tail}"
    return f"{note}\n\n{body}"


def _model_fingerprint(ident: str, effort: str = "") -> Any:
    value = _sdk_model(ident, effort)
    if value is None:
        return ident
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value
    params = []
    for item in getattr(value, "params", None) or []:
        if isinstance(item, dict):
            params.append({"id": item.get("id"), "value": item.get("value")})
        else:
            params.append({"id": getattr(item, "id", None), "value": getattr(item, "value", None)})
    return {"id": _model_id(value) or ident, "params": params}


def _nested_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in {"", "error", "none"}:
            return ""
        if text.startswith("<") or "object at 0x" in text:
            return ""
        return text
    if isinstance(value, dict):
        for key in ("message", "msg", "detail", "reason", "code"):
            text = _nested_text(value.get(key))
            if text:
                return text
        return ""
    for key in ("message", "msg", "detail", "reason", "code"):
        text = _nested_text(getattr(value, key, None))
        if text:
            return text
    return _nested_text(str(value))


def _request_id(result: Any) -> str:
    for name in ("request_id", "requestId"):
        value = getattr(result, name, None)
        if value:
            return str(value).strip()
        if isinstance(result, dict) and result.get(name):
            return str(result.get(name)).strip()
    return ""


def _run_error_text(result: Any, run_id: str, model: str, stream_error: str | None = None) -> str:
    for attr in ("result", "error", "message", "error_message", "failure_reason"):
        text = _nested_text(getattr(result, attr, None))
        if text:
            return text
    if stream_error:
        return stream_error
    used = _model_id(getattr(result, "model", None)) or model
    suffix = f" ({run_id})" if run_id else ""
    request = _request_id(result)
    bits = [f"Run failed{suffix}."]
    if used:
        bits.append(f"Cursor ended the {used} run with no assistant text.")
    duration = getattr(result, "duration_ms", None)
    if isinstance(duration, (int, float)) and duration > 0:
        bits.append(f"It stopped after {int(duration)} ms.")
    if request:
        bits.append(f"request_id={request}")
    bits.append("Retry the message.")
    return " ".join(bits)


async def _iter_messages(run: Any) -> AsyncIterator[dict]:
    async for sdk_message in run.messages():
        for event in map_sdk_message(sdk_message):
            yield event


async def _log_conversation(run: Any, run_id: str) -> None:
    try:
        supports = getattr(run, "supports", None)
        if callable(supports) and not supports("conversation"):
            return
        convo = getattr(run, "conversation", None)
        if convo is None:
            return
        data = convo() if callable(convo) else convo
        if hasattr(data, "__await__"):
            data = await data
        items = data if isinstance(data, list) else getattr(data, "messages", None) or []
        kinds = []
        for item in items:
            if isinstance(item, dict):
                kinds.append(str(item.get("type") or item.get("role") or "?"))
            else:
                kinds.append(str(getattr(item, "type", None) or getattr(item, "role", None) or type(item).__name__))
        logger.warning("cursor conversation run=%s turns=%s", run_id, kinds)
    except Exception:
        logger.debug("cursor conversation unavailable run=%s", run_id, exc_info=True)


async def _start_run(agent: Any, message: str, images: list[dict] | None, mcp_servers: dict):
    # Model is set on AgentOptions at create/resume (CURSOR_MODEL or HA JSON `model`).
    # Do not pass it again on send — that path failed runs that worked with env-only.
    payload = cursor_payload(message, images)
    options: dict[str, Any] = {}
    if mcp_servers:
        options["mcp_servers"] = mcp_servers
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
