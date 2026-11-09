from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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


def ha_hosts(hass: HomeAssistant | None) -> frozenset[str]:
    """Host names that reach this Home Assistant, so its user token never leaves it."""
    hosts: set[str] = set()
    config = getattr(hass, "config", None)
    for raw in (getattr(config, "internal_url", None), getattr(config, "external_url", None)):
        host = urlparse(str(raw or "")).hostname
        if host:
            hosts.add(host.lower())
    api = getattr(config, "api", None)
    local_ip = getattr(api, "local_ip", None)
    if local_ip:
        hosts.add(str(local_ip).lower())
    return frozenset(hosts)


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


# Checked once at import (an executor job), never from the event loop.
_IN_CONTAINER = Path("/.dockerenv").exists()


def _in_container() -> bool:
    return _IN_CONTAINER


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


def supervisor_apps(hass: HomeAssistant) -> dict[str, dict]:
    """Installed Supervisor apps by slug, including ones installed after Core started.

    Since Home Assistant 2026.11 the info cache only holds apps that were installed
    when Core started (or that have entities). The app list is kept current, so a
    later install is taken from there, without hostname and ports.
    """
    try:
        from homeassistant.components.hassio import get_addons_info
    except ImportError:
        return {}
    try:
        apps = {str(slug): info for slug, info in dict(get_addons_info(hass) or {}).items()}
    except Exception:
        apps = {}
    try:
        from homeassistant.components.hassio import get_addons_list

        for item in get_addons_list(hass) or []:
            slug = str((item or {}).get("slug") or "")
            if slug and not apps.get(slug):
                apps[slug] = item
    except Exception:
        pass
    return apps


def _hassio_mcp_urls(hass: HomeAssistant) -> list[str]:
    addons = supervisor_apps(hass)
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


_COMPONENT_DOMAIN = "ha_mcp_tools"
_COMPONENT_PORT = 9584
# HA-MCP's webhook settings (options of its server entry).
_AUTH_SECRET_URL = "none"
_AUTH_HA_LOGIN = "ha_auth"
_AUTH_LEGACY_OAUTH = "legacy"


def _component_webhook_usable(blob: dict) -> bool:
    """HA-MCP's webhook answers us only when it is on and needs no OAuth client of its own.

    With the webhook off, Home Assistant still answers 200 with an empty body for the
    unknown webhook id. "Sign in with Home Assistant" accepts the chatting admin's login,
    which AI Workspace sends; the legacy OAuth mode needs a client id and secret it has not.
    """
    if not blob.get("enable_webhook", True):
        return False
    return str(blob.get("webhook_auth") or _AUTH_SECRET_URL) in {_AUTH_SECRET_URL, _AUTH_HA_LOGIN}


def ha_mcp_setup_hint(hass: HomeAssistant | None) -> str:
    """What to change in HA-MCP when its settings keep AI Workspace out, or ""."""
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if not callable(entries):
        return ""
    try:
        items = entries(_COMPONENT_DOMAIN)
    except TypeError:
        return ""
    for entry in items:
        data = getattr(entry, "data", {}) or {}
        if not data.get("webhook_id"):
            continue
        options = getattr(entry, "options", {}) or {}
        mode = str(options.get("webhook_auth") or _AUTH_SECRET_URL)
        if options.get("enable_webhook", True) and mode == _AUTH_LEGACY_OAUTH:
            return (
                "HA-MCP uses the legacy OAuth sign-in, which AI Workspace cannot use. In HA-MCP's "
                "Configure, set the authentication mode to \u201cSecret webhook URL\u201d or "
                "\u201cSign in with Home Assistant\u201d."
            )
        if mode == _AUTH_HA_LOGIN and options.get("enable_webhook", True):
            return (
                "HA-MCP is set to \u201cSign in with Home Assistant\u201d: it only lets in administrators, "
                "so chats of other users and chats without a login cannot use it. \u201cSecret webhook URL\u201d "
                "works for every chat."
            )
    return ""
_DOCKER_HA_HOSTS = ("homeassistant", "home-assistant")


def _same_network_urls(url: str) -> list[str]:
    """Loopback is this container. A sibling container reaches Home Assistant by its service name."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return [url]
    port = f":{parsed.port}" if parsed.port else ""
    names = [urlunparse(parsed._replace(netloc=f"{name}{port}")) for name in _DOCKER_HA_HOSTS]
    return [*names, url]


def _entry_mcp_urls(hass: HomeAssistant) -> list[str]:
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if not callable(entries):
        return []
    out = []
    try:
        items = entries()
    except TypeError:
        items = []
    api_base = hass_mcp_server_url(hass).rsplit("/api/mcp", 1)[0]
    for entry in items:
        domain = str(getattr(entry, "domain", "") or "").replace("-", "_").lower()
        if "mcp" not in domain or domain == "mcp_server":
            continue
        blob = {**getattr(entry, "data", {}), **getattr(entry, "options", {})}
        if str(blob.get("entry_type") or "") == "tools":
            continue
        locals_: list[str] = []
        for key in ("url", "mcp_url", "webhook_url", "listen_url", "connect_url", "server_url"):
            value = blob.get(key)
            if isinstance(value, str) and value.startswith("http"):
                locals_.append(value.strip())
        webhook_id = blob.get("webhook_id")
        webhook = ""
        if webhook_id and (domain != _COMPONENT_DOMAIN or _component_webhook_usable(blob)):
            webhook = f"{api_base}/api/webhook/{webhook_id}"
        secret = str(blob.get("secret_path") or "").strip()
        direct = ""
        if domain == _COMPONENT_DOMAIN and secret.startswith("/"):
            port = int(blob.get("server_port") or _COMPONENT_PORT)
            direct = f"http://127.0.0.1:{port}{secret}"
        # The login-protected webhook only lets in admins with a login; the direct address
        # works for every chat, so it goes first there.
        login = str(blob.get("webhook_auth") or "") == _AUTH_HA_LOGIN
        locals_.extend(url for url in ((direct, webhook) if login else (webhook, direct)) if url)
        for local in locals_:
            out.extend(_same_network_urls(local))
    return out


def _component_ports(hass: HomeAssistant | None) -> set[int]:
    ports = {_COMPONENT_PORT}
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    try:
        items = entries(_COMPONENT_DOMAIN) if callable(entries) else []
    except TypeError:
        items = []
    for entry in items:
        port = (getattr(entry, "options", {}) or {}).get("server_port")
        if str(port or "").isdigit():
            ports.add(int(port))
    return ports


def _loopback_host(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def for_runtime(servers: dict, hass: HomeAssistant | None, runtime_url: str, core_base: str) -> dict:
    """Point this Home Assistant's loopback MCP URLs at an address the Runtime can reach.

    Inside the Runtime App (or a Docker runtime on another host) 127.0.0.1 is the
    runtime itself, so http://127.0.0.1:8123/api/mcp is refused there. A runtime on
    loopback shares Core's network and keeps the URL as it is.
    """
    base = str(core_base or "").rstrip("/")
    if not base or not runtime_url or _loopback_host(runtime_url) or _loopback_host(base):
        return servers
    port, _tls = _api_port(hass)
    core = urlparse(base)
    # HA-MCP from the ha_mcp_tools integration listens inside Core, on its own port.
    components = getattr(getattr(hass, "config", None), "components", None) or ()
    in_core = _component_ports(hass) if _COMPONENT_DOMAIN in components else set()
    out: dict = {}
    for name, cfg in (servers or {}).items():
        raw = dict(cfg or {})
        url = str(raw.get("url") or "")
        parsed = urlparse(url)
        if url and _loopback_host(url):
            used = parsed.port or (443 if parsed.scheme == "https" else 80)
            if used == port:
                raw["url"] = urlunparse(parsed._replace(scheme=core.scheme, netloc=core.netloc))
            elif used in in_core:
                raw["url"] = urlunparse(parsed._replace(netloc=f"{core.hostname}:{used}"))
        out[name] = raw
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


def _builtin_mcp(url: str) -> bool:
    path = (urlparse(url).path or "").rstrip("/")
    return path == "/api/mcp"


async def async_probe_mcp(
    hass: HomeAssistant,
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 2,
) -> bool:
    extra = {key: value for key, value in (headers or {}).items() if value}
    # A token-less call to /api/mcp is a failed login and can ban 127.0.0.1.
    if _builtin_mcp(url) and not extra.get("Authorization"):
        return False
    session = async_get_clientsession(hass)
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
    # Home Assistant answers an unknown (or switched off) webhook with an empty 200.
    empty = resp.content_length == 0
    resp.release()
    if status in {401, 403}:
        return True
    return 200 <= status < 400 and not empty


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
        component = [url for url in _entry_mcp_urls(hass) if not _loopback_host(url)]
        candidates = [
            *component,
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


def _public(url: str) -> str:
    """Scheme, host and port only: HA-MCP keeps its secret in the path."""
    parsed = urlparse(str(url or ""))
    return urlunparse(parsed._replace(path="", params="", query="", fragment="")) or str(url or "")


def ha_mcp_url_is_wrong(url: str) -> bool:
    """An HA-MCP row on Home Assistant's own /api/mcp is the built-in server, not HA-MCP."""
    return _builtin_mcp(url)


async def async_better_ha_mcp_url(hass: HomeAssistant, url: str, token: str = "") -> tuple[str, bool]:
    """(better URL or "", saved URL works) for an HA-MCP row."""
    url = str(url or "").strip().rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if url and not ha_mcp_url_is_wrong(url) and await async_probe_mcp(hass, url, headers, timeout=3):
        return "", True
    found = await async_resolve_mcp_url(hass, MCP_HA_MCP, url, token)
    found = str(found or "").rstrip("/")
    if not found or found == url or _builtin_mcp(found):
        return "", False
    if not await async_probe_mcp(hass, found, headers, timeout=3):
        return "", False
    return found, False


_HEAL_DELAYS = (0, 30, 120)


async def async_heal_ha_mcp(hass: HomeAssistant, entry, subentry_type: str) -> None:
    """After startup, move HA-MCP rows that point at the wrong server or nowhere to a working HA-MCP.

    Runs after Home Assistant started, because HA-MCP inside Core (ha_mcp_tools)
    may only start late. Custom rows are never touched, and nothing changes when no
    working HA-MCP is found.
    """
    for delay in _HEAL_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        pending = False
        for sub in list(getattr(entry, "subentries", {}).values()):
            if sub.subentry_type != subentry_type:
                continue
            data = dict(sub.data)
            url = str(data.get("url") or "").strip()
            kind = str(data.get(CONF_MCP_KIND) or "").strip() or infer_mcp_kind(url)
            if kind != MCP_HA_MCP:
                continue
            better, works = await async_better_ha_mcp_url(hass, url, str(data.get("token") or ""))
            if not better:
                pending = pending or not works
                continue
            _LOGGER.warning(
                "AI Workspace: the HA-MCP connection %s pointed at %s; it now uses HA-MCP at %s",
                sub.title,
                _public(url) or "nothing",
                _public(better),
            )
            data["url"] = better
            hass.config_entries.async_update_subentry(entry, sub, data=data)
            # The update reloads the entry, which starts a fresh check.
            return
        if not pending:
            return
