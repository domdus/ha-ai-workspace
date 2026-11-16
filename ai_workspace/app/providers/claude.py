"""Claude Agent SDK provider (Claude Code CLI via claude-agent-sdk).

Two credentials work: a Claude Plan token (``sk-ant-oat…`` from ``claude setup-token``, billed to the
Claude subscription) or an Anthropic API key (``sk-ant-api…``, billed as API credits). The agent's own
credential wins over the runtime's (a sign-in, then the Docker environment); the token prefix decides
how Claude Code signs in.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, AsyncIterator, Callable

from app.events import _resolved_tool_name, _tool_event, _tool_label
from app.mcp_config import McpConfigError, load_mcp_servers, merge_mcp_servers, servers_from_chat_mcp
from app.providers.base import ProviderInfo
from app.plan_quota import (
    CLAUDE_PLAN_REJECTED_CODE,
    is_plan_rejection,
    plan_events_from_sdk,
    plan_rejection_error,
)
from app.providers.cursor import CursorRuntime, _take_worker_usage, apply_handoff, apply_standing
from app.redact import redact
from app.settings import Settings
from app.small_talk import wants_house_tools
from app.store import Session

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
API_KEY_URL = "https://console.anthropic.com/settings/keys"

MISSING_KEY = (
    "No Claude credential is set for Claude SDK. Open the agent in Home Assistant and use Sign in with "
    "Claude plan, or paste a Claude Plan token (from `claude setup-token`) or an Anthropic API key there. "
    f"Docker runtimes can set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY. API keys: {API_KEY_URL}"
)
# Expired or revoked sign-in / key. The integration shows its own translation for this code.
AUTH_FAILED_CODE = "claude_auth_failed"
AUTH_FAILED = (
    "Anthropic no longer accepts this Claude sign-in or key: it has expired or was revoked. Open the agent's "
    "settings in Home Assistant and sign in with Claude again, or replace the token or API key there."
)
# What Claude Code and the Anthropic API say when the credential is refused. Strong phrases only: a bare
# "401 Unauthorized" can also be an MCP server and must not send people to sign in again.
_AUTH_TEXT = re.compile(
    r"authentication_error|authentication_failed|invalid[\s_-]*(?:x-)?api[\s_-]*key|invalid bearer token"
    r"|oauth token (?:has )?(?:expired|been revoked)|token (?:has )?been revoked|token has expired"
    r"|api error:?\s*401|please run /login|not logged in|invalid_grant",
    re.IGNORECASE,
)
# Assistant message errors from Claude Code → what the chat shows instead of the CLI's own hint.
API_ERRORS = {
    "authentication_failed": AUTH_FAILED,
    "billing_error": (
        "Anthropic refused the request for billing reasons. Check the Claude plan, or the credits of the "
        "API key's account in the Claude Console."
    ),
    "rate_limit": "This Claude credential hit its usage or rate limit. Try again later.",
}
NOT_INSTALLED = "Claude Agent SDK is not installed in this runtime. Update the AI Workspace Runtime."
CLI_MISSING = "The Claude Code CLI that ships with the Claude Agent SDK was not found in this runtime."

# Built-in Claude Code tools an admin chat may use. Normal users and satellites get MCP only.
_WORKSPACE_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
)
# Without Allow internet the shell goes too: curl or python would reach the web anyway (same as Cursor).
_ONLINE_TOOLS = ("WebSearch", "WebFetch", "Bash", "BashOutput", "KillShell", "KillBash")
# Never offered: subagents would start their own model runs outside this chat's tool rules.
_NEVER = ("Task", "Agent")

# AI Workspace effort choices (shared with Cursor) → Claude Code effort levels.
# Save tokens keeps a Claude session while it is small and starts a new one once a turn's context
# (prompt, history and tool results Claude Code sends to the model) reaches this size. A new session
# every turn lost Claude's own tool results and the cached prefix of the chat.
CONTEXT_BUDGET = 40_000


def context_tokens(message: Any) -> int:
    """Context of one model call: everything sent as input, cached or not."""
    if getattr(message, "parent_tool_use_id", None):
        return 0
    usage = getattr(message, "usage", None) or {}
    return sum(
        _int_usage(_pick(usage, key))
        for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )


_EFFORT = {"fast": "low", "high": "high", "high_fast": "medium"}


def _claude_session_id(agent_id: str | None) -> str | None:
    """Claude Code session ids are UUIDs; anything else is a Cursor agent id from before a switch."""
    try:
        return str(uuid.UUID(str(agent_id or "").strip()))
    except ValueError:
        return None


def is_plan_token(credential: str) -> bool:
    return (credential or "").strip().startswith("sk-ant-oat")


def signed_in_token(settings: Settings) -> str:
    """The Claude Plan token saved by "Sign in with Claude" (see app.claude_login), or ""."""
    from app.claude_login import load_token

    return load_token(settings.claude_token_path)


def runtime_credential(settings: Settings) -> str:
    """The runtime's own credential: the signed-in Plan token, then CLAUDE_CODE_OAUTH_TOKEN, then the API key.

    A sign-in is the deliberate, visible choice on the agent form, so it beats whatever a Docker
    environment (or an old App option) carries. A per-agent credential from Home Assistant still
    beats all of them (see ``resolve_credential``).
    """
    return (
        signed_in_token(settings)
        or (settings.claude_oauth_token or "").strip()
        or (settings.anthropic_api_key or "").strip()
    )


def credential_source(settings: Settings) -> str:
    """signed-in | settings | none: where the runtime's own Claude credential comes from.

    ``settings`` is the runtime's environment (CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY) or an old
    App option Anthropic API key. It only counts when nobody signed in.
    """
    if signed_in_token(settings):
        return "signed-in"
    if (settings.claude_oauth_token or "").strip() or (settings.anthropic_api_key or "").strip():
        return "settings"
    return "none"


def resolve_credential(settings: Settings, api_key: str = "") -> str:
    """Agent credential > signed-in token > CLAUDE_CODE_OAUTH_TOKEN > ANTHROPIC_API_KEY (or the old option)."""
    return (api_key or "").strip() or runtime_credential(settings)


def auth_mode(credential: str) -> str:
    """``plan`` for a Claude Plan token, ``api`` for anything else (an Anthropic API key)."""
    return "plan" if is_plan_token(credential) else "api"


def claude_subprocess_env(settings: Settings, credential: str) -> dict[str, str]:
    """Env vars merged onto the Claude Code subprocess (not the whole uvicorn worker)."""
    config_dir = settings.data_dir / "claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    cred = (credential or "").strip()
    plan = auth_mode(cred) == "plan"
    # Exactly one credential reaches Claude Code. The others are blanked: ANTHROPIC_AUTH_TOKEN and
    # ANTHROPIC_API_KEY outrank CLAUDE_CODE_OAUTH_TOKEN, so a stray container variable would
    # otherwise switch a Plan chat to API billing, or the other way round.
    return {
        "CLAUDE_AGENT_SDK_CLIENT_APP": "ha-ai-workspace",
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "CLAUDE_CODE_OAUTH_TOKEN": cred if plan else "",
        "ANTHROPIC_API_KEY": "" if plan else cred,
        "ANTHROPIC_AUTH_TOKEN": "",
    }


def resolve_model(settings: Settings, model: str = "") -> str:
    return (model or "").strip() or (settings.claude_model or "").strip() or DEFAULT_MODEL


def sdk_effort(effort: str) -> str | None:
    return _EFFORT.get((effort or "").strip())


def mcp_for_sdk(servers: dict) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in (servers or {}).items():
        row = dict(cfg or {})
        kind = str(row.get("type") or "").strip().lower()
        if not kind or kind in {"streamable-http", "streamable_http"}:
            row["type"] = "http"
        out[str(name)] = row
    return out


def tool_policy(
    *,
    no_tools: bool,
    full_tools: bool,
    allow_internet: bool,
    mcp_servers: dict,
) -> dict[str, Any]:
    """ClaudeAgentOptions fields for one turn.

    ``tools`` decides which built-in tools exist at all, ``allowed_tools`` which run without
    asking, and permission mode ``dontAsk`` denies everything else (nobody can answer a prompt).
    """
    if no_tools:
        return {"tools": [], "allowed_tools": [], "disallowed_tools": list(_NEVER), "permission_mode": "dontAsk"}
    allowed = [f"mcp__{name}__*" for name in sorted((mcp_servers or {}).keys())]
    if not full_tools:
        return {"tools": [], "allowed_tools": allowed, "disallowed_tools": list(_NEVER), "permission_mode": "dontAsk"}
    builtins = list(_WORKSPACE_TOOLS) + (list(_ONLINE_TOOLS) if allow_internet else [])
    blocked = list(_NEVER) + ([] if allow_internet else list(_ONLINE_TOOLS))
    return {
        "tools": builtins,
        "allowed_tools": allowed + builtins,
        "disallowed_tools": blocked,
        "permission_mode": "dontAsk",
    }


def user_content(message: str, images: list[dict] | None) -> str | list[dict[str, Any]]:
    """Plain text, or Anthropic content blocks when the chat attached images."""
    pictures = [item for item in (images or []) if item.get("data") and item.get("mime")]
    if not pictures:
        return message
    blocks: list[dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": item["mime"], "data": item["data"]}}
        for item in pictures
    ]
    blocks.append({"type": "text", "text": message})
    return blocks


async def _stream_prompt(content: list[dict[str, Any]]):
    yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}


def is_auth_failure(*texts: object, api_error: str = "", status: object = None) -> bool:
    """True when Anthropic refused the credential (expired, revoked or wrong), not for other failures."""
    if str(api_error or "").strip() == "authentication_failed":
        return True
    if status == 401:
        return True
    return any(_AUTH_TEXT.search(str(text)) for text in texts if text)


def error_event(message: str) -> dict[str, Any]:
    """A chat error; the expired-credential one carries a stable code for the integration."""
    event: dict[str, Any] = {"type": "error", "message": message}
    if message == AUTH_FAILED:
        event["code"] = AUTH_FAILED_CODE
    return event


def map_claude_message(message: Any, api_error: str = "") -> list[dict[str, Any]]:
    try:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, UserMessage
    except ImportError:
        return []

    events: list[dict[str, Any]] = []
    if isinstance(message, AssistantMessage):
        if getattr(message, "error", None):
            # Claude Code also writes the failure as assistant text; the result reports it once.
            return events
        for block in message.content or []:
            if isinstance(block, TextBlock):
                if (block.text or "").strip():
                    events.append({"type": "text", "delta": str(block.text)})
            elif isinstance(block, ThinkingBlock):
                events.append({"type": "status", "text": "Thinking..."})
            elif isinstance(block, ToolUseBlock):
                name = _resolved_tool_name(block.name, block.input)
                events.append(_tool_event(name, "start", f"Calling {_tool_label(name)}...", block.id))
        return events
    if isinstance(message, UserMessage):
        blocks = message.content if isinstance(message.content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock):
                text = "Tool failed" if getattr(block, "is_error", False) else "Finished"
                events.append(_tool_event("tool", "end", text, block.tool_use_id))
        return events
    if isinstance(message, ResultMessage):
        if message.is_error or str(getattr(message, "subtype", "") or "").startswith("error_"):
            if is_auth_failure(
                message.result,
                *(getattr(message, "errors", None) or []),
                api_error=api_error,
                status=getattr(message, "api_error_status", None),
            ):
                events.append(error_event(AUTH_FAILED))
            else:
                if api_error == "rate_limit" or is_plan_rejection(api_error=api_error, text=str(message.result or "")):
                    events.append(plan_rejection_error("claude", None))
                else:
                    text = (
                        API_ERRORS.get(api_error)
                        or str(message.result or "").strip()
                        or "Claude stopped without an answer."
                    )
                    events.append(error_event(text[:400]))
        else:
            events.append(
                {
                    "type": "result",
                    "text": str(message.result or ""),
                    "run_id": str(message.session_id or ""),
                    "status": "finished",
                }
            )
        usage_event = usage_from_result(message)
        if usage_event:
            events.append(usage_event)
    return events


def _int_usage(value: object) -> int:
    try:
        if value is None or isinstance(value, bool):
            return 0
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _pick(blob: Any, *keys: str) -> object:
    for key in keys:
        value = blob.get(key) if isinstance(blob, dict) else getattr(blob, key, None)
        if value:
            return value
    return None


def usage_from_result(message: Any) -> dict[str, Any] | None:
    usage = getattr(message, "usage", None) or {}
    prompt = _int_usage(_pick(usage, "input_tokens"))
    completion = _int_usage(_pick(usage, "output_tokens"))
    cache_read = _int_usage(_pick(usage, "cache_read_input_tokens"))
    cache_write = _int_usage(_pick(usage, "cache_creation_input_tokens"))
    cost = getattr(message, "total_cost_usd", None)
    try:
        cost_usd = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_usd = None
    model = ""
    model_usage = getattr(message, "model_usage", None) or {}
    if isinstance(model_usage, dict) and model_usage:
        # The main model has the most output; small helper models (titles, checks) come along too.
        model = max(
            model_usage,
            key=lambda name: _int_usage(_pick(model_usage[name] or {}, "outputTokens", "output_tokens")),
        )
        if not (prompt or completion):
            for blob in model_usage.values():
                prompt += _int_usage(_pick(blob or {}, "inputTokens", "input_tokens"))
                completion += _int_usage(_pick(blob or {}, "outputTokens", "output_tokens"))
                cache_read += _int_usage(_pick(blob or {}, "cacheReadInputTokens", "cache_read_input_tokens"))
                cache_write += _int_usage(
                    _pick(blob or {}, "cacheCreationInputTokens", "cache_creation_input_tokens")
                )
    if not (prompt or completion or cost_usd):
        return None
    return {
        "type": "usage",
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": prompt + completion,
        "cost_usd": cost_usd,
        "run_id": str(getattr(message, "session_id", "") or ""),
    }


def public_error(exc: Exception, credential: str) -> str:
    try:
        from claude_agent_sdk import CLINotFoundError
    except ImportError:  # pragma: no cover - the provider is only built with the SDK installed
        CLINotFoundError = ()  # type: ignore[assignment]
    if CLINotFoundError and isinstance(exc, CLINotFoundError):
        return CLI_MISSING
    if is_auth_failure(
        str(exc),
        getattr(exc, "stderr", None),
        getattr(exc, "result", None),
        *(getattr(exc, "errors", None) or []),
        status=getattr(exc, "api_error_status", None),
    ):
        return AUTH_FAILED
    text = redact(str(exc), [credential]).strip() or type(exc).__name__
    return text[:400]


class ClaudeProvider:
    def __init__(self, settings: Settings, runtime: CursorRuntime) -> None:
        self.settings = settings
        self.runtime = runtime
        # Context size of each chat's last model call, for Save tokens.
        self._context: dict[str, int] = {}

    def keeps_session(self, session_id: str, fresh: bool) -> bool:
        """Off: always resume. Save tokens: resume only a session measured below CONTEXT_BUDGET.

        A session this Runtime has not measured (for example after a restart) may be any size.
        """
        return not fresh or self._context.get(session_id, CONTEXT_BUDGET) < CONTEXT_BUDGET

    @property
    def info(self) -> ProviderInfo:
        if not runtime_credential(self.settings):
            # Agents may still bring their own credential; the integration checks that on the form.
            return ProviderInfo("claude", "Claude", False, MISSING_KEY)
        return ProviderInfo("claude", "Claude", True, None)

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
        credential = resolve_credential(self.settings, api_key)
        if not credential:
            yield {"type": "error", "message": MISSING_KEY}
            return
        try:
            exclusive = bool((mcp or {}).get("exclusive"))
            file_servers = {} if exclusive else load_mcp_servers(self.settings.mcp_config_path)
            mcp_servers = merge_mcp_servers(file_servers, servers_from_chat_mcp(mcp))
        except McpConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, query
        except ImportError:
            yield {"type": "error", "message": NOT_INSTALLED}
            return

        asked = (question or "").strip()
        attach_tools = not no_tools and (bool(images) or wants_house_tools(asked or message))
        run_servers = mcp_for_sdk(self.runtime.wrap_mcp(mcp_servers, session.id)) if attach_tools else {}
        resume = _claude_session_id(session.agent_id) if self.keeps_session(session.id, fresh) else None
        cold = not resume
        if fresh and not resume and session.agent_id:
            logger.info("claude session=%s grew past %s tokens, starting a new one", session.id, CONTEXT_BUDGET)
        self._context.pop(session.id, None)
        outbound = apply_standing(message, prompt, cold)
        outbound = apply_handoff(outbound, handoff, cold, question=asked or question)
        content = user_content(outbound, images)
        yield {"type": "status", "text": "Thinking..."}

        # Claude Code may only say on stderr that the credential was refused.
        refused: list[bool] = []

        def on_stderr(line: str) -> None:
            if not refused and is_auth_failure(line):
                refused.append(True)
            logger.debug("claude cli: %s", redact(line, [credential]))

        options_kwargs: dict[str, Any] = {
            "cwd": str(self.settings.workspace_dir),
            # No user, project or local settings, CLAUDE.md, skills or hooks: only what this chat sends.
            "setting_sources": [],
            "strict_mcp_config": True,
            "model": resolve_model(self.settings, model or ""),
            "env": claude_subprocess_env(self.settings, credential),
            "resume": resume,
            "mcp_servers": run_servers,
            "stderr": on_stderr,
            **tool_policy(
                no_tools=no_tools,
                full_tools=full_tools,
                allow_internet=allow_internet,
                mcp_servers=run_servers,
            ),
        }
        level = sdk_effort(effort)
        if level:
            options_kwargs["effort"] = level
        finished = False
        api_error = ""
        try:
            self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
            options = ClaudeAgentOptions(**options_kwargs)
            stream = query(prompt=content if isinstance(content, str) else _stream_prompt(content), options=options)
            # Read the stream to its end: leaving it early closes the SDK's generator from the wrong task.
            book = self.runtime.plan_quota
            async for sdk_message in stream:
                if finished:
                    continue
                for notice in plan_events_from_sdk(book, "claude", sdk_message):
                    yield notice
                if isinstance(sdk_message, AssistantMessage):
                    if sdk_message.error:
                        api_error = str(sdk_message.error)
                    size = context_tokens(sdk_message)
                    if size:
                        self._context[session.id] = size
                if isinstance(sdk_message, ResultMessage):
                    finished = True
                    sid = str(sdk_message.session_id or "")
                    if sid:
                        on_agent_id(sid)
                for event in map_claude_message(sdk_message, api_error):
                    if event.get("type") == "error" and event.get("code") == CLAUDE_PLAN_REJECTED_CODE:
                        snap = book.get("claude")
                        event = plan_rejection_error("claude", snap)
                        if not event.get("message"):
                            event["message"] = API_ERRORS.get("rate_limit", "")
                    yield event
                # Worker jobs (agent_run / agent_job) this chat finished over the MCP proxy.
                for worker in _take_worker_usage(self.runtime, session.id):
                    yield worker
            if not finished:
                refused_now = is_auth_failure(api_error=api_error) or bool(refused)
                yield error_event(AUTH_FAILED if refused_now else "Claude stopped without an answer.")
        except Exception as exc:
            text = public_error(exc, credential)
            if not finished and text != AUTH_FAILED and (refused or is_auth_failure(api_error=api_error)):
                text = AUTH_FAILED
            if finished:
                # The result is already in the chat. Claude Code exits non-zero after an error result.
                logger.debug("claude cli exit after result session=%s: %s", session.id, text)
            else:
                logger.warning("claude turn failed session=%s: %s", session.id, text)
                yield error_event(text)
        # Worker jobs that finished after the last streamed message, or before a failed turn, still count.
        for worker in _take_worker_usage(self.runtime, session.id):
            yield worker
