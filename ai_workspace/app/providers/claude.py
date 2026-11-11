"""Claude Agent SDK provider (Claude Code CLI via claude-agent-sdk).

Authentication is an Anthropic API key only (Claude Console). Anthropic does not allow
third-party products built on the Agent SDK to sign in with Claude.ai subscription plans,
so Plan (OAuth) tokens are refused with a clear message instead of being forwarded.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Callable

from app.events import _resolved_tool_name, _tool_event, _tool_label
from app.mcp_config import McpConfigError, load_mcp_servers, merge_mcp_servers, servers_from_chat_mcp
from app.providers.base import ProviderInfo
from app.providers.cursor import CursorRuntime, apply_handoff, apply_standing
from app.redact import redact
from app.settings import Settings
from app.small_talk import wants_house_tools
from app.store import Session

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
API_KEY_URL = "https://console.anthropic.com/settings/keys"

MISSING_KEY = (
    "No Anthropic API key is set for Claude SDK. Add one on the agent in Home Assistant, "
    f"or set ANTHROPIC_API_KEY (App option anthropic_api_key) on the runtime. Keys: {API_KEY_URL}"
)
PLAN_TOKEN = (
    "This is a Claude.ai subscription token (sk-ant-oat…). Claude SDK agents need an Anthropic API key "
    f"(sk-ant-api…) from the Claude Console: {API_KEY_URL}. Anthropic does not allow apps built on the "
    "Agent SDK to use Claude.ai plan sign-ins."
)
# Assistant message errors from Claude Code → what the chat shows instead of the CLI's own hint.
API_ERRORS = {
    "authentication_failed": (
        "Anthropic refused the API key. Check the Anthropic API key on the agent, "
        "or the runtime's anthropic_api_key."
    ),
    "billing_error": (
        "Anthropic refused the request for billing reasons. Check the credits of this API key's "
        "account in the Claude Console."
    ),
    "rate_limit": "This API key hit Anthropic's rate limit. Try again in a moment.",
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
_EFFORT = {"fast": "low", "high": "high", "high_fast": "medium"}


def is_plan_token(credential: str) -> bool:
    return (credential or "").strip().startswith("sk-ant-oat")


def resolve_credential(settings: Settings, api_key: str = "") -> str:
    """The agent's own key wins over the runtime key."""
    return (api_key or "").strip() or (settings.anthropic_api_key or "").strip()


def claude_subprocess_env(settings: Settings, credential: str) -> dict[str, str]:
    """Env vars merged onto the Claude Code subprocess (not the whole uvicorn worker)."""
    config_dir = settings.data_dir / "claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return {
        "CLAUDE_AGENT_SDK_CLIENT_APP": "ha-ai-workspace",
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "ANTHROPIC_API_KEY": (credential or "").strip(),
        # These outrank ANTHROPIC_API_KEY in Claude Code. Blank them so a stray container
        # variable cannot switch this chat to another account or a subscription sign-in.
        "ANTHROPIC_AUTH_TOKEN": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
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
            text = API_ERRORS.get(api_error) or str(message.result or "").strip() or "Claude stopped without an answer."
            events.append({"type": "error", "message": text[:400]})
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
    text = redact(str(exc), [credential]).strip() or type(exc).__name__
    return text[:400]


class ClaudeProvider:
    def __init__(self, settings: Settings, runtime: CursorRuntime) -> None:
        self.settings = settings
        self.runtime = runtime

    @property
    def info(self) -> ProviderInfo:
        key = (self.settings.anthropic_api_key or "").strip()
        if is_plan_token(key):
            return ProviderInfo("claude", "Claude", False, PLAN_TOKEN)
        if not key:
            # Agents may still bring their own key; the integration checks that on the form.
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
        if is_plan_token(credential):
            yield {"type": "error", "message": PLAN_TOKEN}
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
        resume = None if fresh else (session.agent_id or None)
        cold = fresh or not resume
        outbound = apply_standing(message, prompt, cold)
        outbound = apply_handoff(outbound, handoff, cold, question=asked or question)
        content = user_content(outbound, images)
        yield {"type": "status", "text": "Thinking..."}

        options_kwargs: dict[str, Any] = {
            "cwd": str(self.settings.workspace_dir),
            # No user, project or local settings, CLAUDE.md, skills or hooks: only what this chat sends.
            "setting_sources": [],
            "strict_mcp_config": True,
            "model": resolve_model(self.settings, model or ""),
            "env": claude_subprocess_env(self.settings, credential),
            "resume": resume,
            "mcp_servers": run_servers,
            "stderr": lambda line: logger.debug("claude cli: %s", redact(line, [credential])),
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
        try:
            self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
            options = ClaudeAgentOptions(**options_kwargs)
            stream = query(prompt=content if isinstance(content, str) else _stream_prompt(content), options=options)
            api_error = ""
            # Read the stream to its end: leaving it early closes the SDK's generator from the wrong task.
            async for sdk_message in stream:
                if finished:
                    continue
                if isinstance(sdk_message, AssistantMessage) and sdk_message.error:
                    api_error = str(sdk_message.error)
                if isinstance(sdk_message, ResultMessage):
                    finished = True
                    sid = str(sdk_message.session_id or "")
                    if sid:
                        on_agent_id(sid)
                for event in map_claude_message(sdk_message, api_error):
                    yield event
            if not finished:
                yield {"type": "error", "message": "Claude stopped without an answer."}
        except Exception as exc:
            if finished:
                # The result is already in the chat. Claude Code exits non-zero after an error result.
                logger.debug("claude cli exit after result session=%s: %s", session.id, public_error(exc, credential))
                return
            logger.warning("claude turn failed session=%s: %s", session.id, public_error(exc, credential))
            yield {"type": "error", "message": public_error(exc, credential)}
