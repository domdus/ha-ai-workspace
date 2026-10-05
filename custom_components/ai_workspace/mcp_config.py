from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

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
