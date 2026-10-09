from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class McpConfigError(ValueError):
    pass


def _subst(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise McpConfigError(f"MCP config references unset environment variable ${{{name}}}")
        return os.environ[name]

    return _ENV.sub(replace, value)


def _stringify(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise McpConfigError(f"{field} must be a string")
    return _subst(value)


def server_to_sdk(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise McpConfigError(f"MCP server {name} must be an object")
    url = raw.get("url")
    command = raw.get("command")
    kind = str(raw.get("type") or "").strip().lower()
    if url or kind in {"http", "sse", "streamable-http", "streamable_http"}:
        if not url:
            raise McpConfigError(f"MCP server {name} has type {kind} but no url")
        transport = "sse" if kind == "sse" else "http"
        server: dict[str, Any] = {"type": transport, "url": _stringify(url, f"{name}.url")}
        headers = raw.get("headers")
        if headers is not None:
            if not isinstance(headers, dict):
                raise McpConfigError(f"{name}.headers must be an object")
            server["headers"] = {str(key): _stringify(val, f"{name}.headers.{key}") for key, val in headers.items()}
        return server
    if command:
        server = {"type": "stdio", "command": _stringify(command, f"{name}.command")}
        args = raw.get("args") or []
        if not isinstance(args, list):
            raise McpConfigError(f"{name}.args must be a list")
        server["args"] = [_stringify(item, f"{name}.args") for item in args]
        env = raw.get("env")
        if env is not None:
            if not isinstance(env, dict):
                raise McpConfigError(f"{name}.env must be an object")
            server["env"] = {str(key): _stringify(val, f"{name}.env.{key}") for key, val in env.items()}
        if raw.get("cwd"):
            server["cwd"] = _stringify(raw["cwd"], f"{name}.cwd")
        return server
    raise McpConfigError(f"MCP server {name} needs a url or a command")


def mcp_servers_from_url(url: str, token: str = "") -> dict[str, dict[str, Any]]:
    if not url:
        return {}
    raw: dict[str, Any] = {"url": url}
    secret = str(token or "").strip()
    if secret:
        raw["headers"] = {"Authorization": f"Bearer {secret}"}
    return {"mcp": server_to_sdk("mcp", raw)}


def load_mcp_servers(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"MCP config is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise McpConfigError("MCP config must be a JSON object")
    servers = data.get("mcpServers", data)
    if not isinstance(servers, dict):
        raise McpConfigError("mcpServers must be an object")
    return {str(name): server_to_sdk(str(name), cfg) for name, cfg in servers.items()}


_RESERVED_NAMES = {"mcp", "home-assistant", "ha", "ha-mcp"}
_SLUG = re.compile(r"[^a-z0-9]+")


def clean_mcp_extra(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url or name in seen:
            continue
        seen.add(name)
        found.append({"name": name, "url": url, "token": str(item.get("token") or "").strip()})
    return found


def server_slug(name: str, url: str) -> str:
    raw = str(name or "").strip().lower()
    if not raw:
        raw = (urlparse(str(url or "")).hostname or "connection").lower()
    slug = _SLUG.sub("-", raw).strip("-")[:40]
    if slug in _RESERVED_NAMES:
        slug = f"{slug}-extra"
    return slug


def mcp_servers_from_saved(url: str, token: str, extra: Any) -> dict[str, dict[str, Any]]:
    servers = mcp_servers_from_url(url, token)
    for item in clean_mcp_extra(extra):
        name = item["name"]
        if name in servers:
            name = f"{name}-2"
        raw: dict[str, Any] = {"url": item["url"]}
        if item["token"]:
            raw["headers"] = {"Authorization": f"Bearer {item['token']}"}
        servers[name] = server_to_sdk(name, raw)
    return servers


def _needs_ha_bearer(name: str, url: str, mcp_kind: str = "") -> bool:
    """True for Home Assistant APIs that reject unauthenticated calls (and spam the log)."""
    path = (urlparse(str(url or "")).path or "").lower()
    key = str(name or "").strip().lower()
    if key in {"catalog", "house-map"} or "/api/ai_workspace/catalog/" in path or "/api/ai_workspace/house_map/" in path:
        return True
    if "/api/mcp" in path:
        return True
    if mcp_kind == "ha" and key in {"mcp", "home-assistant", "ha", "ha-mcp"}:
        return True
    return False


def with_mcp_auth(
    servers: dict[str, dict[str, Any]] | None,
    *,
    access_token: str = "",
    mcp_token: str = "",
    mcp_kind: str = "",
) -> dict[str, dict[str, Any]]:
    """Attach a Bearer token to HA MCP endpoints; drop the catalog when none is available."""
    token = str(mcp_token or "").strip() or str(access_token or "").strip()
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in (servers or {}).items():
        raw = dict(cfg or {})
        url = str(raw.get("url") or "")
        if not _needs_ha_bearer(name, url, mcp_kind):
            out[name] = raw
            continue
        if not token:
            # Calling these without auth floods HA with "invalid authentication" warnings.
            continue
        headers = dict(raw.get("headers") or {})
        if "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {token}"
            raw["headers"] = headers
        out[name] = raw
    return out


def public_tool_names(groups: list[tuple[str, list[str]]]) -> dict[str, tuple[str, str]]:
    """Name the model sees -> (server, tool on that server)."""
    counts = Counter(name for _server, tools in groups for name in tools)
    routes: dict[str, tuple[str, str]] = {}
    for server, tools in groups:
        for name in tools:
            public = f"{server}__{name}" if counts[name] > 1 else name
            if public in routes:
                public = f"{server}__{name}"
            routes[public] = (server, name)
    return routes
