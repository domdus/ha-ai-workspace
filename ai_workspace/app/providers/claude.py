"""Claude Agent SDK provider (Claude Code CLI via claude-agent-sdk)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
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

_MISSING_KEY = (
    "No Claude credential is set. Add an OpenRouter key, Claude Plan token (CLAUDE_CODE_OAUTH_TOKEN), "
    "or Anthropic API key in the runtime environment or addon options."
)

_OPENROUTER_DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
_PLAN_API_DEFAULT_MODEL = "claude-sonnet-5-5"

# Non-admin chats: MCP only (no shell or workspace file tools).
_FILE_AND_SHELL = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "LS",
    "Task",
)
_INTERNET_TOOLS = ("WebSearch", "WebFetch")


def _runtime_credential(settings: Settings) -> str:
    return (
        (settings.openrouter_api_key or "").strip()
        or (settings.claude_oauth_token or "").strip()
        or (settings.anthropic_api_key or "").strip()
    )


def detect_auth_mode(credential: str, settings: Settings) -> str:
    """Pick how the Claude Code CLI should authenticate.

    Order: OpenRouter → Claude Plan (OAuth) → Anthropic API. Per-chat keys use the same rules.
    """
    cred = (credential or "").strip()
    base = (settings.anthropic_base_url or "").strip().lower()
    if (
        "openrouter.ai" in base
        or (settings.openrouter_api_key or "").strip()
        or cred.startswith("sk-or-")
    ):
        return "openrouter"
    if (settings.claude_oauth_token or "").strip() or cred.startswith("sk-ant-oat"):
        return "plan"
    return "api"


def claude_subprocess_env(settings: Settings, credential: str, model: str) -> dict[str, str]:
    """Env vars merged onto the Claude Code subprocess (not the whole uvicorn worker)."""
    cred = (credential or "").strip()
    config_dir = settings.data_dir / "claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    resolved_model = (model or "").strip() or (settings.claude_model or "").strip() or _default_model(settings, cred)
    env: dict[str, str] = {
        "CLAUDE_AGENT_SDK_CLIENT_APP": "ha-ai-workspace",
        "CLAUDE_CONFIG_DIR": str(config_dir),
    }
    mode = detect_auth_mode(cred or _runtime_credential(settings), settings)
    if mode == "openrouter":
        key = cred or (settings.openrouter_api_key or "").strip()
        base = (settings.anthropic_base_url or "").strip() or "https://openrouter.ai/api"
        slug = resolved_model if "/" in resolved_model else _OPENROUTER_DEFAULT_MODEL
        env.update(
            {
                "ANTHROPIC_BASE_URL": base,
                "ANTHROPIC_AUTH_TOKEN": key,
                "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": slug,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": slug,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": slug,
                "CLAUDE_CODE_SUBAGENT_MODEL": slug,
            }
        )
        if os.environ.get("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "").strip() in {"1", "true", "yes"}:
            env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"
    elif mode == "plan":
        token = cred or (settings.claude_oauth_token or "").strip()
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    else:
        key = cred or (settings.anthropic_api_key or "").strip()
        if key:
            env["ANTHROPIC_API_KEY"] = key
        base = (settings.anthropic_base_url or "").strip()
        if base and "openrouter.ai" not in base:
            env["ANTHROPIC_BASE_URL"] = base
    return env


def _default_model(settings: Settings, credential: str) -> str:
    mode = detect_auth_mode(credential or _runtime_credential(settings), settings)
    if mode == "openrouter":
        return _OPENROUTER_DEFAULT_MODEL
    return (settings.claude_model or "").strip() or _PLAN_API_DEFAULT_MODEL


def _mcp_for_sdk(servers: dict) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in (servers or {}).items():
        row = dict(cfg or {})
        kind = str(row.get("type") or "").strip().lower()
        if kind in {"streamable-http", "streamable_http"}:
            row["type"] = "http"
        elif not kind:
            row["type"] = "http"
        out[str(name)] = row
    return out


def _allowed_mcp_tools(servers: dict) -> list[str]:
    return [f"mcp__{name}__*" for name in sorted((servers or {}).keys())]


def _tool_policy(
    *,
    no_tools: bool,
    full_tools: bool,
    allow_internet: bool,
    mcp_servers: dict,
    attach_tools: bool,
) -> tuple[list[str], list[str], str | None]:
    if no_tools or not attach_tools:
        return [], list(_FILE_AND_SHELL) + list(_INTERNET_TOOLS), None
    allowed = _allowed_mcp_tools(mcp_servers) if mcp_servers else []
    disallowed: list[str] = []
    if not full_tools:
        disallowed.extend(_FILE_AND_SHELL)
    if not allow_internet:
        disallowed.extend(_INTERNET_TOOLS)
    permission = "acceptEdits" if full_tools else None
    return allowed, disallowed, permission


def map_claude_message(message: Any) -> list[dict[str, Any]]:
    try:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, UserMessage
    except ImportError:
        return []

    events: list[dict[str, Any]] = []
    if isinstance(message, AssistantMessage):
        for block in message.content or []:
            if isinstance(block, TextBlock):
                text = (block.text or "").strip()
                if text:
                    events.append({"type": "text", "delta": str(block.text)})
            elif isinstance(block, ThinkingBlock):
                events.append({"type": "status", "text": "Thinking..."})
            elif isinstance(block, ToolUseBlock):
                name = _resolved_tool_name(block.name, block.input)
                label = _tool_label(name)
                events.append(_tool_event(name, "start", f"Calling {label}...", block.id))
        return events
    if isinstance(message, UserMessage):
        blocks = message.content if isinstance(message.content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock):
                events.append(_tool_event("tool", "end", "Finished", block.tool_use_id))
        return events
    if isinstance(message, ResultMessage):
        if message.is_error or str(getattr(message, "subtype", "") or "").startswith("error_"):
            text = str(message.result or "").strip() or "Run failed."
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
        usage_event = _usage_from_result(message)
        if usage_event:
            events.append(usage_event)
        return events
    return events


def _int_usage(value: object) -> int:
    try:
        if value is None or value is False:
            return 0
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _usage_from_result(message: Any) -> dict[str, Any] | None:
    usage = getattr(message, "usage", None) or {}
    if not isinstance(usage, dict):
        usage = {}
    prompt = _int_usage(usage.get("input_tokens") or usage.get("prompt_tokens"))
    completion = _int_usage(usage.get("output_tokens") or usage.get("completion_tokens"))
    cache_read = _int_usage(
        usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens")
    )
    cache_write = _int_usage(
        usage.get("cache_creation_input_tokens") or usage.get("cache_write_tokens")
    )
    cost = getattr(message, "total_cost_usd", None)
    try:
        cost_usd = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_usd = None
    model = ""
    model_usage = getattr(message, "model_usage", None) or {}
    if isinstance(model_usage, dict) and model_usage:
        model = next(iter(model_usage.keys()), "")
        blob = model_usage.get(model)
        if blob is not None:
            prompt = prompt or _int_usage(getattr(blob, "input_tokens", None))
            completion = completion or _int_usage(getattr(blob, "output_tokens", None))
    if not (prompt or completion or cost_usd is not None):
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


class ClaudeProvider:
    def __init__(self, settings: Settings, runtime: CursorRuntime) -> None:
        self.settings = settings
        self.runtime = runtime

    @property
    def info(self) -> ProviderInfo:
        if not _runtime_credential(self.settings):
            return ProviderInfo("claude", "Claude", False, _MISSING_KEY)
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
        del effort, images  # Claude SDK turn is text-only here; images not wired yet.
        credential = (api_key or "").strip() or _runtime_credential(self.settings)
        if not credential:
            yield {"type": "error", "message": _MISSING_KEY}
            return
        try:
            exclusive = bool((mcp or {}).get("exclusive"))
            file_servers = {} if exclusive else load_mcp_servers(self.settings.mcp_config_path)
            mcp_servers = merge_mcp_servers(file_servers, servers_from_chat_mcp(mcp))
        except McpConfigError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        if no_tools:
            mcp_servers = {}
        used_model = (model or "").strip() or _default_model(self.settings, credential)
        asked = (question or "").strip()
        attach_tools = not no_tools and wants_house_tools(asked or message)
        wrapped = self.runtime.wrap_mcp(mcp_servers, session.id) if attach_tools else {}
        run_servers = _mcp_for_sdk(wrapped)
        allowed, disallowed, permission = _tool_policy(
            no_tools=no_tools,
            full_tools=full_tools,
            allow_internet=allow_internet,
            mcp_servers=run_servers,
            attach_tools=attach_tools,
        )
        resume = None if fresh else (session.agent_id or None)
        cold = fresh or not resume
        outbound = apply_standing(message, prompt, cold)
        outbound = apply_handoff(outbound, handoff, cold, question=asked or question)
        yield {"type": "status", "text": "Thinking..."}
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError:
            yield {"type": "error", "message": "Claude Agent SDK is not installed in this runtime."}
            return

        options_kwargs: dict[str, Any] = {
            "cwd": str(self.settings.workspace_dir),
            "setting_sources": [],
            "strict_mcp_config": True,
            "model": used_model,
            "env": claude_subprocess_env(self.settings, credential, used_model),
            "resume": resume,
        }
        if run_servers:
            options_kwargs["mcp_servers"] = run_servers
        if allowed:
            options_kwargs["allowed_tools"] = allowed
        if disallowed:
            options_kwargs["disallowed_tools"] = disallowed
        if permission:
            options_kwargs["permission_mode"] = permission
        options = ClaudeAgentOptions(**options_kwargs)
        try:
            from claude_agent_sdk import ResultMessage

            async for sdk_message in query(prompt=outbound, options=options):
                if isinstance(sdk_message, ResultMessage):
                    sid = str(sdk_message.session_id or "")
                    if sid:
                        on_agent_id(sid)
                for event in map_claude_message(sdk_message):
                    yield event
                if isinstance(sdk_message, ResultMessage):
                    break
        except Exception as exc:
            yield {"type": "error", "message": _public_error(exc, credential)}


def _public_error(exc: Exception, credential: str) -> str:
    return redact(str(exc), [credential])
