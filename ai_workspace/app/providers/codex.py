"""OpenAI Codex chats on the AI Workspace Runtime (the official openai-codex Python SDK).

The SDK drives a local `codex app-server` over JSON-RPC (stdio) and ships the matching Codex CLI
(openai-codex-cli-bin). Every turn gets its own app-server process in the runtime's workspace; the
conversation continues across turns and restarts through Codex threads kept in CODEX_HOME.

Credentials, first one found wins:
  the agent's OpenAI API key   sent by Home Assistant with the turn, handed to Codex in memory
  CODEX_HOME/auth.json         "Sign in with ChatGPT" on the agent form (plan usage)
  OPENAI_API_KEY               on a Docker runtime (API billing)

Tools follow the same rules as Cursor and Claude SDK chats:
  no tools        read-only, no shell, no MCP (Save tokens' chat-only mode)
  normal users    MCP only: read-only sandbox, no shell, no web
  admin chats     plus file edits in the workspace (apply_patch), still no shell
  Allow internet  plus the shell and live web search
The container is the sandbox (Codex's own bubblewrap sandbox needs user namespaces Docker does not
allow by default; CODEX_SANDBOX=codex uses it when they are). Nobody can answer an approval prompt
in a chat turn, so anything that would ask is refused. No AGENTS.md, skills, hooks, plugins, apps or
memories are loaded: only what the chat sends.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from app.codex_login import cli_path, credential_source, sdk_config, sdk_installed
from app.events import _tool_event
from app.mcp_config import McpConfigError, load_mcp_servers, merge_mcp_servers, servers_from_chat_mcp
from app.plan_quota import plan_events_from_sdk, plan_rejection_error
from app.providers.base import ProviderInfo
from app.providers.cursor import CursorRuntime, _take_worker_usage, apply_handoff, apply_standing
from app.redact import redact
from app.settings import Settings
from app.small_talk import wants_house_tools
from app.store import Session

logger = logging.getLogger(__name__)

MISSING_KEY = (
    "OpenAI Codex has no credential on the AI Workspace Runtime. Open the agent's settings and pick "
    "Sign in with ChatGPT, or paste an OpenAI API key on the agent."
)
NOT_INSTALLED = "OpenAI Codex is not installed in this runtime. Update the AI Workspace Runtime."
CLI_MISSING = "The Codex CLI that ships with openai-codex was not found in this runtime. Update the AI Workspace Runtime."
AUTH_FAILED = (
    "OpenAI refused the Codex credential. Open the agent's settings and sign in with ChatGPT again, "
    "or check the OpenAI API key."
)
AUTH_FAILED_CODE = "codex_auth_failed"
# How Codex words a ChatGPT sign-in that no longer works (expired or reused refresh token, revoked).
_AUTH_MARKS = (
    "401",
    "unauthorized",
    "sign in again",
    "log in again",
    "login again",
    "refresh token",
    "refresh_token",
    "token_expired",
    "invalid_grant",
    "not logged in",
)
RATE_LIMITS_SECONDS = 10
START_SECONDS = 60
INTERRUPT_SECONDS = 10
# Save tokens keeps a Codex thread while a model call's input stays below this (as on Claude).
CONTEXT_BUDGET = 40_000
# Codex answers this when a thread to resume is gone (for example a new data folder).
_THREAD_GONE = ("no rollout found", "thread not found", "unknown thread", "no thread found")
# AI Workspace effort choices (shared with Cursor) -> Codex reasoning efforts.
_EFFORT = {"fast": "low", "high": "high", "high_fast": "medium"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")
# Never wanted in a chat turn.
_ALWAYS_OFF = {
    "hooks": False,
    "apps": False,
    "plugins": False,
    "memories": False,
    "goals": False,
    "browser_use": False,
    "computer_use": False,
    "in_app_browser": False,
    "image_generation": False,
}
_NO_SHELL = {"shell_tool": False, "unified_exec": False}
_API_ERRORS = {
    "usageLimitExceeded": "This ChatGPT plan or API key hit its Codex usage limit. Try again later.",
    "rateLimitExceeded": "This Codex credential hit a rate limit. Try again later.",
    "serverOverloaded": "OpenAI is overloaded right now. Try again later.",
}


# ---- options -------------------------------------------------------------------------------------


def resolve_model(settings: Settings, model: str) -> str:
    """'' means Codex's own default model for the account."""
    value = (model or "").strip()
    if value.lower() in {"default", "codex"}:
        value = ""
    return value or settings.codex_model


def effort_for(effort: str) -> str | None:
    return _EFFORT.get((effort or "").strip().lower())


def resolve_credential(settings: Settings, api_key: str = "") -> tuple[str, str]:
    """(kind, key): kind is "agent-api", "chatgpt", "api-key" (auth.json), "env-api" or "none"."""
    own = (api_key or "").strip()
    if own:
        return "agent-api", own
    source = credential_source(settings)
    if source == "env-api":
        return source, settings.openai_api_key
    return source, ""


def mcp_config(servers: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Runtime MCP servers (already behind the runtime's proxy) -> Codex mcp_servers."""
    out: dict[str, Any] = {}
    skipped: list[str] = []
    for name, cfg in sorted((servers or {}).items()):
        key = _SAFE_NAME.sub("_", str(name))[:64] or "server"
        if str(cfg.get("type") or "").lower() == "sse" or not cfg.get("url"):
            skipped.append(str(name))
            continue
        item: dict[str, Any] = {"url": str(cfg["url"])}
        if cfg.get("headers"):
            item["http_headers"] = {str(k): str(v) for k, v in cfg["headers"].items()}
        out[key] = item
    return out, skipped


def tool_policy(
    *, no_tools: bool, full_tools: bool, allow_internet: bool, servers: dict[str, dict[str, Any]], sandbox_mode: str = "container"
) -> tuple[str, dict[str, Any]]:
    """(sandbox preset name, thread config) for one turn."""
    features: dict[str, Any] = dict(_ALWAYS_OFF)
    config: dict[str, Any] = {
        # No instructions from files in the workspace or CODEX_HOME.
        "project_doc_max_bytes": 0,
        "skills": {"bundled": {"enabled": False}},
        "web_search": "live" if full_tools and allow_internet and not no_tools else "disabled",
    }
    own_sandbox = sandbox_mode == "codex"
    if no_tools or not full_tools:
        sandbox = "read_only"
        features.update(_NO_SHELL)
        if no_tools:
            features["view_image"] = False
    elif allow_internet:
        sandbox = "workspace_write" if own_sandbox else "full_access"
        if own_sandbox:
            config["sandbox_workspace_write"] = {"network_access": True}
    else:
        # File edits in the workspace (apply_patch), no shell: a shell could reach the network.
        sandbox = "full_access"
        features.update(_NO_SHELL)
    config["features"] = features
    if not no_tools:
        mapped, _skipped = mcp_config(servers)
        if mapped:
            config["mcp_servers"] = mapped
    return sandbox, config


def turn_input(message: str, images: list[dict] | None) -> Any:
    pictures = [item for item in (images or []) if item.get("data") and item.get("mime")]
    if not pictures:
        return message
    from openai_codex import ImageInput, TextInput

    items: list[Any] = [ImageInput(url=f"data:{item['mime']};base64,{item['data']}") for item in pictures]
    items.append(TextInput(message))
    return items


# ---- events --------------------------------------------------------------------------------------


def as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            data = dump(by_alias=True, mode="json", exclude_none=True)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_name(item: dict[str, Any]) -> str:
    kind = item.get("type")
    if kind == "commandExecution":
        return "shell"
    if kind == "fileChange":
        return "edit"
    if kind == "mcpToolCall":
        return f"mcp__{item.get('server') or 'mcp'}__{item.get('tool') or 'tool'}"
    if kind == "webSearch":
        return "web_search"
    if kind == "dynamicToolCall":
        return str(item.get("tool") or item.get("name") or "tool")
    return ""


def _failed(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    if status in {"failed", "declined", "error"}:
        return True
    if item.get("type") == "commandExecution" and item.get("exitCode") not in (None, 0):
        return True
    return bool(item.get("error"))


@dataclass
class TurnState:
    parts: list[str] = field(default_factory=list)
    streamed: set[str] = field(default_factory=set)
    messages: list[tuple[str, str]] = field(default_factory=list)  # (phase, text)
    usage_first: dict[str, Any] | None = None
    usage_last: dict[str, Any] | None = None
    context: int = 0
    status: str = ""
    error: dict[str, Any] | None = None
    stream_error: dict[str, Any] | None = None

    def final_text(self) -> str:
        for phase, text in reversed(self.messages):
            if phase == "final_answer" and text.strip():
                return text.strip()
        for _phase, text in reversed(self.messages):
            if text.strip():
                return text.strip()
        return "".join(self.parts).strip()


def map_notification(method: str, payload: Any, state: TurnState) -> list[dict[str, Any]]:
    """Codex app-server notifications -> chat events; records text, usage and the end of the turn."""
    data = as_dict(payload)
    events: list[dict[str, Any]] = []
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    if method == "item/agentMessage/delta":
        delta = str(data.get("delta") or "")
        if delta:
            state.streamed.add(str(data.get("itemId") or ""))
            state.parts.append(delta)
            events.append({"type": "text", "delta": delta})
    elif method == "item/started":
        kind = item.get("type")
        item_id = str(item.get("id") or "")
        if kind == "reasoning":
            events.append({"type": "status", "text": "Thinking..."})
        elif kind == "commandExecution":
            events.append(_tool_event("shell", "start", _short(f"Running {item.get('command') or ''}"), item_id))
        elif kind == "webSearch":
            events.append(_tool_event("web_search", "start", _short(f"Searching the web: {item.get('query') or ''}"), item_id))
        elif _tool_name(item):
            name = _tool_name(item)
            events.append(_tool_event(name, "start", f"Calling {name}...", item_id))
    elif method == "item/completed":
        kind = item.get("type")
        if kind == "agentMessage":
            text = str(item.get("text") or "")
            item_id = str(item.get("id") or "")
            state.messages.append((str(item.get("phase") or ""), text))
            if text.strip() and item_id not in state.streamed:
                if state.parts and not state.parts[-1].endswith("\n"):
                    state.parts.append("\n\n")
                    events.append({"type": "text", "delta": "\n\n"})
                state.parts.append(text)
                events.append({"type": "text", "delta": text})
        elif _tool_name(item):
            name = _tool_name(item)
            events.append(_tool_event(name, "end", "Tool failed" if _failed(item) else "Finished", str(item.get("id") or "")))
    elif method == "thread/tokenUsage/updated":
        usage = data.get("tokenUsage") or {}
        if isinstance(usage, dict):
            if state.usage_first is None:
                state.usage_first = usage
            state.usage_last = usage
            last = usage.get("last") or {}
            # The last model call's whole input (OpenAI counts cached input inside inputTokens).
            state.context = _n(last, "inputTokens") or state.context
    elif method == "error":
        error = data.get("error") or {}
        if data.get("willRetry"):
            events.append({"type": "status", "text": _short(str(error.get("message") or "Reconnecting..."), 120)})
        elif isinstance(error, dict):
            state.stream_error = error
    elif method == "turn/completed":
        turn = data.get("turn") or {}
        state.status = str(turn.get("status") or "")
        state.error = turn.get("error") if isinstance(turn.get("error"), dict) else None
    return events


def _n(blob: dict[str, Any] | None, key: str) -> int:
    try:
        return max(0, int((blob or {}).get(key) or 0))
    except (TypeError, ValueError):
        return 0


def usage_event(state: TurnState, model: str, run_id: str) -> dict[str, Any] | None:
    """This turn's tokens. Codex reports thread totals, so a resumed thread's earlier turns are taken off.

    Reported Anthropic-style (cache apart from input), as the Claude SDK chats do: OpenAI counts the
    cached part inside ``inputTokens``.
    """
    if state.usage_last is None:
        return None
    first = state.usage_first or state.usage_last
    end = state.usage_last.get("total") or {}
    keys = ("inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens", "totalTokens")
    base = {key: _n(first.get("total"), key) - _n(first.get("last"), key) for key in keys}
    turn = {key: max(0, _n(end, key) - max(0, base[key])) for key in keys}
    cached = min(turn["cachedInputTokens"], turn["inputTokens"])
    prompt = turn["inputTokens"] - cached
    completion = turn["outputTokens"]
    if not (prompt or completion or cached):
        return None
    return {
        "type": "usage",
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_tokens": cached,
        "cache_write_tokens": turn["cacheWriteInputTokens"],
        "total_tokens": prompt + cached + completion,
        # Codex reports no price: plan usage is not billed per token.
        "cost_usd": None,
        "run_id": run_id,
    }


def _error_kind(error: dict[str, Any] | None) -> str:
    info = (error or {}).get("codexErrorInfo")
    if isinstance(info, str):
        return info
    if isinstance(info, dict) and info:
        key = next(iter(info))
        status = info[key].get("httpStatusCode") if isinstance(info[key], dict) else None
        if status == 401:
            return "unauthorized"
        if status == 429:
            return "rateLimitExceeded"
        return str(key)
    return ""


def is_auth_failure(text: str) -> bool:
    low = str(text or "").lower()
    return any(mark in low for mark in _AUTH_MARKS)


def auth_failed_event() -> dict[str, Any]:
    """The integration shows this in the chat's language: sign in with ChatGPT again (or a new key)."""
    return {"type": "error", "message": AUTH_FAILED, "code": AUTH_FAILED_CODE}


def error_event(error: dict[str, Any] | None, model: str, secrets: list[str], book: Any = None) -> dict[str, Any]:
    kind = _error_kind(error)
    message = redact(str((error or {}).get("message") or ""), secrets).strip()
    if kind == "unauthorized" or (kind not in _API_ERRORS and kind != "modelNotFound" and is_auth_failure(message)):
        return auth_failed_event()
    if kind == "usageLimitExceeded" and book is not None:
        event = plan_rejection_error("codex", book.get("codex"))
        event["message"] = _API_ERRORS[kind]
        return event
    if kind == "modelNotFound":
        return {"type": "error", "message": f"Codex does not offer the model {model or '(default)'} for this account. {message}".strip()[:400]}
    known = _API_ERRORS.get(kind)
    if known:
        return {"type": "error", "message": (known + (f" ({_short(message, 200)})" if message else ""))[:400]}
    return {"type": "error", "message": (message or "Codex stopped without an answer.")[:400]}


# ---- the provider --------------------------------------------------------------------------------


class CodexProvider:
    def __init__(self, settings: Settings, runtime: CursorRuntime, factory: Callable[[Any], Any] | None = None) -> None:
        self.settings = settings
        self.runtime = runtime
        # Test seam: (CodexConfig) -> an AsyncCodex-like object.
        self._factory = factory
        # Input size of each chat's last model call, for Save tokens.
        self._context: dict[str, int] = {}

    @property
    def info(self) -> ProviderInfo:
        if not sdk_installed():
            return ProviderInfo("codex", "Codex", False, NOT_INSTALLED)
        if credential_source(self.settings) == "none":
            # Agents may still bring their own OpenAI API key; the integration checks that on the form.
            return ProviderInfo("codex", "Codex", False, MISSING_KEY)
        return ProviderInfo("codex", "Codex", True, None)

    def keeps_session(self, session_id: str, fresh: bool) -> bool:
        """Off: always resume. Save tokens: resume only a thread measured below CONTEXT_BUDGET."""
        return not fresh or self._context.get(session_id, CONTEXT_BUDGET) < CONTEXT_BUDGET

    def _codex(self, *, ephemeral_auth: bool) -> Any:
        config = sdk_config(
            self.settings, store="ephemeral" if ephemeral_auth else "file", cwd=str(self.settings.workspace_dir)
        )
        if self._factory is not None:
            return self._factory(config)
        from openai_codex import AsyncCodex

        return AsyncCodex(config)

    async def _thread(self, codex: Any, resume: str | None, common: dict[str, Any]) -> tuple[Any, bool]:
        if resume:
            try:
                return await codex.thread_resume(resume, **common), False
            except Exception as exc:
                if not any(mark in str(exc).lower() for mark in _THREAD_GONE):
                    raise
                logger.info("codex thread %s is gone, starting a new one", resume)
        return await codex.thread_start(**common), True

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
        prompt: str = "",
        full_tools: bool = False,
        allow_internet: bool = False,
        fresh: bool = False,
        no_tools: bool = False,
        **_kwargs,
    ) -> AsyncIterator[dict]:
        if not sdk_installed():
            yield {"type": "error", "message": NOT_INSTALLED}
            return
        if not cli_path() and self._factory is None:
            yield {"type": "error", "message": CLI_MISSING}
            return
        kind, key = resolve_credential(self.settings, api_key)
        if kind == "none":
            yield {"type": "error", "message": MISSING_KEY}
            return
        secrets = [key] if key else []
        try:
            exclusive = bool((mcp or {}).get("exclusive"))
            file_servers = {} if exclusive else load_mcp_servers(self.settings.mcp_config_path)
            mcp_servers = merge_mcp_servers(file_servers, servers_from_chat_mcp(mcp))
        except McpConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        asked = (question or "").strip()
        attach_tools = not no_tools and (bool(images) or wants_house_tools(asked or message))
        run_servers = self.runtime.wrap_mcp(mcp_servers, session.id) if attach_tools else {}
        resume = (session.agent_id or None) if self.keeps_session(session.id, fresh) else None
        if fresh and not resume and session.agent_id:
            logger.info("codex session=%s grew past %s tokens, starting a new thread", session.id, CONTEXT_BUDGET)
        self._context.pop(session.id, None)
        yield {"type": "status", "text": "Thinking..."}

        from openai_codex import ApprovalMode, Sandbox

        sandbox_name, config = tool_policy(
            no_tools=no_tools,
            full_tools=full_tools,
            allow_internet=allow_internet,
            servers=run_servers,
            sandbox_mode=self.settings.codex_sandbox,
        )
        used_model = resolve_model(self.settings, model or "")
        common = {
            # Nobody can answer an approval prompt in a chat turn: anything that would ask is refused.
            "approval_mode": ApprovalMode.deny_all,
            "cwd": str(self.settings.workspace_dir),
            "sandbox": getattr(Sandbox, sandbox_name),
            "config": config,
            "model": used_model or None,
        }
        book = self.runtime.plan_quota
        state = TurnState()
        thread_id = ""
        self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        codex = self._codex(ephemeral_auth=kind in {"agent-api", "env-api"})
        try:
            try:
                await asyncio.wait_for(codex.__aenter__(), START_SECONDS)
                if kind in {"agent-api", "env-api"}:
                    await codex.login_api_key(key)
                thread, created = await self._thread(codex, resume, common)
                thread_id = str(getattr(thread, "id", "") or "")
                if thread_id:
                    # Kept even if the turn fails: the thread holds the conversation so far.
                    on_agent_id(thread_id)
                outbound = apply_standing(message, prompt, created)
                outbound = apply_handoff(outbound, handoff, created, question=asked or question)
                handle = await thread.turn(turn_input(outbound, images), effort=effort_for(effort))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                text = self._public(exc, secrets)
                logger.warning("codex turn failed session=%s: %s", session.id, text)
                yield self._error(text)
                return
            stream = handle.stream()
            try:
                async for note in stream:
                    method = str(getattr(note, "method", ""))
                    payload = getattr(note, "payload", None)
                    if method == "account/rateLimits/updated":
                        for notice in plan_events_from_sdk(book, "codex", as_dict(payload)):
                            yield notice
                        continue
                    for event in map_notification(method, payload, state):
                        yield event
                    for worker in _take_worker_usage(self.runtime, session.id):
                        yield worker
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(asyncio.wait_for(handle.interrupt(), INTERRUPT_SECONDS))
                except Exception:
                    logger.debug("codex interrupt failed", exc_info=True)
                raise
            except Exception as exc:
                if not state.status:
                    text = self._public(exc, secrets)
                    logger.warning("codex stream failed session=%s: %s", session.id, text)
                    yield self._error(text)
                    return
                logger.debug("codex stream ended after the turn session=%s", session.id, exc_info=True)
            finally:
                try:
                    await stream.aclose()
                except Exception:
                    pass
            if kind == "chatgpt":
                # Codex sends plan usage as a notification outside the turn; ask for it once instead.
                for notice in await self._plan_limits(codex, book):
                    yield notice
        finally:
            try:
                await asyncio.shield(asyncio.wait_for(codex.close(), 10))
            except Exception:
                logger.debug("codex close failed", exc_info=True)
        if state.context:
            self._context[session.id] = state.context
        usage = usage_event(state, used_model, thread_id)
        if state.status == "completed":
            yield {"type": "result", "text": state.final_text(), "run_id": thread_id, "status": "finished"}
        elif state.status == "interrupted" and not (state.error or state.stream_error):
            yield {"type": "error", "message": "The Codex turn was interrupted."}
        else:
            error = state.error or state.stream_error
            if error is None:
                yield {"type": "error", "message": "Codex stopped without finishing the turn."}
            else:
                yield error_event(error, used_model, secrets, book)
        if usage:
            yield usage
        for worker in _take_worker_usage(self.runtime, session.id):
            yield worker

    def _public(self, exc: BaseException, secrets: list[str]) -> str:
        if isinstance(exc, FileNotFoundError) and "codex" in str(exc).lower():
            return CLI_MISSING
        text = (redact(str(exc), secrets).strip() or type(exc).__name__)[:400]
        if is_auth_failure(text):
            return AUTH_FAILED
        return text

    @staticmethod
    def _error(text: str) -> dict[str, Any]:
        return auth_failed_event() if text == AUTH_FAILED else {"type": "error", "message": text}

    async def _plan_limits(self, codex: Any, book: Any) -> list[dict[str, Any]]:
        """ChatGPT plan windows (account/rateLimits/read) -> plan_notice / plan_usage events. Never raises."""
        if book is None:
            return []
        request = getattr(getattr(codex, "_client", None), "request", None)
        if not callable(request):
            return []
        try:
            from openai_codex.generated.v2_all import GetAccountRateLimitsResponse

            answer = await asyncio.wait_for(
                request("account/rateLimits/read", None, response_model=GetAccountRateLimitsResponse),
                RATE_LIMITS_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("codex rate limits not read", exc_info=True)
            return []
        return plan_events_from_sdk(book, "codex", as_dict(answer))

    async def models(self, api_key: str = "") -> list[dict[str, str]]:
        """Models the Codex account offers."""
        kind, key = resolve_credential(self.settings, api_key)
        if kind == "none" or not sdk_installed():
            return []
        codex = self._codex(ephemeral_auth=kind in {"agent-api", "env-api"})
        try:
            await asyncio.wait_for(codex.__aenter__(), START_SECONDS)
            if kind in {"agent-api", "env-api"}:
                await codex.login_api_key(key)
            listed = await asyncio.wait_for(codex.models(), 30)
            return [
                {"id": str(item.id), "name": str(getattr(item, "display_name", "") or item.id)}
                for item in getattr(listed, "data", []) or []
                if getattr(item, "id", "") and not getattr(item, "hidden", False)
            ]
        finally:
            try:
                await asyncio.wait_for(codex.close(), 10)
            except Exception:
                pass


__all__ = ["CodexProvider", "tool_policy", "usage_event", "map_notification", "CONTEXT_BUDGET"]
