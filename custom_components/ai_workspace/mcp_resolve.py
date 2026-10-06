from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    COMPOSE_MCP_URL,
    CONF_MCP_KIND,
    CONF_MCP_URL,
    DEFAULT_COOLVER_URL,
    DEFAULT_MCP_URL,
    MCP_COOLVER,
    MCP_CUSTOM,
    MCP_HA,
    MCP_HA_MCP,
    MCP_KINDS,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)
_SIDECAR_PORTS = {8086, 9583, 9584, 8099}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "ai-workspace", "version": VERSION},
    },
}


def infer_mcp_kind(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    host = (parsed.hostname or "").lower()
    if path.startswith("/api/mcp"):
        return MCP_HA
    if parsed.port == 8099 or host in {"vibecode", "ha-vibecode"}:
        return MCP_COOLVER
    if not raw:
        return MCP_HA_MCP
    if host == "ha-mcp" or parsed.port in {8086, 9583, 9584} or "/private_" in path or "webhook" in path:
        return MCP_HA_MCP
    if path.endswith("/mcp") or parsed.port == 8086:
        return MCP_HA_MCP
    return MCP_CUSTOM


def _api_port(hass: HomeAssistant | None) -> tuple[int, bool]:
    port = 8123
    tls = False
    api = getattr(hass, "config", None)
    api = getattr(api, "api", None) if api is not None else None
    if api is not None:
        port = int(getattr(api, "port", None) or port)
        tls = bool(getattr(api, "use_ssl", False))
    return port, tls


def hass_mcp_server_url(hass: HomeAssistant | None) -> str:
    port, tls = _api_port(hass)
    scheme = "https" if tls else "http"
    return f"{scheme}://127.0.0.1:{port}/api/mcp"


def hass_mcp_server_urls(hass: HomeAssistant | None) -> list[str]:
    port, tls = _api_port(hass)
    urls = [f"http://127.0.0.1:{port}/api/mcp", f"http://localhost:{port}/api/mcp"]
    if tls:
        urls.extend(
            [
                f"https://127.0.0.1:{port}/api/mcp",
                f"https://localhost:{port}/api/mcp",
            ]
        )
    if hass is not None:
        try:
            from homeassistant.helpers.network import get_url

            base = get_url(hass, prefer_external=False, allow_cloud=False)
        except Exception:
            base = ""
        internal = getattr(getattr(hass, "config", None), "internal_url", None) or ""
        for raw in (base, internal):
            raw = str(raw or "").strip().rstrip("/")
            if raw.startswith("http"):
                urls.append(f"{raw}/api/mcp")
    return _unique(urls)


def default_mcp_url(hass: HomeAssistant | None, kind: str) -> str:
    if kind == MCP_HA:
        return hass_mcp_server_url(hass)
    if kind == MCP_COOLVER:
        return DEFAULT_COOLVER_URL
    if kind == MCP_CUSTOM:
        return ""
    return DEFAULT_MCP_URL


def mcp_kind_of(data: dict) -> str:
    kind = str(data.get(CONF_MCP_KIND) or "").strip()
    if kind in MCP_KINDS:
        return kind
    return infer_mcp_kind(str(data.get(CONF_MCP_URL) or ""))


def _on_hassio() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def loopback_alternates(url: str) -> list[str]:
    """Docker DNS aliases for a loopback sidecar URL. Skip on Home Assistant OS."""
    if _on_hassio():
        return []
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return []
    if parsed.port not in _SIDECAR_PORTS:
        return []
    path = parsed.path or "/mcp"
    scheme = parsed.scheme or "http"
    port = parsed.port
    aliases = ["host.docker.internal"]
    if _in_container():
        aliases.insert(0, "ha-mcp")
    return [f"{scheme}://{alias}:{port}{path}" for alias in aliases]


def _compose_mcp_urls() -> list[str]:
    if _on_hassio() or not _in_container():
        return []
    return [COMPOSE_MCP_URL]


def _sidecar_loopback_urls() -> list[str]:
    return [
        DEFAULT_MCP_URL,
        "http://127.0.0.1:9583/mcp",
        "http://127.0.0.1:9584/mcp",
    ]


def _hassio_mcp_urls(hass: HomeAssistant) -> list[str]:
    try:
        from homeassistant.components.hassio import get_addons_info
    except ImportError:
        return []
    try:
        addons = get_addons_info(hass)
    except Exception:
        return []
    if not addons:
        return []
    out = []
    for slug, info in addons.items():
        if not info:
            continue
        blob = f"{slug} {info.get('name') or ''} {info.get('hostname') or ''}".replace("-", "_").lower()
        if "mcp_server" in blob:
            continue
        if "ha_mcp" not in blob and not str(slug).lower().replace("-", "_").endswith("_mcp"):
            continue
        state = str(info.get("state") or "").lower()
        if state not in {"started", "running"}:
            continue
        hostname = info.get("hostname") or str(slug).replace("_", "-")
        ports = {8086, 9583, 9584}
        network = info.get("network") or {}
        if isinstance(network, dict):
            for key, value in network.items():
                text = str(key).split("/")[0]
                if str(text).isdigit():
                    ports.add(int(text))
                if str(value).isdigit():
                    ports.add(int(value))
        for port in sorted(ports):
            out.append(f"http://{hostname}:{port}/mcp")
    return out


def _entry_mcp_urls(hass: HomeAssistant) -> list[str]:
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if not callable(entries):
        return []
    out = []
    try:
        items = entries()
    except TypeError:
        items = []
    for entry in items:
        domain = str(getattr(entry, "domain", "") or "")
        if "mcp" not in domain.replace("-", "_") or domain == "mcp_server":
            continue
        blob = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
        for key in ("url", "mcp_url", "webhook_url", "listen_url", "connect_url", "server_url"):
            value = blob.get(key)
            if isinstance(value, str) and value.startswith("http"):
                out.append(value.strip())
        webhook_id = blob.get("webhook_id")
        if webhook_id:
            out.append(f"{hass_mcp_server_url(hass).rsplit('/api/mcp', 1)[0]}/api/webhook/{webhook_id}")
    return out


def _unique(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        url = str(url or "").strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


async def async_probe_mcp(
    hass: HomeAssistant,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 2,
) -> bool:
    session = async_get_clientsession(hass)
    extra = {key: value for key, value in (headers or {}).items() if value}
    try:
        resp = await session.post(
            url.rstrip("/"),
            json=_INIT,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                **extra,
            },
            timeout=ClientTimeout(total=timeout),
        )
    except (ClientError, TimeoutError, OSError, ValueError):
        return False
    status = resp.status
    resp.release()
    if status in {401, 403}:
        return True
    return 200 <= status < 400


def configured_mcp_kinds(hass: HomeAssistant) -> set[str]:
    """MCP providers already added under Devices & services."""
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if not callable(entries):
        return set()
    try:
        items = entries()
    except TypeError:
        return set()
    found: set[str] = set()
    for entry in items:
        domain = str(getattr(entry, "domain", "") or "").replace("-", "_").lower()
        if domain == "mcp_server":
            found.add(MCP_HA)
        elif "vibecode" in domain or "coolver" in domain:
            found.add(MCP_COOLVER)
        elif "mcp" in domain and domain not in {"mcp_server", "ai_workspace"}:
            found.add(MCP_HA_MCP)
    return found


async def async_detect_mcp_kinds(hass: HomeAssistant) -> list[str]:
    """Providers this Home Assistant can reach. Custom URL is added by the form."""
    found = configured_mcp_kinds(hass)
    probes: list[tuple[str, str]] = []
    if MCP_HA not in found:
        probes.extend((MCP_HA, url) for url in hass_mcp_server_urls(hass))
    probes.extend(
        (MCP_HA_MCP, url)
        for url in _unique(
            [
                *_entry_mcp_urls(hass),
                *_hassio_mcp_urls(hass),
                *_compose_mcp_urls(),
                *_sidecar_loopback_urls(),
                *loopback_alternates(DEFAULT_MCP_URL),
            ]
        )
    )
    probes.extend(
        (MCP_COOLVER, url)
        for url in _unique([DEFAULT_COOLVER_URL, *loopback_alternates(DEFAULT_COOLVER_URL)])
    )

    async def _hit(kind: str, url: str) -> str | None:
        if await async_probe_mcp(hass, url, timeout=1):
            return kind
        return None

    for kind in await asyncio.gather(*(_hit(kind, url) for kind, url in probes)):
        if kind:
            found.add(kind)
    return [kind for kind in (MCP_HA, MCP_HA_MCP, MCP_COOLVER) if kind in found]


async def async_resolve_mcp_url(
    hass: HomeAssistant,
    kind: str,
    configured: str,
    token: str = "",
) -> str:
    configured = str(configured or "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if kind == MCP_CUSTOM:
        return configured
    if kind == MCP_HA:
        candidates = []
        if configured.startswith("http") and "/api/mcp" in configured:
            candidates.append(configured)
        candidates.extend(hass_mcp_server_urls(hass))
        for url in _unique(candidates):
            if await async_probe_mcp(hass, url, headers):
                _LOGGER.info("AI Workspace MCP using %s", url)
                return url
        builtin = configured if configured.startswith("http") and "/api/mcp" in configured else hass_mcp_server_url(hass)
        _LOGGER.warning(
            "Built-in MCP at %s did not answer. Add Model Context Protocol Server in Devices & services.",
            builtin,
        )
        return builtin
    if kind == MCP_COOLVER:
        candidates = [configured, DEFAULT_COOLVER_URL, *loopback_alternates(configured or DEFAULT_COOLVER_URL)]
    else:
        skip_builtin = "/api/mcp" in urlparse(configured).path if configured else False
        start = [] if skip_builtin else [configured]
        candidates = [
            *start,
            *loopback_alternates(configured),
            *_entry_mcp_urls(hass),
            *_hassio_mcp_urls(hass),
            *_sidecar_loopback_urls(),
            *_compose_mcp_urls(),
            *loopback_alternates(DEFAULT_MCP_URL),
        ]
    fallback = configured or (DEFAULT_COOLVER_URL if kind == MCP_COOLVER else DEFAULT_MCP_URL)
    for url in _unique(candidates):
        if await async_probe_mcp(hass, url, headers):
            if configured and url != configured.rstrip("/"):
                _LOGGER.info("AI Workspace MCP %s is unreachable, using %s", configured, url)
            else:
                _LOGGER.info("AI Workspace MCP using %s", url)
            return url
    _LOGGER.warning("AI Workspace MCP did not answer; leaving %s", fallback)
    return fallback
