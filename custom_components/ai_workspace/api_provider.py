from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from typing import Any, AsyncIterator, Callable

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .images import anthropic_user_content, openai_user_content
from .const import (
    API_ANTHROPIC,
    API_AZURE,
    API_COMPATIBLE,
    API_GEMINI,
    API_OLLAMA,
    API_OPENAI,
    API_OPENROUTER,
    API_SHORT_LABELS,
    API_XAI,
    DEFAULT_AZURE_API_VERSION,
    BPS_KEY_INSTRUCTIONS,
    DEFAULT_SYSTEM_PROMPT,
    DOMAIN,
    LOW_TOKEN_PROMPT,
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
from .mcp_config import (
    OPENAI_TOOL_NAME_MAX,
    is_local_hass_mcp_url,
    openai_tool_name_errors,
    public_tool_names,
    with_mcp_auth,
)
from .mcp_resolve import ha_hosts, hass_mcp_server_url
from .models import ProviderInfo, Settings
from .redact import redact
from .small_talk import wants_house_tools
from .store import Session, Store
from .titles import clean_title, title_prompt
from .tool_result import fit_tool_result

logger = logging.getLogger(__name__)

_IDENTITY = (
    "You are {label}, model {model}, in Home Assistant AI Workspace. "
    "If asked which model or provider you are, answer with that provider and that exact model id. "
    "Do not claim to be a different model."
)
_MAX_ROUNDS = 15
_DESC_MAX = 180
# HA-MCP hides the acknowledgment key inside ha_get_skill_guide and puts the
# "call that tool" sentence at the end of a long write-tool description. A
# 180-character trim drops it, and the model then asks the user for BestPracticeKey.
_BPS_PARAM = (
    "Call ha_get_skill_guide, copy the acknowledgment key from the top of the result, "
    "and pass it here. Do not ask the user."
)
_BPS_NOTE = (
    " Call ha_get_skill_guide and pass its acknowledgment key as BestPracticeKey. Do not ask the user."
)
_HISTORY_MAX = 12
_LOW_TOKEN_CHARS = 1200
_LOW_TOKEN_REPLY = 256
_PROPS_MAX = 16
_WAIT = re.compile(r"try again in ([\d.]+)\s*(ms|s)", re.I)
_ANTHROPIC_VERSION = "2023-06-01"
_REASONING_EFFORT = {API_OPENAI, API_AZURE, API_GEMINI, API_XAI}
_EFFORT_KEYS = ("reasoning_effort", "reasoning", "output_config")
_MCP_TTL = 600.0
_MCP_CACHE_MAX = 32
_MCP_CACHE = f"{DOMAIN}_mcp_cache"
_LOCAL_TOOLS = {"catalog", "house-map"}
_ERRORS = (McpError, ClientError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError)


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _StreamUnsupported(Exception):
    pass


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
        kept = 0
        for key, value in props.items():
            name = str(key)
            if name == "BestPracticeKey":
                slim[name] = {"type": "string", "description": _BPS_PARAM}
                continue
            if kept >= _PROPS_MAX:
                continue
            kept += 1
            slim[name] = _slim_schema(value, depth + 1) if isinstance(value, dict) else {"type": "string"}
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


def _clip_bps_tool(text: str) -> str:
    """Keep the skill-key instruction inside the description budget."""
    note = _BPS_NOTE
    room = _DESC_MAX - len(note)
    raw = str(text or "").strip()
    if len(raw) <= room:
        return raw + note
    return raw[: room - 1].rstrip() + "…" + note


def _slim_mcp_tools(mcp_tools: list[dict]) -> list[dict]:
    out = []
    for tool in mcp_tools:
        name = str(tool.get("name") or "")
        if not name:
            continue
        schema = tool.get("inputSchema") or tool.get("input_schema") or {"type": "object", "properties": {}}
        slim = _slim_schema(schema)
        description = str(tool.get("description") or name)
        props = slim.get("properties") if isinstance(slim, dict) else None
        if isinstance(props, dict) and "BestPracticeKey" in props:
            description = _clip_bps_tool(description)
        else:
            description = _clip(description, _DESC_MAX)
        out.append(
            {
                "name": name,
                "description": description,
                "inputSchema": slim,
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
        lookup = {route: name for name, route in self._routes.items()}
        merged: list[dict] = []
        truncated = 0
        for server, tools in self._pending:
            for tool in tools:
                raw = str(tool.get("name") or "")
                public = lookup.get((server, raw), raw)
                copied = dict(tool)
                copied["name"] = public
                if public != raw:
                    note = f"From {server}. "
                    copied["description"] = note + str(copied.get("description") or "")
                if len(raw) > OPENAI_TOOL_NAME_MAX:
                    truncated += 1
                merged.append(copied)
        self.tools = merged
        if truncated:
            logger.info("MCP tools truncated to the OpenAI %s-character name limit: %s", OPENAI_TOOL_NAME_MAX, truncated)

    def original_name(self, name: str) -> str:
        route = self._routes.get(name)
        return route[1] if route else name

    @property
    def names(self) -> list[str]:
        return list(self._clients)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        route = self._routes.get(name)
        if route is None:
            raise McpError(f"No connection has a tool named {name}.")
        server, raw = route
        return await self._clients[server].call_tool(raw, arguments or {})


class McpServer:
    """One open MCP connection, shared by chats and reopened once when its session expires."""

    def __init__(self, http: ClientSession, kind: str, url: str, headers: dict[str, str]) -> None:
        self._http = http
        self._kind = kind
        self._url = url
        self._headers = headers
        self._client: Any = None
        self.tools: list[dict] = []
        self.expires = 0.0

    async def open(self) -> None:
        if self._kind == MCP_COOLVER:
            client: Any = CoolverClient(self._http, self._url, self._headers)
        else:
            client = McpHttpClient(self._http, self._url, self._headers)
        await client.initialize()
        self.tools = await client.list_tools()
        self._client = client
        self.expires = time.monotonic() + _MCP_TTL

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        try:
            return await self._client.call_tool(name, arguments or {})
        except McpError as exc:
            # Streamable HTTP answers 404 (or 400) once the server forgot our session.
            if exc.status not in {400, 404}:
                raise
        await self.open()
        return await self._client.call_tool(name, arguments or {})


async def async_mcp_server(
    hass: HomeAssistant, http: ClientSession, kind: str, url: str, headers: dict[str, str]
) -> McpServer:
    cache: OrderedDict = hass.data.setdefault(_MCP_CACHE, OrderedDict())
    key = (kind, url.rstrip("/"), tuple(sorted(headers.items())))
    found = cache.get(key)
    if found is not None and found.expires > time.monotonic():
        cache.move_to_end(key)
        return found
    server = McpServer(http, kind, url, headers)
    await server.open()
    cache[key] = server
    cache.move_to_end(key)
    while len(cache) > _MCP_CACHE_MAX:
        cache.popitem(last=False)
    return server


async def async_check_api_key(
    hass: HomeAssistant,
    provider: str,
    api_key: str,
    api_base: str = "",
    azure_api_version: str = "",
) -> str | None:
    """None when the provider accepts the key, else a form error key."""
    base = (str(api_base or "").strip() or default_api_base(provider)).rstrip("/")
    if not base:
        return None
    key = str(api_key or "").strip()
    headers: dict[str, str] = {}
    url = f"{base}/models"
    if provider == API_ANTHROPIC:
        headers = {"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION}
    elif provider == API_AZURE:
        version = str(azure_api_version or DEFAULT_AZURE_API_VERSION).strip()
        url = f"{base}/openai/models?api-version={version}"
        headers = {"api-key": key}
    elif provider == API_OPENROUTER:
        url = f"{base}/key"
        headers = {"Authorization": f"Bearer {key}"}
    elif key:
        headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = await async_get_clientsession(hass).get(url, headers=headers, timeout=ClientTimeout(total=10))
        status = resp.status
        resp.release()
    except (ClientError, TimeoutError, OSError):
        return "cannot_connect"
    if status in {401, 403}:
        return "invalid_auth"
    return None


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
    bad = openai_tool_name_errors([str((item.get("function") or {}).get("name") or "") for item in out])
    if bad:
        logger.error(
            "OpenAI tool names invalid (max %s characters, [A-Za-z0-9_-]): %s",
            OPENAI_TOOL_NAME_MAX,
            ", ".join(bad),
        )
        raise McpError(
            "An MCP tool name is longer than OpenAI allows (64 characters). "
            "Disable one MCP connection or shorten its title."
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


async def _sse(resp: ClientResponse) -> AsyncIterator[tuple[str, str]]:
    """(event, data) pairs from a server-sent event stream."""
    event = ""
    data: list[str] = []
    buffer = b""

    def line_of(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace").rstrip("\r")

    async for chunk in resp.content.iter_any():
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            line = line_of(raw)
            if not line:
                if data:
                    yield event, "\n".join(data)
                event, data = "", []
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
    tail = line_of(buffer)
    if tail.startswith("data:"):
        data.append(tail[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def _clean_blocks(blocks: list[dict]) -> list[dict]:
    """Anthropic rejects empty text blocks when they are sent back."""
    return [block for block in blocks if block.get("type") != "text" or str(block.get("text") or "")]


class ApiProvider:
    def __init__(self, hass: HomeAssistant, settings: Settings, store: Store) -> None:
        self.hass = hass
        self.settings = settings
        self.store = store
        self._stream = True
        self._effort = True
        self._force = True
        reason = None
        needs_key = settings.api_provider not in {API_OLLAMA, API_COMPATIBLE}
        if needs_key and not settings.api_key:
            reason = "Add an API key on this agent."
        elif settings.api_provider == API_AZURE and not (settings.api_base and settings.model):
            reason = "Azure needs the endpoint and the deployment name."
        elif self.settings.mcp_kind == MCP_CUSTOM and not settings.mcp_servers:
            reason = "Add an MCP connection on the AI Workspace integration."
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

    def _anthropic_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.settings.api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _effort_body(self, payload: dict[str, Any]) -> None:
        effort = (self.settings.effort or "").strip()
        if not self._effort or effort not in {EFFORT_FAST, EFFORT_HIGH, EFFORT_HIGH_FAST}:
            return
        level = "low" if effort == EFFORT_FAST else "high"
        provider = self.settings.api_provider
        if provider == API_ANTHROPIC:
            payload["output_config"] = {"effort": level}
        elif provider == API_OPENROUTER:
            payload["reasoning"] = {"effort": level}
        elif provider in _REASONING_EFFORT:
            payload["reasoning_effort"] = level

    def _model(self) -> str:
        model = (self.settings.model or "").strip()
        if model:
            return model
        return default_api_model(self.settings.api_provider)

    def _system(self, origin: str = "", language: str = "", admin: bool = True) -> str:
        if self.settings.low_token:
            return with_language_rule(LOW_TOKEN_PROMPT, language)
        identity = _IDENTITY.format(label=self._label(), model=self._model())
        body = (self.settings.system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
        text = f"{identity}\n\n{body}\n\n{ui_link_instructions(origin)}\n\n{BPS_KEY_INSTRUCTIONS}"
        if self.settings.house_map and admin:
            from .house_map import CATALOG_INSTRUCTIONS

            text = f"{text}\n\n{CATALOG_INSTRUCTIONS}"
        return with_language_rule(text, language)

    def _public(self, exc: BaseException) -> str:
        return redact(str(exc), [self.settings.api_key, self.settings.cursor_api_key, self.settings.mcp_token])

    def _servers(self, access_token: str, admin: bool) -> dict[str, dict[str, Any]]:
        if admin:
            servers = dict(self.settings.mcp_servers)
        elif self.hass is not None and "mcp_server" in self.hass.config.components:
            servers = {"mcp": {"type": "http", "url": hass_mcp_server_url(self.hass)}}
        else:
            servers = {}
        signed = with_mcp_auth(servers, access_token=access_token, ha_hosts=ha_hosts(self.hass))
        return {name: cfg for name, cfg in signed.items() if not self._skip_unloaded_hass_mcp(name, cfg)}

    def _skip_unloaded_hass_mcp(self, name: str, cfg: dict[str, Any]) -> bool:
        """Built-in /api/mcp is gone when the mcp_server integration is not loaded."""
        if self.hass is None:
            return False
        url = str((cfg or {}).get("url") or "")
        if not is_local_hass_mcp_url(url, ha_hosts(self.hass)):
            return False
        if "mcp_server" in self.hass.config.components:
            return False
        logger.info("MCP connection %s skipped: Home Assistant MCP Server is not loaded", name)
        return True

    def _server_kind(self, name: str, admin: bool) -> str:
        if name == "mcp":
            return str(self.settings.mcp_kind or "") if admin else MCP_HA
        for row in self.settings.mcp_rows:
            if row.get("name") == name and not row.get("primary"):
                return str(row.get("kind") or "")
        return MCP_CUSTOM

    async def _open_tools(self, http: ClientSession, access_token: str, admin: bool) -> tuple[McpBundle, list[str], str]:
        bundle = McpBundle()
        skipped: list[str] = []
        first_error = ""
        for name, cfg in self._servers(access_token, admin).items():
            url = str(cfg.get("url") or "")
            if name in _LOCAL_TOOLS or not url:
                continue
            label = "home-assistant" if name == "mcp" else name
            try:
                server = await async_mcp_server(
                    self.hass, http, self._server_kind(name, admin), url, dict(cfg.get("headers") or {})
                )
            except _ERRORS as exc:
                logger.warning("MCP connection %s skipped: %s", label, self._public(exc))
                skipped.append(label)
                first_error = first_error or self._public(exc)
                continue
            bundle.add(label, server, server.tools)
        if admin and self.settings.house_map:
            from .house_map import HouseMapClient

            local = HouseMapClient(self.hass, self.store)
            bundle.add("catalog", local, await local.list_tools())
        bundle.finish()
        return bundle, skipped, first_error

    async def _invoke_tool(self, mcp, name: str, args: Any, on_tool: Callable | None):
        payload = args if isinstance(args, dict) else {}
        if on_tool is None:
            return await mcp.call_tool(name, payload)
        original = mcp.original_name(name)

        async def call(_tool_name: str, tool_args: dict) -> Any:
            return await mcp.call_tool(name, tool_args)

        return await on_tool(original, payload, call)

    async def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
        access_token: str | None = None,
        frontend_origin: str | None = None,
        images: list[dict] | None = None,
        language: str = "",
        tools: bool | None = None,
        admin: bool = True,
        force_tools: bool = False,
        on_tool: Callable | None = None,
    ) -> AsyncIterator[dict]:
        """force_tools makes the first round call a tool, so house answers come from live data."""
        origin = str(frontend_origin or "").strip()
        language = str(language or "")
        pictures = list(images or [])
        on_agent_id(self.info.id)
        if not self.info.available:
            yield {"type": "error", "message": self.info.reason}
            return
        http = self._http()
        use_tools = (wants_house_tools(message) if tools is None else bool(tools)) or bool(pictures)
        history = []
        bundle = McpBundle()
        if self.settings.low_token:
            message = _clip(message, _LOW_TOKEN_CHARS)
            pictures = []
        else:
            history = await self.hass.async_add_executor_job(self.store.list_messages, session.id)
        yield {"type": "status", "text": "Working"}
        if use_tools and not self.settings.low_token:
            bundle, skipped, first_error = await self._open_tools(http, str(access_token or ""), admin)
            if skipped and not bundle.names:
                yield {"type": "error", "message": first_error}
                return
            if skipped:
                yield {"type": "status", "text": f"Not reachable, continuing without: {', '.join(skipped)}"}
        logger.info(
            "api chat provider=%s model=%s mcp=%s tools=%s low_token=%s",
            self.settings.api_provider,
            self._model(),
            ", ".join(bundle.names) or "none",
            len(bundle.tools),
            int(self.settings.low_token),
        )
        if bundle.tools:
            logger.debug("MCP OpenAI tool names: %s", ", ".join(tool["name"] for tool in bundle.tools))
        loop = self._anthropic if self.settings.api_provider == API_ANTHROPIC else self._openai
        force = bool(force_tools) and self.settings.check_house and not pictures and not self.settings.low_token
        try:
            async for event in loop(
                http, history, message, bundle, origin, pictures, language, admin, force, on_tool
            ):
                yield event
        except _ERRORS as exc:
            logger.warning("api provider failed: %s", self._public(exc))
            yield {"type": "error", "message": self._public(exc)}

    async def suggest_title(self, user: str, assistant: str = "") -> str | None:
        if not self.info.available or self.settings.low_token:
            return None
        prompt = title_prompt(user, assistant)
        system = "You write short chat titles. Reply with the title only."
        http = self._http()
        try:
            if self.settings.api_provider == API_ANTHROPIC:
                data = await self._post(
                    http,
                    f"{self._base()}/messages",
                    self._anthropic_headers(),
                    {
                        "model": self._model(),
                        "max_tokens": 32,
                        "system": system,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=8,
                    attempts=1,
                )
                blocks = data.get("content") or []
                raw = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
            else:
                data = await self._post(
                    http,
                    self._chat_url(),
                    self._auth_headers(),
                    {
                        "model": self._model(),
                        "max_tokens": 32,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    },
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
        origin: str,
        images: list[dict],
        language: str,
        admin: bool,
        force: bool = False,
        on_tool: Callable | None = None,
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system(origin, language, admin)}]
        messages.extend(_history_messages(history))
        messages.append({"role": "user", "content": openai_user_content(message, images)})
        tools = _openai_tools(mcp.tools)
        url = self._chat_url()
        headers = self._auth_headers()
        said: list[str] = []
        for round_no in range(_MAX_ROUNDS + 1):
            last = round_no == _MAX_ROUNDS
            payload: dict[str, Any] = {"model": self._model(), "messages": messages}
            if self.settings.low_token:
                payload["max_tokens"] = _LOW_TOKEN_REPLY
            else:
                self._effort_body(payload)
            if tools:
                payload["tools"] = tools
                if last:
                    payload["tool_choice"] = "none"
                else:
                    if round_no == 0 and force and self._force:
                        payload["tool_choice"] = "required"
                    if self.settings.api_provider == API_OPENAI:
                        payload["parallel_tool_calls"] = False
            reply: dict[str, Any] = {}
            gap = bool(said)
            async for kind, value in self._openai_round(http, url, headers, payload):
                if kind == "message":
                    reply = value
                    continue
                if gap:
                    said.append("\n\n")
                    yield {"type": "text", "delta": "\n\n"}
                    gap = False
                said.append(value)
                yield {"type": "text", "delta": value}
            calls = reply.get("tool_calls") or []
            if calls and not last:
                messages.append({"role": "assistant", "content": reply.get("content") or None, "tool_calls": calls})
                for call in calls:
                    fn = call.get("function") or {}
                    name = str(fn.get("name") or "tool")
                    label = _tool_label(mcp.original_name(name))
                    yield {"type": "tool", "name": name, "phase": "start", "text": f"Calling {label}..."}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        body = _tool_body(await self._invoke_tool(mcp, name, args, on_tool))
                    except _ERRORS as exc:
                        body = self._public(exc)
                    yield {"type": "tool", "name": name, "phase": "end", "text": f"Finished {label}"}
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": body})
                continue
            break
        text = "".join(said).strip()
        if not text and last:
            yield {"type": "error", "message": "The model kept calling tools without finishing."}
            return
        yield {"type": "result", "text": text, "status": "finished"}

    async def _openai_round(
        self, http: ClientSession, url: str, headers: dict, payload: dict
    ) -> AsyncIterator[tuple[str, Any]]:
        if self._stream:
            try:
                async for item in self._openai_stream(http, url, headers, payload):
                    yield item
                return
            except _StreamUnsupported:
                logger.info("%s does not stream; using plain replies", self._label())
                self._stream = False
        data = await self._post(http, url, headers, payload)
        reply = ((data.get("choices") or [{}])[0].get("message")) or {}
        content = str(reply.get("content") or "")
        if content:
            yield "text", content
        yield "message", reply

    async def _openai_stream(
        self, http: ClientSession, url: str, headers: dict, payload: dict
    ) -> AsyncIterator[tuple[str, Any]]:
        body = {**payload, "stream": True}
        resp = await self._open(http, url, headers, body, stream=True)
        parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        try:
            async for _event, raw in _sse(resp):
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    raise ApiError(resp.status, _friendly_api_error(resp.status, raw))
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        parts.append(text)
                        yield "text", text
                    for position, call in enumerate(delta.get("tool_calls") or []):
                        index = call.get("index", position)
                        slot = calls.setdefault(
                            index,
                            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                        )
                        if call.get("id"):
                            slot["id"] = call["id"]
                        fn = call.get("function") or {}
                        if fn.get("name") and not slot["function"]["name"]:
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += str(fn["arguments"])
        finally:
            resp.release()
        reply: dict[str, Any] = {"role": "assistant", "content": "".join(parts) or None}
        if calls:
            ordered = [calls[index] for index in sorted(calls)]
            for number, call in enumerate(ordered):
                call["id"] = call["id"] or f"call_{number}"
            reply["tool_calls"] = ordered
        yield "message", reply

    async def _anthropic(
        self,
        http: ClientSession,
        history,
        message: str,
        mcp: McpBundle,
        origin: str,
        images: list[dict],
        language: str,
        admin: bool,
        force: bool = False,
        on_tool: Callable | None = None,
    ) -> AsyncIterator[dict]:
        messages: list[dict[str, Any]] = list(_history_messages(history))
        messages.append({"role": "user", "content": anthropic_user_content(message, images)})
        tools = _anthropic_tools(mcp.tools)
        url = f"{self._base()}/messages"
        headers = self._anthropic_headers()
        said: list[str] = []
        for round_no in range(_MAX_ROUNDS + 1):
            last = round_no == _MAX_ROUNDS
            payload: dict[str, Any] = {
                "model": self._model(),
                "max_tokens": _LOW_TOKEN_REPLY if self.settings.low_token else 4096,
                "system": self._system(origin, language, admin),
                "messages": messages,
            }
            if not self.settings.low_token:
                self._effort_body(payload)
            if tools:
                payload["tools"] = tools
                if last:
                    payload["tool_choice"] = {"type": "none"}
                elif round_no == 0 and force and self._force:
                    payload["tool_choice"] = {"type": "any"}
            blocks: list[dict] = []
            gap = bool(said)
            async for kind, value in self._anthropic_round(http, url, headers, payload):
                if kind == "message":
                    blocks = value
                    continue
                if gap:
                    said.append("\n\n")
                    yield {"type": "text", "delta": "\n\n"}
                    gap = False
                said.append(value)
                yield {"type": "text", "delta": value}
            uses = [block for block in blocks if block.get("type") == "tool_use"]
            if uses and not last:
                messages.append({"role": "assistant", "content": _clean_blocks(blocks)})
                results = []
                for block in uses:
                    name = str(block.get("name") or "tool")
                    label = _tool_label(mcp.original_name(name))
                    yield {"type": "tool", "name": name, "phase": "start", "text": f"Calling {label}..."}
                    args = block.get("input") if isinstance(block.get("input"), dict) else {}
                    try:
                        body = _tool_body(await self._invoke_tool(mcp, name, args, on_tool))
                    except _ERRORS as exc:
                        body = self._public(exc)
                    yield {"type": "tool", "name": name, "phase": "end", "text": f"Finished {label}"}
                    results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": body})
                messages.append({"role": "user", "content": results})
                continue
            break
        text = "".join(said).strip()
        if not text and last:
            yield {"type": "error", "message": "The model kept calling tools without finishing."}
            return
        yield {"type": "result", "text": text, "status": "finished"}

    async def _anthropic_round(
        self, http: ClientSession, url: str, headers: dict, payload: dict
    ) -> AsyncIterator[tuple[str, Any]]:
        if self._stream:
            try:
                async for item in self._anthropic_stream(http, url, headers, payload):
                    yield item
                return
            except _StreamUnsupported:
                self._stream = False
        data = await self._post(http, url, headers, payload)
        blocks = list(data.get("content") or [])
        for block in blocks:
            if block.get("type") == "text" and block.get("text"):
                yield "text", str(block["text"])
        yield "message", blocks

    async def _anthropic_stream(
        self, http: ClientSession, url: str, headers: dict, payload: dict
    ) -> AsyncIterator[tuple[str, Any]]:
        resp = await self._open(http, url, headers, {**payload, "stream": True}, stream=True)
        blocks: dict[int, dict[str, Any]] = {}
        partial: dict[int, list[str]] = {}
        try:
            async for event, raw in _sse(resp):
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = str(data.get("type") or event)
                index = int(data.get("index") or 0)
                if kind == "content_block_start":
                    block = dict(data.get("content_block") or {})
                    blocks[index] = block
                    if block.get("type") == "text" and block.get("text"):
                        yield "text", str(block["text"])
                elif kind == "content_block_delta":
                    delta = data.get("delta") or {}
                    block = blocks.setdefault(index, {"type": "text", "text": ""})
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        piece = str(delta.get("text") or "")
                        block["text"] = str(block.get("text") or "") + piece
                        if piece:
                            yield "text", piece
                    elif dtype == "input_json_delta":
                        partial.setdefault(index, []).append(str(delta.get("partial_json") or ""))
                    elif dtype == "thinking_delta":
                        block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
                    elif dtype == "signature_delta":
                        block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
                elif kind == "content_block_stop":
                    block = blocks.get(index) or {}
                    if block.get("type") == "tool_use":
                        raw_input = "".join(partial.pop(index, [])).strip()
                        try:
                            block["input"] = json.loads(raw_input) if raw_input else {}
                        except json.JSONDecodeError:
                            block["input"] = {}
                elif kind == "error":
                    err = data.get("error") or {}
                    raise ApiError(resp.status, str(err.get("message") or "The model provider failed."))
                elif kind == "message_stop":
                    break
        finally:
            resp.release()
        yield "message", [blocks[index] for index in sorted(blocks)]

    async def _open(
        self,
        http: ClientSession,
        url: str,
        headers: dict,
        payload: dict,
        *,
        timeout: float = 120,
        attempts: int = 4,
        stream: bool = False,
    ) -> ClientResponse:
        """A successful response; retries rate limits and drops effort the model refuses."""
        body = dict(payload)
        last = ""
        retries = max(1, attempts)
        attempt = 0
        while attempt < retries:
            attempt += 1
            resp = await http.post(
                url,
                json=body,
                headers=headers,
                timeout=ClientTimeout(total=None, sock_connect=30, sock_read=timeout)
                if stream
                else ClientTimeout(total=timeout),
            )
            if resp.status < 400:
                return resp
            text = await resp.text()
            resp.release()
            last = text
            low = text.lower()
            if resp.status == 429:
                wait = _retry_wait(resp, text)
                if wait is not None and attempt < retries:
                    logger.warning("api rate limited, retry in %.2fs", wait)
                    await asyncio.sleep(wait)
                    continue
            if resp.status == 400 and any(key in body for key in _EFFORT_KEYS) and (
                "effort" in low or "reasoning" in low or "output_config" in low
            ):
                logger.info("%s refused the effort setting; sending without it", self._label())
                self._effort = False
                for key in _EFFORT_KEYS:
                    body.pop(key, None)
                attempt -= 1
                continue
            if resp.status in {400, 422} and body.get("tool_choice") not in (None, "none", {"type": "none"}) and (
                "tool_choice" in low or "tool choice" in low or "tool_use" in low or "thinking" in low
            ):
                logger.info("%s refused a forced tool call; letting the model choose", self._label())
                self._force = False
                body.pop("tool_choice", None)
                attempt -= 1
                continue
            if stream and resp.status in {400, 404, 415, 422} and "stream" in low:
                raise _StreamUnsupported
            raise ApiError(resp.status, _friendly_api_error(resp.status, text))
        raise ApiError(429, _friendly_api_error(429, last))

    async def _post(
        self,
        http: ClientSession,
        url: str,
        headers: dict,
        payload: dict,
        timeout: float = 120,
        attempts: int = 4,
    ) -> dict:
        resp = await self._open(http, url, headers, payload, timeout=timeout, attempts=attempts)
        try:
            text = await resp.text()
        finally:
            resp.release()
        return json.loads(text)
