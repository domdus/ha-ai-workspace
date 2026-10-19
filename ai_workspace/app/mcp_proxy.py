"""MCP proxy: route Cursor MCP through the Runtime, record Change History, shorten large results."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.settings import _default_hass_url, _read_options
from app.tool_result import shorten_mcp_response

logger = logging.getLogger(__name__)

_FORWARD = {
    "accept",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
    "last-event-id",
}
# Never forward Authorization from Cursor. Auth for HA /api/mcp (and other MCP
# that needs a Bearer) is stored on the upstream when the chat wraps servers.
# Cursor's own Authorization would overwrite that and HA logs ban warnings.
_DROP = {"content-length", "transfer-encoding", "connection", "keep-alive"}


_MAX_UPSTREAMS = 64


class McpProxy:
    def __init__(self, secret_path: Path | None = None) -> None:
        self.secret = _load_secret(secret_path)
        self.upstreams: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.actors: OrderedDict[str, dict[str, str]] = OrderedDict()

    def allows(self, secret: str, digest: str) -> bool:
        return hmac.compare_digest(secret, self.secret) and digest in self.upstreams

    def wrap(self, servers: dict[str, dict[str, Any]], base: str, actor: str = "") -> dict[str, dict[str, Any]]:
        wrapped: dict[str, dict[str, Any]] = {}
        root = str(base or "").rstrip("/")
        for name, cfg in servers.items():
            url = str(cfg.get("url") or "")
            kind = str(cfg.get("type") or "")
            if not url or kind == "stdio" or "/api/mcp-proxy/" in url or "/api/mcp-fit/" in url:
                wrapped[name] = cfg
                continue
            digest = hashlib.sha256(
                json.dumps({"url": url, "headers": cfg.get("headers") or {}}, sort_keys=True).encode()
            ).hexdigest()[:20]
            self.upstreams[digest] = {"url": url, "headers": dict(cfg.get("headers") or {})}
            self.upstreams.move_to_end(digest)
            while len(self.upstreams) > _MAX_UPSTREAMS:
                self.upstreams.popitem(last=False)
            forwarded = dict(cfg)
            forwarded["url"] = f"{root}/api/mcp-proxy/{self.secret}/{digest}"
            if actor:
                forwarded["url"] += f"/{actor}"
            forwarded.pop("headers", None)
            wrapped[name] = forwarded
        return wrapped

    def note_actor(self, session_id: str, user_id: str, agent: str) -> None:
        session_id = str(session_id or "").strip()
        user_id = str(user_id or "").strip()
        if not session_id or not user_id:
            return
        self.actors[session_id] = {"user_id": user_id, "agent": str(agent or "Cursor")[:120]}
        self.actors.move_to_end(session_id)
        while len(self.actors) > _MAX_UPSTREAMS:
            self.actors.popitem(last=False)

    def actor(self, session_id: str) -> dict[str, str] | None:
        found = self.actors.get(str(session_id or ""))
        return dict(found) if found else None


def parse_tool_call(body: bytes) -> tuple[str, dict[str, Any]] | None:
    """Return the tool name and arguments when this MCP body is a tools/call."""
    raw = (body or b"").strip()
    if not raw:
        return None
    payload: Any
    if raw.startswith(b"{") or raw.startswith(b"["):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        payload = None
        for chunk in _json_messages(raw.decode("utf-8", "replace")):
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            break
        if payload is None:
            return None
    messages = payload if isinstance(payload, list) else [payload]
    for message in messages:
        found = _tool_call_from_message(message)
        if found is not None:
            return found
    return None


def _tool_call_from_message(message: Any) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(message, dict) or message.get("method") != "tools/call":
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    name = str(params.get("name") or "").strip()
    if not name:
        return None
    raw_args = params.get("arguments")
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed = {}
        arguments = parsed if isinstance(parsed, dict) else {}
    elif isinstance(raw_args, dict):
        arguments = raw_args
    else:
        arguments = {}
    return name, arguments


def _json_messages(text: str):
    body = text.strip()
    if body.startswith("{") or body.startswith("["):
        yield body
        return
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{") or line.startswith("["):
            yield line


def tool_response_ok(status: int, raw: bytes) -> bool:
    """True when the MCP call itself succeeded.

    A description or skill text may contain the words ``isError: true``. Only
    the tool result flag counts. A JSON-RPC result with no flag is success.
    """
    if status >= 400:
        return False
    text = raw.decode("utf-8", "replace")
    saw_result = False
    for chunk in _json_messages(text):
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            messages = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            messages = [payload]
        else:
            continue
        for message in messages:
            result = message.get("result") if isinstance(message.get("result"), dict) else message
            if not isinstance(result, dict):
                continue
            if result.get("isError") is True:
                return False
            if "isError" in result or "content" in result or "structuredContent" in result:
                saw_result = True
            elif result.get("success") is True:
                saw_result = True
    if saw_result:
        return True
    return '"isError": true' not in text and '"isError":true' not in text


async def proxy_mcp(request: Request, secret: str, digest: str, actor: str = "") -> Response:
    runtime = getattr(request.app.state, "runtime", None)
    registry = getattr(runtime, "proxy", None) if runtime is not None else None
    if registry is None or not registry.allows(secret, digest):
        raise HTTPException(status_code=404, detail="MCP proxy route was not found.")
    upstream = registry.upstreams[digest]
    body = await request.body()
    headers = {str(key): str(value) for key, value in (upstream.get("headers") or {}).items()}
    for key, value in request.headers.items():
        if key.lower() in _FORWARD and value:
            headers[key] = value
    if "accept" not in {key.lower() for key in headers}:
        headers["Accept"] = "application/json, text/event-stream"
    target = str(upstream.get("url") or "")
    if _is_builtin_mcp(target) and not _header(headers, "authorization"):
        logger.warning("mcp proxy refused /api/mcp without Bearer (avoids HA ban noise)")
        raise HTTPException(status_code=502, detail="Built-in MCP needs a Home Assistant login.")
    tool_call = parse_tool_call(body) if request.method.upper() == "POST" else None
    activity_token = ""
    if tool_call is not None and _change_history_enabled(request):
        activity_token = await _activity_prepare(request, registry, actor, tool_call)
        if not activity_token:
            name, _arguments = tool_call
            base, _token = _activity_target(request)
            who = registry.actor(actor)
            if not base:
                logger.warning(
                    "activity prepare skipped for %s: runtime hass_url is not configured",
                    name,
                )
            elif not who:
                logger.info(
                    "activity prepare skipped for %s: no chat actor for session %s",
                    name,
                    actor[:12] if actor else "?",
                )
            else:
                logger.info("activity prepare returned no token for %s", name)
    try:
        status, response_headers, raw = await asyncio.to_thread(
            _forward,
            target,
            headers,
            body,
            request.method,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if activity_token:
            await _activity_commit(request, activity_token, ok=False)
        logger.warning("mcp proxy failed: %s", exc)
        raise HTTPException(status_code=502, detail="The MCP server did not answer.") from exc
    content_type = response_headers.get("Content-Type") or response_headers.get("content-type") or ""
    if activity_token:
        await _activity_commit(request, activity_token, ok=tool_response_ok(status, raw))
    kind = "unchanged"
    if request.method.upper() == "POST":
        raw, kind = shorten_mcp_response(body, raw, content_type, enabled=_shorten_enabled(request))
        if tool_call is not None:
            name, _arguments = tool_call
            logger.debug("mcp proxy last tool result: %s %s", name, kind)
            if kind not in {"unchanged", "off"}:
                logger.info("mcp proxy last tool result: %s %s", name, kind)
            await _note_mcp_result(request, registry, actor, name, kind)
    kept = {}
    for key, value in response_headers.items():
        if key.lower() in _DROP:
            continue
        if key.lower() in {"content-type", "mcp-session-id"}:
            kept[key] = value
    if content_type and "content-type" not in {key.lower() for key in kept}:
        kept["Content-Type"] = content_type
    return Response(content=raw, status_code=status, headers=kept)


def _load_secret(path: Path | None) -> str:
    if path is None:
        return secrets.token_urlsafe(18)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        if existing:
            return existing
        secret = secrets.token_urlsafe(18)
        path.write_text(secret, encoding="utf-8")
        return secret
    except OSError:
        logger.warning("mcp proxy secret could not be stored", exc_info=True)
        return secrets.token_urlsafe(18)


def _header(headers: dict[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return str(value or "").strip()
    return ""


def _is_builtin_mcp(url: str) -> bool:
    from urllib.parse import urlparse

    path = (urlparse(str(url or "")).path or "").rstrip("/").lower()
    return path == "/api/mcp"


def _activity_target(request: Request) -> tuple[str, str]:
    settings = getattr(request.app.state, "settings", None)
    token = str(getattr(settings, "runtime_token", "") or "").strip()
    base = str(getattr(settings, "hass_url", "") or "").rstrip("/")
    if not base:
        base = _default_hass_url(_read_options()).rstrip("/")
    return base, token


def proxy_secret_path(data_dir: Path) -> Path:
    """Keep the existing secret file so in-flight Cursor MCP URLs stay valid."""
    fresh = data_dir / "mcp-proxy-secret"
    legacy = data_dir / "mcp-fit-secret"
    return fresh if fresh.is_file() or not legacy.is_file() else legacy


def _shorten_enabled(request: Request) -> bool:
    state = getattr(request.app.state, "shorten_mcp_results", None)
    if state is not None:
        return bool(state)
    settings = getattr(request.app.state, "settings", None)
    return bool(getattr(settings, "shorten_mcp_results", True))


def _change_history_enabled(request: Request) -> bool:
    state = getattr(request.app.state, "change_history", None)
    if state is not None:
        return bool(state)
    settings = getattr(request.app.state, "settings", None)
    return bool(getattr(settings, "change_history", True))


async def _note_mcp_result(
    request: Request, registry: McpProxy, actor: str, tool: str, kind: str
) -> None:
    who = registry.actor(actor) or {}
    base, token = _activity_target(request)
    if not base:
        return
    payload = json.dumps(
        {"tool": tool, "kind": kind, "agent": who.get("agent") or "Cursor"}
    ).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        await asyncio.to_thread(
            _forward,
            f"{base}/api/ai_workspace/mcp_proxy",
            headers,
            payload,
            "POST",
            8,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.debug("mcp proxy result note failed", exc_info=True)


async def _activity_prepare(
    request: Request,
    registry: McpProxy,
    actor: str,
    tool_call: tuple[str, dict[str, Any]],
) -> str:
    who = registry.actor(actor)
    base, token = _activity_target(request)
    if who is None or not base:
        return ""
    name, arguments = tool_call
    payload = {
        "user_id": who["user_id"],
        "agent": who.get("agent") or "Cursor",
        "session_id": actor,
        "tool": name,
        "arguments": arguments,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        status, _headers, raw = await asyncio.to_thread(
            _forward,
            f"{base}/api/ai_workspace/activity/prepare",
            headers,
            json.dumps(payload).encode(),
            "POST",
            15,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("activity prepare failed", exc_info=True)
        return ""
    if status >= 400:
        detail = raw.decode("utf-8", "replace")[:200]
        logger.warning("activity prepare HTTP %s: %s", status, detail)
        return ""
    try:
        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return ""
    return str(body.get("token") or "") if isinstance(body, dict) else ""


async def _activity_commit(request: Request, token: str, *, ok: bool) -> None:
    base, runtime_token = _activity_target(request)
    if not base or not token:
        return
    payload = json.dumps({"token": token, "ok": ok}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if runtime_token:
        headers["Authorization"] = f"Bearer {runtime_token}"
    try:
        await asyncio.to_thread(
            _forward,
            f"{base}/api/ai_workspace/activity/commit",
            headers,
            payload,
            "POST",
            25,
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("activity commit failed", exc_info=True)


def _forward(
    url: str, headers: dict[str, str], body: bytes, method: str, timeout: int = 120
) -> tuple[int, dict[str, str], bytes]:
    data = body if method.upper() not in {"GET", "HEAD"} else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
