"""Local MCP proxy that compacts oversized tool results before Cursor reads them."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.tool_result import compact_mcp_response

logger = logging.getLogger(__name__)

_FORWARD = {
    "accept",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
    "authorization",
    "last-event-id",
}
_DROP = {"content-length", "transfer-encoding", "connection", "keep-alive"}


class FitRegistry:
    def __init__(self, secret_path: Path | None = None) -> None:
        self.secret = _load_secret(secret_path)
        self.upstreams: dict[str, dict[str, Any]] = {}

    def allows(self, secret: str, digest: str) -> bool:
        return hmac.compare_digest(secret, self.secret) and digest in self.upstreams

    def wrap(self, servers: dict[str, dict[str, Any]], base: str) -> dict[str, dict[str, Any]]:
        wrapped: dict[str, dict[str, Any]] = {}
        root = str(base or "").rstrip("/")
        for name, cfg in servers.items():
            url = str(cfg.get("url") or "")
            kind = str(cfg.get("type") or "")
            if not url or kind == "stdio" or "/api/mcp-fit/" in url:
                wrapped[name] = cfg
                continue
            digest = hashlib.sha256(
                json.dumps({"url": url, "headers": cfg.get("headers") or {}}, sort_keys=True).encode()
            ).hexdigest()[:20]
            self.upstreams[digest] = {"url": url, "headers": dict(cfg.get("headers") or {})}
            forwarded = dict(cfg)
            forwarded["url"] = f"{root}/api/mcp-fit/{self.secret}/{digest}"
            forwarded.pop("headers", None)
            wrapped[name] = forwarded
        return wrapped


async def proxy_mcp(request: Request, secret: str, digest: str) -> Response:
    runtime = getattr(request.app.state, "runtime", None)
    registry = getattr(runtime, "fit", None) if runtime is not None else None
    if registry is None or not registry.allows(secret, digest):
        raise HTTPException(status_code=404, detail="MCP fit route was not found.")
    upstream = registry.upstreams[digest]
    body = await request.body()
    headers = {str(key): str(value) for key, value in (upstream.get("headers") or {}).items()}
    for key, value in request.headers.items():
        if key.lower() in _FORWARD and value:
            headers[key] = value
    if "accept" not in {key.lower() for key in headers}:
        headers["Accept"] = "application/json, text/event-stream"
    try:
        status, response_headers, raw = await asyncio.to_thread(
            _forward,
            str(upstream["url"]),
            headers,
            body,
            request.method,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("mcp fit proxy failed: %s", exc)
        raise HTTPException(status_code=502, detail="The MCP server did not answer.") from exc
    content_type = response_headers.get("Content-Type") or response_headers.get("content-type") or ""
    if request.method.upper() == "POST":
        raw = compact_mcp_response(body, raw, content_type)
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
        logger.warning("mcp fit secret could not be stored", exc_info=True)
        return secrets.token_urlsafe(18)


def _forward(url: str, headers: dict[str, str], body: bytes, method: str) -> tuple[int, dict[str, str], bytes]:
    data = body if method.upper() not in {"GET", "HEAD"} else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
