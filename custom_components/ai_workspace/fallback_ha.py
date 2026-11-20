"""Home Assistant side of the agent fallback (fallback.py): settings, saved state, cheap checks."""

from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_ANTHROPIC, API_AZURE, DOMAIN, default_api_base
from .fallback import (
    CAP_CHAT,
    KIND_AUTH,
    KIND_CONNECTION,
    KIND_LIMIT,
    KIND_TIMEOUT,
    RETURN_MODES,
    DEFAULT_RETURN,
    Failure,
    FallbackBook,
    agent_caps,
    classify_status,
    clean_chain,
)

logger = logging.getLogger(__name__)

_STORE_KEY = f"{DOMAIN}.fallback"
_PROBE_TIMEOUT = 8
_ANTHROPIC_VERSION = "2023-06-01"


def fallback_chain(data: dict[str, Any]) -> list[str]:
    """The ordered agent ids when Fallback is on, else an empty list."""
    settings = data.get("settings")
    if not bool(getattr(settings, "fallback_enabled", False)):
        return []
    providers = data.get("providers") or {}
    chain = clean_chain(getattr(settings, "fallback_agents", ()) or (), providers.keys())
    return chain if chain else []


def fallback_return(data: dict[str, Any]) -> str:
    value = str(getattr(data.get("settings"), "fallback_return", "") or "")
    return value if value in RETURN_MODES else DEFAULT_RETURN


def caps_of(data: dict[str, Any]):
    providers = data.get("providers") or {}

    def caps(agent_id: str) -> frozenset[str]:
        provider = providers.get(agent_id)
        if provider is None:
            return frozenset()
        return agent_caps(str(getattr(provider, "kind", "") or ""))

    return caps


def available_of(data: dict[str, Any]):
    providers = data.get("providers") or {}

    def available(agent_id: str) -> bool:
        provider = providers.get(agent_id)
        return bool(provider is not None and provider.info.available)

    return available


def base_needs() -> set[str]:
    return {CAP_CHAT}


def book_of(hass: HomeAssistant, data: dict[str, Any]) -> FallbackBook:
    """The shared fallback state. Loaded once by async_load_book; empty until then."""
    book = data.get("fallback_book")
    if book is None:
        book = data["fallback_book"] = FallbackBook()
    return book


async def async_load_book(hass: HomeAssistant, data: dict[str, Any]) -> FallbackBook:
    book = book_of(hass, data)
    if data.get("fallback_loaded"):
        return book
    data["fallback_loaded"] = True
    try:
        from homeassistant.helpers.storage import Store

        store = Store(hass, 1, _STORE_KEY)
        book.load(await store.async_load())

        def save() -> None:
            store.async_delay_save(book.dump, 5)

        book.on_change = save
    except Exception:  # noqa: BLE001 - the state is a convenience; chats go on without it
        logger.debug("fallback state not loaded", exc_info=True)
    return book


def engine_of(provider: Any) -> str:
    return str(getattr(provider, "kind", "") or "")


def known_reset(hass: HomeAssistant, provider: Any, failure: Failure) -> Failure:
    """A limit without a reset time gets the one the plan data knows (Usage page, 1.6.0b12+)."""
    if failure.kind != KIND_LIMIT or failure.reset_at:
        return failure
    engine = failure.engine or engine_of(provider)
    try:
        from .plan_quota import rejection_reset_epoch, rejection_window
        from .plan_quota_store import plan_quota_cache

        snapshot = (plan_quota_cache(hass) or {}).get(engine) or {}
        window = failure.window or rejection_window(snapshot)
        reset = rejection_reset_epoch(snapshot, window) if str(snapshot.get("status") or "") == "rejected" else None
    except Exception:  # noqa: BLE001 - plan data is extra
        return failure
    if not reset:
        return failure
    return Failure(KIND_LIMIT, int(reset), engine, window)


async def async_probe(hass: HomeAssistant, data: dict[str, Any], agent_id: str) -> Failure | None:
    """A cheap check that an agent works again: status and sign-in, never a model prompt."""
    providers = data.get("providers") or {}
    provider = providers.get(agent_id)
    if provider is None:
        return Failure(KIND_CONNECTION)
    kind = engine_of(provider)
    try:
        if kind in {"cursor", "claude", "codex"}:
            return await _probe_runtime(hass, data, agent_id, kind)
        return await _probe_cloud(hass, data, agent_id)
    except TimeoutError:
        return Failure(KIND_TIMEOUT)
    except (ClientError, OSError):
        return Failure(KIND_CONNECTION)


async def _probe_runtime(hass: HomeAssistant, data: dict[str, Any], agent_id: str, kind: str) -> Failure | None:
    from .discovery import async_bind_runtime, async_runtime_health

    provider = (data.get("providers") or {}).get(agent_id)
    if provider is None or not provider.info.available:
        await async_bind_runtime(hass, data, force=True)
        provider = (data.get("providers") or {}).get(agent_id)
        if provider is None or not provider.info.available:
            return Failure(KIND_CONNECTION, engine=kind)
    base = str(data.get("runtime_url") or "").rstrip("/")
    if not base:
        return Failure(KIND_CONNECTION, engine=kind)
    health = await async_runtime_health(hass, base)
    if health is None or not health.get(kind):
        return Failure(KIND_CONNECTION, engine=kind)
    plan = (health.get("plan_quota") or {}).get(kind) or {}
    if str(plan.get("status") or "") == "rejected":
        from .plan_quota import rejection_reset_epoch, rejection_window

        reset = rejection_reset_epoch(plan, rejection_window(plan))
        if reset and int(reset) > time.time():
            return Failure(KIND_LIMIT, int(reset), kind)
    if str(getattr(provider, "api_key", "") or "").strip():
        # The agent brings its own key; the Runtime's sign-in says nothing about it.
        return None
    headers = {"Accept": "application/json"}
    token = str(data.get("runtime_token") or "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http = async_get_clientsession(hass)
    resp = await http.get(f"{base}/api/auth/{kind}", headers=headers, timeout=ClientTimeout(total=_PROBE_TIMEOUT))
    try:
        if resp.status == 404:
            # Older Runtime without sign-in status: health is all there is.
            return None
        if resp.status >= 400:
            return Failure(classify_status(resp.status) or KIND_CONNECTION, engine=kind)
        body = await resp.json(content_type=None)
    finally:
        resp.release()
    if isinstance(body, dict) and body.get("ready") is False:
        return Failure(KIND_AUTH, engine=kind)
    return None


async def _probe_cloud(hass: HomeAssistant, data: dict[str, Any], agent_id: str) -> Failure | None:
    from .agents import entry_agents

    provider = (data.get("providers") or {}).get(agent_id)
    if provider is not None and not provider.info.available:
        return Failure(KIND_AUTH)
    agent = next((item for item in entry_agents(data["entry"]) if item.id == agent_id), None) if data.get("entry") else None
    if agent is None or agent.provider == API_AZURE:
        # Nothing cheap to ask: try it with the next turn.
        return None
    base = (str(agent.api_base or "").strip() or default_api_base(agent.provider)).rstrip("/")
    if not base:
        return None
    key = str(agent.api_key or "").strip()
    if agent.provider == API_ANTHROPIC:
        headers = {"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION}
        url = f"{base}/models?limit=1"
    else:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        url = f"{base}/models"
    http = async_get_clientsession(hass)
    resp = await http.get(url, headers=headers, timeout=ClientTimeout(total=_PROBE_TIMEOUT))
    try:
        if resp.status < 400:
            return None
        kind = classify_status(resp.status)
    finally:
        resp.release()
    # A 404 or 400 here is the list endpoint, not the agent: it may still chat fine.
    return Failure(kind) if kind else None
