from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# OpenAI Chat Completions rejects function.name longer than this.
OPENAI_TOOL_NAME_MAX = 64
_PREFIX_MAX = 16
_HASH_LEN = 8
_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_TRIMMED: set[str] = set()
_PREFIX_ALIASES = {
    "mcp": "ha",
    "home-assistant": "ha",
    "homeassistant": "ha",
    "ha-mcp": "hamcp",
    "ha_mcp": "hamcp",
    "hamcp": "hamcp",
    "catalog": "catalog",
    "house-map": "catalog",
}


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


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "homeassistant"})


def _needs_ha_bearer(name: str, url: str, ha_hosts: frozenset[str] | set[str]) -> bool:
    """True for this Home Assistant's own APIs, which reject unauthenticated calls."""
    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").lower()
    host = (parsed.hostname or "").lower()
    if host not in ha_hosts:
        return False
    key = str(name or "").strip().lower()
    if key in {"catalog", "house-map"}:
        return True
    return "/api/mcp" in path or "/api/ai_workspace/catalog/" in path or "/api/ai_workspace/house_map/" in path


def with_mcp_auth(
    servers: dict[str, dict[str, Any]] | None,
    *,
    access_token: str = "",
    ha_hosts: frozenset[str] | set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Sign this Home Assistant's MCP endpoints as the chatting user; drop them when nobody is signed in."""
    token = str(access_token or "").strip()
    hosts = frozenset(ha_hosts or ()) | LOOPBACK_HOSTS
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in (servers or {}).items():
        raw = dict(cfg or {})
        url = str(raw.get("url") or "")
        headers = dict(raw.get("headers") or {})
        if "Authorization" in headers or not _needs_ha_bearer(name, url, hosts):
            out[name] = raw
            continue
        if not token:
            # Calling these without auth floods HA with "invalid authentication" warnings.
            continue
        headers["Authorization"] = f"Bearer {token}"
        raw["headers"] = headers
        out[name] = raw
    return out


def is_local_hass_mcp_url(url: str, ha_hosts: frozenset[str] | set[str] | None = None) -> bool:
    """True for this Home Assistant's built-in /api/mcp (not HA-MCP on another host)."""
    parsed = urlparse(str(url or ""))
    if "/api/mcp" not in (parsed.path or "").lower():
        return False
    host = (parsed.hostname or "").lower()
    return host in (frozenset(ha_hosts or ()) | LOOPBACK_HOSTS)


def connection_prefix(server_key: str) -> str:
    """Short slug used only when two connections expose the same tool name."""
    raw = str(server_key or "").strip().lower()
    if raw in _PREFIX_ALIASES:
        return _PREFIX_ALIASES[raw]
    slug = _SLUG.sub("-", raw).strip("-")[:_PREFIX_MAX]
    if not slug:
        return "mcp"
    if slug in _PREFIX_ALIASES or slug in _PREFIX_ALIASES.values() or slug in _RESERVED_NAMES:
        slug = f"{slug[: max(1, _PREFIX_MAX - 2)]}-x".strip("-")
    return slug[:_PREFIX_MAX]


def _stable_hash(server_key: str, original_tool: str) -> str:
    blob = f"{server_key}\0{original_tool}".encode()
    return hashlib.sha1(blob).hexdigest()[:_HASH_LEN]


def _clean_openai_chars(name: str) -> str:
    cleaned = _NAME_CHARS.sub("_", str(name or "")).strip("_")
    return cleaned or "tool"


def _warn_trim(server_key: str, original_tool: str, old: str, new: str) -> None:
    key = f"{server_key}\0{original_tool}"
    if key in _TRIMMED:
        return
    _TRIMMED.add(key)
    _LOGGER.warning(
        "MCP tool name shortened for OpenAI (%s → %s, server %s tool %s)",
        old,
        new,
        server_key,
        original_tool,
    )


def sanitize_openai_tool_name(
    public_name: str,
    server_key: str,
    original_tool: str,
    used: set[str] | None = None,
) -> str:
    """OpenAI function.name: unique, [A-Za-z0-9_-], at most 64 characters."""
    taken = used if used is not None else set()
    digest = _stable_hash(server_key, original_tool)
    cleaned = _clean_openai_chars(public_name)
    if len(cleaned) <= OPENAI_TOOL_NAME_MAX and cleaned not in taken:
        if cleaned != str(public_name or ""):
            _warn_trim(server_key, original_tool, public_name, cleaned)
        return cleaned
    suffix = f"_{digest}"
    keep = max(1, OPENAI_TOOL_NAME_MAX - len(suffix))
    name = (cleaned[:keep] + suffix)[:OPENAI_TOOL_NAME_MAX]
    extra = 0
    while name in taken:
        extra += 1
        bump = f"_{extra}"
        compact = f"t_{digest}{bump}"
        name = compact[:OPENAI_TOOL_NAME_MAX]
        if extra > 32:
            break
    _warn_trim(server_key, original_tool, public_name, name)
    return name


def _prefixed_name(prefix: str, tool: str) -> str:
    sep = "__"
    if len(prefix) + len(sep) + len(tool) <= OPENAI_TOOL_NAME_MAX:
        return f"{prefix}{sep}{tool}"
    room = OPENAI_TOOL_NAME_MAX - len(sep) - len(tool)
    if room >= 2:
        return f"{prefix[:room]}{sep}{tool}"
    return f"{prefix}{sep}{tool}"


def public_tool_names(groups: list[tuple[str, list[str]]]) -> dict[str, tuple[str, str]]:
    """Name the model sees -> (server, tool on that server). Unique and ≤ 64 characters."""
    counts = Counter(name for _server, tools in groups for name in tools)
    routes: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    for server, tools in groups:
        prefix = connection_prefix(server)
        for name in tools:
            public = _prefixed_name(prefix, name) if counts[name] > 1 else name
            if _clean_openai_chars(public) in used:
                public = _prefixed_name(prefix, name)
            openai_name = sanitize_openai_tool_name(public, server, name, used)
            used.add(openai_name)
            routes[openai_name] = (server, name)
    return routes


def openai_tool_name_errors(names: list[str]) -> list[str]:
    """Names that OpenAI would reject (length or charset)."""
    allowed = re.compile(r"^[A-Za-z0-9_-]{1," + str(OPENAI_TOOL_NAME_MAX) + r"}$")
    return [name for name in names if not allowed.fullmatch(str(name or ""))]
