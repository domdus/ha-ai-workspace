from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Callable

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_ANTHROPIC,
    API_COMPATIBLE,
    API_OPENAI,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_API_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
)
from .coolver import CoolverClient
from .mcp_client import McpError, McpHttpClient
from .mcp_resolve import async_resolve_mcp_url
from .models import ProviderInfo, Settings
from .redact import redact
from .store import Session, Store

logger = logging.getLogger(__name__)

_IDENTITY = (
    "You are {label}, model {model}, in Home Assistant AI Workspace. "
    "If asked which model or provider you are, answer with that provider and that exact model id. "
    "Do not claim to be a different model."
)
_MAX_ROUNDS = 8
_DESC_MAX = 180
_RESULT_MAX = 2500
_HISTORY_MAX = 12
_PROPS_MAX = 16
_WAIT = re.compile(r"try again in ([\d.]+)\s*(ms|s)", re.I)


def _friendly_api_error(status: int, text: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    err = data.get("error") if isinstance(data, dict) else None
    message = ""
    code = ""
    if isinstance(err, dict):
        message = str(err.get("message") or "")
        code = str(err.get("code") or err.get("type") or "")
    elif isinstance(err, str):
        message = err
    low = f"{code} {message}".lower()
    if "rate_limit" in low or "rate limit" in low:
        return (
            "The model provider hit a short rate limit. Wait a second and send again. "
            "New OpenAI accounts are often capped at 30,000 tokens per minute; "
            "Home Assistant MCP tool lists use a lot of that budget."
        )
    if message:
        return message.split("Visit https://")[0].strip()
    return (text or f"HTTP {status}")[:400]


def _retry_wait(resp, text: str) -> float | None:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), 5.0)
        except ValueError:
            pass
    match = _WAIT.search(text or "")
    if match:
        value = float(match.group(1))
        if match.group(2).lower() == "ms":
            value /= 1000.0
        return min(value + 0.05, 5.0)
    if resp.status == 429:
        return 0.5
    return None



def _clip(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1].rstrip() + "…"


def _slim_schema(schema: Any, depth: int = 0) -> dict[str, Any]:
    if not isinstance(schema, dict) or depth > 3:
        return {"type": "object", "properties": {}}
    out: dict[str, Any] = {}
    if schema.get("type"):
        out["type"] = schema["type"]
    if schema.get("description"):
        out["description"] = _clip(str(schema["description"]), _DESC_MAX)
    if isinstance(schema.get("enum"), list):
        out["enum"] = schema["enum"][:12]
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        slim: dict[str, Any] = {}
        for index, (key, value) in enumerate(props.items()):
            if index >= _PROPS_MAX:
                break
            slim[str(key)] = _slim_schema(value, depth + 1) if isinstance(value, dict) else {"type": "string"}
        out["properties"] = slim
    required = schema.get("required")
    if isinstance(required, list) and out.get("properties"):
        allowed = out["properties"]
        kept = [item for item in required if item in allowed]
        if kept:
            out["required"] = kept
    items = schema.get("items")
    if isinstance(items, dict):
        out["items"] = _slim_schema(items, depth + 1)
    return out or {"type": "object", "properties": {}}


def _slim_mcp_tools(mcp_tools: list[dict]) -> list[dict]:
    out = []
    for tool in mcp_tools:
        name = str(tool.get("name") or "")
        if not name:
            continue
        schema = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object", "properties": {}}
        out.append(
            {
                "name": name,
                "description": _clip(str(tool.get("description") or name), _DESC_MAX),
                "inputSchema": _slim_schema(schema),
            }
        )
    return out


def _tool_body(result: Any) -> str:
    if isinstance(result, str):
        raw = result
    else:
        raw = json.dumps(result, ensure_ascii=False)
    return _clip(raw, _RESULT_MAX)


def _tool_label(name: str) -> str:
    raw = str(name or "tool").strip() or "tool"
    if raw.lower() == "mcp":
        return "MCP"
    return raw


def _openai_tools(mcp_tools: list[dict]) -> list[dict]:
    out = []
    for tool in _slim_mcp_tools(mcp_tools):
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                },
            }
        )
    return out


def _anthropic_tools(mcp_tools: list[dict]) -> list[dict]:
    out = []
    for tool in _slim_mcp_tools(mcp_tools):
        out.append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["inputSchema"],
            }
        )
    return out


def _history_messages(rows) -> list[dict[str, str]]:
    messages = []
    for row in rows:
        if row.role not in {"user", "assistant"}:
            continue
        content = _clip(row.content or "", 2000)
        if not content:
            continue
        messages.append({"role": row.role, "content": content})
    if messages and messages[-1]["role"] == "user":
        messages = messages[:-1]
    if len(messages) > _HISTORY_MAX:
        messages = messages[-_HISTORY_MAX:]
    return messages


class ApiProvider:
    def __init__(self, hass: HomeAssistant, settings: Settings, store: Store) -> None:
        self.hass = hass
        self.settings = settings
        self.store = store
        reason = None
        if not settings.api_key:
            reason = "Set an API key on the AI Workspace integration (OpenAI, Claude, or compatible)."
        elif self.settings.mcp_kind == MCP_CUSTOM and not settings.mcp_servers:
            reason = "Set an MCP URL on the AI Workspace integration."
        elif self.settings.mcp_kind == MCP_COOLVER and not settings.mcp_token:
            reason = "Set the Vibecode Agent Key on the AI Workspace integration."
        self.info = ProviderInfo(
            id="api",
            label=f"{self._label()} ({self._model()})",
            available=reason is None,
            reason=reason,
        )

    def _label(self) -> str:
        kind = self.settings.api_provider
        if kind == API_ANTHROPIC:
            return "Claude"
        if kind == API_COMPATIBLE:
            return "OpenAI-compatible"
        return "OpenAI"

    def _http(self) -> ClientSession:
        return async_get_clientsession(self.hass)

    def _base(self) -> str:
        configured = (self.settings.api_base or "").strip().rstrip("/")
        if configured:
            return configured
        if self.settings.api_provider == API_ANTHROPIC:
            return "https://api.anthropic.com/v1"
        return "https://api.openai.com/v1"

    def _model(self) -> str:
        model = (self.settings.model or "").strip()
        if model:
            return model
        if self.settings.api_provider == API_ANTHROPIC:
            return DEFAULT_ANTHROPIC_MODEL
        return DEFAULT_API_MODEL

    def _system(self) -> str:
        identity = _IDENTITY.format(label=self._label(), model=self._model())
        body = (self.settings.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
        return f"{identity}\n\n{body}"

    def _public(self, exc: BaseException) -> str:
        return redact(str(exc), [self.settings.api_key, self.settings.cursor_api_key, self.settings.mcp_token])

    async def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
        access_token: str | None = None,
    ) -> AsyncIterator[dict]:
        on_agent_id("api")
        if not self.info.available:
            yield {"type": "error", "message": self.info.reason}
            return
        server = next(iter(self.settings.mcp_servers.values()), {}) if self.settings.mcp_servers else {}
        configured = str(server.get("url") or "")
        headers = dict(server.get("headers") or {})
        token = (self.settings.mcp_token or "").strip()
        if self.settings.mcp_kind == MCP_HA:
            token = token or str(access_token or "").strip()
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        mcp_url = await async_resolve_mcp_url(self.hass, self.settings.mcp_kind, configured, token)
        if not mcp_url:
            yield {"type": "error", "message": "MCP URL is missing."}
            return
        http = self._http()
        if self.settings.mcp_kind == MCP_COOLVER:
            mcp: McpHttpClient | CoolverClient = CoolverClient(http, mcp_url, headers)
        else:
            mcp = McpHttpClient(http, mcp_url, headers)
        logger.info("api chat provider=%s model=%s mcp=%s", self.settings.api_provider, self._model(), mcp_url)
        yield {"type": "status", "text": "Working"}
        try:
            await mcp.initialize()
            mcp_tools = await mcp.list_tools()
        except McpError as exc:
            yield {"type": "error", "message": self._public(exc)}
            return
        history = await self.hass.async_add_executor_job(self.store.list_messages, session.id)
        try:
            if self.settings.api_provider == API_ANTHROPIC:
                async for event in self._anthropic(http, history, message, mcp, mcp_tools):
                    yield event
            else:
                async for event in self._openai(http, history, message, mcp, mcp_tools):
                    yield event
        except (McpError, ClientError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            logger.exception("api provider failed")
            yield {"type": "error", "message": self._public(exc)}

    async def _openai(
        self,
        http: ClientSession,
        history,
        message: str,
        mcp: McpHttpClient,
        mcp_tools: list[dict],
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system()}]
        messages.extend(_history_messages(history))
        messages.append({"role": "user", "content": message})
        tools = _openai_tools(mcp_tools)
        url = f"{self._base()}/chat/completions"
        headers = {"Authorization": f"Bearer {self.settings.api_key}", "Content-Type": "application/json"}
        for _ in range(_MAX_ROUNDS):
            payload: dict[str, Any] = {"model": self._model(), "messages": messages}
            if tools:
                payload["tools"] = tools
                payload["parallel_tool_calls"] = False
            data = await self._post(http, url, headers, payload)
            choice = ((data.get("choices") or [{}])[0].get("message")) or {}
            tool_calls = choice.get("tool_calls") or []
            content = str(choice.get("content") or "")
            if tool_calls:
                messages.append(choice)
                for call in tool_calls:
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "tool")
                    label = _tool_label(name)
                    yield {"type": "tool", "name": name, "phase": "start", "text": f"Calling {label}..."}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = await mcp.call_tool(name, args if isinstance(args, dict) else {})
                        body = _tool_body(result)
                    except McpError as exc:
                        body = self._public(exc)
                    yield {"type": "tool", "name": name, "phase": "end", "text": f"Finished {label}"}
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": body})
                continue
            if content:
                yield {"type": "text", "delta": content}
            yield {"type": "result", "text": content, "status": "finished"}
            return
        yield {"type": "error", "message": "The model kept calling tools without finishing."}

    async def _anthropic(
        self,
        http: ClientSession,
        history,
        message: str,
        mcp: McpHttpClient,
        mcp_tools: list[dict],
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = list(_history_messages(history))
        messages.append({"role": "user", "content": message})
        tools = _anthropic_tools(mcp_tools)
        url = f"{self._base()}/messages"
        headers = {
            "x-api-key": self.settings.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        for _ in range(_MAX_ROUNDS):
            payload: dict[str, Any] = {
                "model": self._model(),
                "max_tokens": 4096,
                "system": self._system(),
                "messages": messages,
            }
            if tools:
                payload["tools"] = tools
            data = await self._post(http, url, headers, payload)
            blocks = data.get("content") or []
            tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
            texts = [str(b.get("text") or "") for b in blocks if b.get("type") == "text"]
            if tool_uses:
                messages.append({"role": "assistant", "content": blocks})
                results = []
                for block in tool_uses:
                    name = str(block.get("name") or "tool")
                    label = _tool_label(name)
                    yield {"type": "tool", "name": name, "phase": "start", "text": f"Calling {label}..."}
                    args = block.get("input") if isinstance(block.get("input"), dict) else {}
                    try:
                        result = await mcp.call_tool(name, args)
                        body = _tool_body(result)
                    except McpError as exc:
                        body = self._public(exc)
                    yield {"type": "tool", "name": name, "phase": "end", "text": f"Finished {label}"}
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.get("id"),
                            "content": body,
                        }
                    )
                messages.append({"role": "user", "content": results})
                continue
            content = "".join(texts)
            if content:
                yield {"type": "text", "delta": content}
            yield {"type": "result", "text": content, "status": "finished"}
            return
        yield {"type": "error", "message": "The model kept calling tools without finishing."}

    async def _post(self, http: ClientSession, url: str, headers: dict, payload: dict) -> dict:
        last = ""
        for attempt in range(4):
            resp = await http.post(url, json=payload, headers=headers, timeout=ClientTimeout(total=120))
            text = await resp.text()
            last = text
            if resp.status == 429:
                wait = _retry_wait(resp, text)
                if wait is not None and attempt < 3:
                    logger.warning("api rate limited, retry in %.2fs", wait)
                    await asyncio.sleep(wait)
                    continue
            if resp.status >= 400:
                raise RuntimeError(_friendly_api_error(resp.status, text))
            return json.loads(text)
        raise RuntimeError(_friendly_api_error(429, last))
