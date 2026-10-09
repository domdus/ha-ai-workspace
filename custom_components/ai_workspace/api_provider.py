from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Callable

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .images import anthropic_user_content, openai_user_content
from .const import (
    API_ANTHROPIC,
    API_AZURE,
    API_OLLAMA,
    API_OPENAI,
    API_SHORT_LABELS,
    DEFAULT_AZURE_API_VERSION,
    DEFAULT_SYSTEM_PROMPT,
    EFFORT_FAST,
    EFFORT_HIGH,
    EFFORT_HIGH_FAST,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    default_api_base,
    default_api_model,
    ui_link_instructions,
    with_language_rule,
)
from .coolver import CoolverClient
from .mcp_client import McpError, McpHttpClient
from .mcp_config import public_tool_names
from .mcp_resolve import async_resolve_mcp_url
from .models import ProviderInfo, Settings
from .redact import redact
from .store import Session, Store
from .titles import clean_title, title_prompt
from .tool_result import fit_tool_result

logger = logging.getLogger(__name__)

_IDENTITY = (
    "You are {label}, model {model}, in Home Assistant AI Workspace. "
    "If asked which model or provider you are, answer with that provider and that exact model id. "
    "Do not claim to be a different model."
)
_MAX_ROUNDS = 8
_DESC_MAX = 180
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


class McpBundle:
    """One call_tool for every connected MCP server."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._routes: dict[str, tuple[str, str]] = {}
        self._groups: list[tuple[str, list[str]]] = []
        self._pending: list[tuple[str, list[dict]]] = []
        self.tools: list[dict] = []

    def add(self, server: str, client: Any, tools: list[dict]) -> None:
        names = [str(tool.get("name") or "") for tool in tools if tool.get("name")]
        self._clients[server] = client
        self._groups.append((server, names))
        self._pending.append((server, tools))

    def finish(self) -> None:
        self._routes = public_tool_names(self._groups)
        merged: list[dict] = []
        for server, tools in self._pending:
            for tool in tools:
                raw = str(tool.get("name") or "")
                public = next((name for name, route in self._routes.items() if route == (server, raw)), raw)
                copied = dict(tool)
                copied["name"] = public
                if public != raw:
                    note = f"From {server}. "
                    copied["description"] = note + str(copied.get("description") or "")
                merged.append(copied)
        self.tools = merged

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        route = self._routes.get(name)
        if route is None:
            raise McpError(f"No connection has a tool named {name}.")
        server, raw = route
        return await self._clients[server].call_tool(raw, arguments or {})


def _tool_body(result: Any) -> str:
    return fit_tool_result(result)


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


def _failed_reply(row) -> bool:
    if row.role != "assistant":
        return False
    try:
        events = json.loads(row.events or "[]")
    except json.JSONDecodeError:
        return False
    if not isinstance(events, list):
        return False
    errors = [str(item.get("message") or "") for item in events if isinstance(item, dict) and item.get("type") == "error"]
    if not errors:
        return False
    content = str(row.content or "").strip()
    return not content or content in errors


def _history_messages(rows) -> list[dict[str, str]]:
    messages = []
    for row in rows:
        if row.role not in {"user", "assistant"} or _failed_reply(row):
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
        needs_key = settings.api_provider != API_OLLAMA
        if needs_key and not settings.api_key:
            reason = "Add an API key on this agent."
        elif settings.api_provider == API_AZURE and not (settings.api_base and settings.model):
            reason = "Azure needs the endpoint and the deployment name."
        elif self.settings.mcp_kind == MCP_CUSTOM and not settings.mcp_servers:
            reason = "Set an MCP URL on the AI Workspace integration."
        elif self.settings.mcp_kind == MCP_COOLVER and not settings.mcp_token:
            reason = "Set the Vibecode Agent Key on the AI Workspace integration."
        label = settings.agent_title or f"{self._label()} ({self._model()})"
        self.info = ProviderInfo(
            id=settings.agent_id or "api",
            label=label,
            available=reason is None,
            reason=reason,
        )

    def _label(self) -> str:
        return API_SHORT_LABELS.get(self.settings.api_provider, "OpenAI")

    def _http(self) -> ClientSession:
        return async_get_clientsession(self.hass)

    def _base(self) -> str:
        configured = (self.settings.api_base or "").strip().rstrip("/")
        if configured:
            return configured
        return default_api_base(self.settings.api_provider) or "https://api.openai.com/v1"

    def _chat_url(self) -> str:
        if self.settings.api_provider == API_AZURE:
            version = (self.settings.azure_api_version or DEFAULT_AZURE_API_VERSION).strip()
            return (
                f"{self._base()}/openai/deployments/{self._model()}/chat/completions"
                f"?api-version={version}"
            )
        return f"{self._base()}/chat/completions"

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.settings.api_key
        if not key:
            return headers
        if self.settings.api_provider == API_AZURE:
            headers["api-key"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _effort_body(self, payload: dict[str, Any]) -> None:
        effort = (self.settings.effort or "").strip()
        if effort not in {EFFORT_FAST, EFFORT_HIGH, EFFORT_HIGH_FAST}:
            return
        level = "low" if effort == EFFORT_FAST else "high"
        provider = self.settings.api_provider
        if provider == API_ANTHROPIC:
            payload["output_config"] = {"effort": "max" if effort == EFFORT_HIGH_FAST else level}
            return
        payload["reasoning_effort"] = level

    def _model(self) -> str:
        model = (self.settings.model or "").strip()
        if model:
            return model
        return default_api_model(self.settings.api_provider)

    def _system(self, origin: str = "", language: str = "") -> str:
        identity = _IDENTITY.format(label=self._label(), model=self._model())
        body = (self.settings.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
        text = f"{identity}\n\n{body}\n\n{ui_link_instructions(origin)}"
        if self.settings.house_map:
            from .house_map import CATALOG_INSTRUCTIONS

            text = f"{text}\n\n{CATALOG_INSTRUCTIONS}"
        return with_language_rule(text, language)

    def _public(self, exc: BaseException) -> str:
        return redact(str(exc), [self.settings.api_key, self.settings.cursor_api_key, self.settings.mcp_token])

    async def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
        access_token: str | None = None,
        frontend_origin: str | None = None,
        images: list[dict] | None = None,
        language: str = "",
    ) -> AsyncIterator[dict]:
        origin = str(frontend_origin or "").strip()
        language = str(language or "")
        pictures = list(images or [])
        on_agent_id(self.info.id)
        if not self.info.available:
            yield {"type": "error", "message": self.info.reason}
            return
        bundle = McpBundle()
        http = self._http()
        primary = next(iter(self.settings.mcp_servers.values()), {}) if self.settings.mcp_servers else {}
        configured = str(primary.get("url") or "")
        headers = dict(primary.get("headers") or {})
        token = (self.settings.mcp_token or "").strip()
        if self.settings.mcp_kind == MCP_HA:
            token = token or str(access_token or "").strip()
        if token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
        mcp_url = await async_resolve_mcp_url(self.hass, self.settings.mcp_kind, configured, token)
        extra_clients: list[tuple[str, str, dict[str, str]]] = []
        for name, cfg in (self.settings.mcp_servers or {}).items():
            if name == "mcp" or not cfg.get("url"):
                continue
            extra_clients.append((name, str(cfg.get("url") or ""), dict(cfg.get("headers") or {})))
        if not mcp_url and not extra_clients:
            yield {"type": "error", "message": "MCP URL is missing."}
            return
        yield {"type": "status", "text": "Working"}
        try:
            if mcp_url:
                if self.settings.mcp_kind == MCP_COOLVER:
                    primary_client: McpHttpClient | CoolverClient = CoolverClient(http, mcp_url, headers)
                else:
                    primary_client = McpHttpClient(http, mcp_url, headers)
                await primary_client.initialize()
                bundle.add("home-assistant", primary_client, await primary_client.list_tools())
            for name, url, extra_headers in extra_clients:
                if name in {"catalog", "house-map"}:
                    continue
                client = McpHttpClient(http, url, extra_headers)
                await client.initialize()
                bundle.add(name, client, await client.list_tools())
            if self.settings.house_map:
                from .house_map import HouseMapClient

                local = HouseMapClient(self.hass, self.store)
                await local.initialize()
                bundle.add("catalog", local, await local.list_tools())
            bundle.finish()
        except McpError as exc:
            yield {"type": "error", "message": self._public(exc)}
            return
        logger.info(
            "api chat provider=%s model=%s mcp=%s",
            self.settings.api_provider,
            self._model(),
            ", ".join(bundle._clients) or "none",
        )
        mcp = bundle
        mcp_tools = bundle.tools
        history = await self.hass.async_add_executor_job(self.store.list_messages, session.id)
        try:
            if self.settings.api_provider == API_ANTHROPIC:
                async for event in self._anthropic(http, history, message, mcp, mcp_tools, origin, pictures, language):
                    yield event
            else:
                async for event in self._openai(http, history, message, mcp, mcp_tools, origin, pictures, language):
                    yield event
        except (McpError, ClientError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            logger.exception("api provider failed")
            yield {"type": "error", "message": self._public(exc)}

    async def suggest_title(self, user: str, assistant: str = "") -> str | None:
        if not self.info.available:
            return None
        prompt = title_prompt(user, assistant)
        http = self._http()
        try:
            if self.settings.api_provider == API_ANTHROPIC:
                data = await self._post(
                    http,
                    f"{self._base()}/messages",
                    {
                        "x-api-key": self.settings.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    {
                        "model": self._model(),
                        "max_tokens": 32,
                        "system": "You write short chat titles. Reply with the title only.",
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=8,
                    attempts=1,
                )
                blocks = data.get("content") or []
                raw = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
            else:
                title_body = {
                    "model": self._model(),
                    "max_tokens": 32,
                    "messages": [
                        {"role": "system", "content": "You write short chat titles. Reply with the title only."},
                        {"role": "user", "content": prompt},
                    ],
                }
                data = await self._post(
                    http,
                    self._chat_url(),
                    self._auth_headers(),
                    title_body,
                    timeout=8,
                    attempts=1,
                )
                raw = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        except Exception:
            logger.debug("title generation failed", exc_info=True)
            return None
        return clean_title(raw) or None

    async def _openai(
        self,
        http: ClientSession,
        history,
        message: str,
        mcp: McpBundle,
        mcp_tools: list[dict],
        origin: str = "",
        images: list[dict] | None = None,
        language: str = "",
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system(origin, language)}]
        messages.extend(_history_messages(history))
        messages.append({"role": "user", "content": openai_user_content(message, images or [])})
        tools = _openai_tools(mcp_tools)
        url = self._chat_url()
        headers = self._auth_headers()
        for _ in range(_MAX_ROUNDS):
            payload: dict[str, Any] = {"model": self._model(), "messages": messages}
            self._effort_body(payload)
            if tools:
                payload["tools"] = tools
                if self.settings.api_provider == API_OPENAI:
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
        mcp: McpBundle,
        mcp_tools: list[dict],
        origin: str = "",
        images: list[dict] | None = None,
        language: str = "",
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = list(_history_messages(history))
        messages.append({"role": "user", "content": anthropic_user_content(message, images or [])})
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
                "system": self._system(origin, language),
                "messages": messages,
            }
            self._effort_body(payload)
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

    async def _post(
        self,
        http: ClientSession,
        url: str,
        headers: dict,
        payload: dict,
        timeout: float = 120,
        attempts: int = 4,
    ) -> dict:
        last = ""
        retries = max(1, attempts)
        for attempt in range(retries):
            resp = await http.post(url, json=payload, headers=headers, timeout=ClientTimeout(total=timeout))
            text = await resp.text()
            last = text
            if resp.status == 429:
                wait = _retry_wait(resp, text)
                if wait is not None and attempt < retries - 1:
                    logger.warning("api rate limited, retry in %.2fs", wait)
                    await asyncio.sleep(wait)
                    continue
            if resp.status >= 400:
                raise RuntimeError(_friendly_api_error(resp.status, text))
            return json.loads(text)
        raise RuntimeError(_friendly_api_error(429, last))
