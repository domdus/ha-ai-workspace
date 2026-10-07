from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def rewrite_loopback_url(url: str, host: str | None = None) -> str:
    """Map 127.0.0.1 MCP URLs to the Docker host when the runtime is not on host network."""
    target = (host if host is not None else os.environ.get("REWRITE_LOOPBACK_HOST") or "").strip()
    if not target or not url:
        return url
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in _LOOPBACK:
        return url
    user = parsed.username or ""
    if parsed.password:
        user = f"{user}:{parsed.password}"
    auth = f"{user}@" if user else ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunparse(parsed._replace(netloc=f"{auth}{target}{port}"))


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
        server: dict[str, Any] = {
            "type": transport,
            "url": rewrite_loopback_url(_stringify(url, f"{name}.url")),
        }
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


_HA_MCP_NAMES = {"home-assistant", "mcp", "ha", "ha-mcp"}


def mcp_servers_from_url(url: str, token: str = "") -> dict[str, dict[str, Any]]:
    if not url:
        return {}
    raw: dict[str, Any] = {"url": url}
    secret = str(token or "").strip()
    if secret:
        raw["headers"] = {"Authorization": f"Bearer {secret}"}
    return {"mcp": server_to_sdk("mcp", raw)}


def servers_from_chat_mcp(mcp: Any) -> dict[str, dict[str, Any]]:
    if mcp is None:
        return {}
    if hasattr(mcp, "model_dump"):
        mcp = mcp.model_dump()
    if not isinstance(mcp, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    raw_servers = mcp.get("servers")
    if isinstance(raw_servers, dict):
        for name, cfg in raw_servers.items():
            out[str(name)] = server_to_sdk(str(name), cfg)
    url = str(mcp.get("url") or "").strip()
    token = str(mcp.get("token") or "").strip()
    if url and not out:
        out = mcp_servers_from_url(url, token)
    return out


def _is_loopback(url: str) -> bool:
    return (urlparse(str(url or "")).hostname or "").lower() in _LOOPBACK


def merge_mcp_servers(
    file_servers: dict[str, dict[str, Any]],
    request_servers: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not request_servers:
        return dict(file_servers)
    # 127.0.0.1 inside Home Assistant is not 127.0.0.1 inside the runtime container.
    # Keep a docker-network server from mcp.json instead of that loopback URL.
    request_ha = {name: cfg for name, cfg in request_servers.items() if name in _HA_MCP_NAMES}
    request_ha_loopback = bool(request_ha) and all(_is_loopback(str(cfg.get("url") or "")) for cfg in request_ha.values())
    file_ha_reachable = any(
        name in _HA_MCP_NAMES and cfg.get("url") and not _is_loopback(str(cfg.get("url") or ""))
        for name, cfg in file_servers.items()
    )
    skip_request_ha = request_ha_loopback and file_ha_reachable
    incoming_ha = bool(request_ha) and not skip_request_ha
    merged: dict[str, dict[str, Any]] = {}
    for name, cfg in file_servers.items():
        if incoming_ha and name in _HA_MCP_NAMES:
            continue
        if name in request_servers and not (skip_request_ha and name in _HA_MCP_NAMES):
            continue
        merged[name] = cfg
    for name, cfg in request_servers.items():
        if skip_request_ha and name in _HA_MCP_NAMES:
            continue
        merged[name] = cfg
    return merged


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
