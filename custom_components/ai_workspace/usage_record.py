"""Persist one chat/Assist turn of token usage and notify sensors."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .store import Store
from .usage_cost import (
    EVENT_USAGE,
    SIGNAL_USAGE_UPDATE,
    TokenUsage,
    estimate_cost,
    estimate_tts_cost,
    parse_usage,
    usage_payload,
)

_LOGGER = logging.getLogger(__name__)
_TTS_USER: ContextVar[str] = ContextVar("ai_workspace_tts_user", default="")
_TTS_SESSION: ContextVar[str] = ContextVar("ai_workspace_tts_session", default="")


def zone_info(hass: HomeAssistant) -> ZoneInfo:
    name = str(hass.config.time_zone or "UTC")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def day_bounds(hass: HomeAssistant, now: datetime | None = None) -> tuple[str, str, str]:
    """Return ISO start of local today, tomorrow, and this month."""
    tz = zone_info(hass)
    current = (now or dt_util.now()).astimezone(tz)
    start_day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = start_day.replace(day=1)
    return (
        start_day.isoformat(),
        (start_day + timedelta(days=1)).isoformat(),
        start_month.isoformat(),
    )


def provider_id(provider: Any) -> str:
    return str(
        getattr(getattr(provider, "info", None), "id", None)
        or getattr(provider, "id", None)
        or getattr(provider, "kind", "")
        or ""
    )


def provider_label(provider: Any) -> str:
    info = getattr(provider, "info", None)
    return str(
        getattr(info, "label", None)
        or getattr(provider, "title", None)
        or provider_id(provider)
        or "Agent"
    )


def provider_kind(provider: Any) -> str:
    return str(
        getattr(provider, "kind", "")
        or getattr(provider, "provider", "")
        or getattr(getattr(provider, "settings", None), "api_provider", "")
        or ""
    )


def provider_model(provider: Any, fallback: str = "") -> str:
    return str(
        fallback
        or getattr(provider, "model", "")
        or getattr(getattr(provider, "settings", None), "model", "")
        or ""
    )


def finalize_usage(raw: object, *, model: str = "", run_id: str = "") -> TokenUsage | None:
    usage = parse_usage(raw, model=model, run_id=run_id)
    if usage.empty():
        return None
    return estimate_cost(usage, model=model or usage.model)


async def record_usage_turn(
    hass: HomeAssistant,
    *,
    store: Store,
    user_id: str,
    session_id: str,
    provider: Any | None,
    usage: TokenUsage,
    origin: str = "chat",
) -> dict[str, Any]:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    payload = usage_payload(usage)
    payload.update(
        {
            "agent_id": provider_id(provider),
            "agent": provider_label(provider),
            "provider": provider_kind(provider),
            "session_id": session_id,
            "origin": origin,
        }
    )
    if not bool(getattr(settings, "track_usage", True)):
        return payload
    await hass.async_add_executor_job(
        lambda: store.add_usage(
            user_id=user_id,
            session_id=session_id,
            agent_id=payload["agent_id"],
            agent=payload["agent"],
            provider=payload["provider"],
            model=payload.get("model") or "",
            prompt_tokens=int(payload.get("prompt_tokens") or 0),
            completion_tokens=int(payload.get("completion_tokens") or 0),
            cache_read_tokens=int(payload.get("cache_read_tokens") or 0),
            cache_write_tokens=int(payload.get("cache_write_tokens") or 0),
            reasoning_tokens=int(payload.get("reasoning_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
            characters=int(payload.get("characters") or 0),
            cost_usd=payload.get("cost_usd"),
            cost_source=str(payload.get("cost_source") or ""),
            charged_cents=payload.get("charged_cents"),
            run_id=str(payload.get("run_id") or ""),
            origin=origin,
        )
    )
    hass.bus.async_fire(EVENT_USAGE, payload)
    async_dispatcher_send(hass, SIGNAL_USAGE_UPDATE)
    _LOGGER.debug(
        "usage session=%s agent=%s tokens=%s cost=%s source=%s",
        session_id,
        payload["agent_id"],
        payload.get("total_tokens"),
        payload.get("cost_usd"),
        payload.get("cost_source"),
    )
    return payload


@contextmanager
def tts_usage_scope(*, user_id: str = "", session_id: str = "") -> Iterator[None]:
    """Attach the current chat user/session to an in-flight overlay TTS call."""
    user_token = _TTS_USER.set(str(user_id or ""))
    session_token = _TTS_SESSION.set(str(session_id or ""))
    try:
        yield
    finally:
        _TTS_USER.reset(user_token)
        _TTS_SESSION.reset(session_token)


async def record_tts_usage(
    hass: HomeAssistant,
    *,
    text: str,
    model: str,
    provider: Any | None = None,
    user_id: str = "",
    session_id: str = "",
) -> dict[str, Any] | None:
    data = hass.data.get(DOMAIN) or {}
    store = data.get("store")
    if store is None:
        return None
    usage = estimate_tts_cost(text, model)
    if usage.empty():
        return None
    return await record_usage_turn(
        hass,
        store=store,
        user_id=user_id or _TTS_USER.get(),
        session_id=session_id or _TTS_SESSION.get(),
        provider=provider,
        usage=usage,
        origin="tts",
    )


def dashboard_payload(hass: HomeAssistant, store: Store, *, session_id: str = "") -> dict[str, Any]:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    enabled = bool(getattr(settings, "track_usage", True))
    today, tomorrow, month = day_bounds(hass)
    totals = {
        "today": store.summarize_usage(since=today, until=tomorrow),
        "month": store.summarize_usage(since=month),
        "all": store.summarize_usage(),
    }
    last = store.last_usage()
    providers = (hass.data.get(DOMAIN) or {}).get("providers") or {}
    agents_cfg = list(providers.items())
    by_id = {row["agent_id"]: row for row in store.usage_by_agent(since=today, until=tomorrow)}
    month_by = {row["agent_id"]: row for row in store.usage_by_agent(since=month)}
    all_by = {row["agent_id"]: row for row in store.usage_by_agent()}
    agents = []
    seen: set[str] = set()
    for agent_id, provider in agents_cfg:
        seen.add(agent_id)
        agents.append(
            {
                "id": agent_id,
                "title": provider_label(provider),
                "provider": provider_kind(provider),
                "model": provider_model(provider),
                "today": store.summarize_usage(since=today, until=tomorrow, agent_id=agent_id),
                "month": store.summarize_usage(since=month, agent_id=agent_id),
                "all": store.summarize_usage(agent_id=agent_id),
            }
        )
    for extra_id, row in all_by.items():
        if extra_id in seen:
            continue
        agents.append(
            {
                "id": extra_id or "unknown",
                "title": row.get("agent") or extra_id or "Unknown",
                "provider": row.get("provider") or "",
                "model": row.get("model") or "",
                "today": by_id.get(extra_id) or store.summarize_usage(since=today, until=tomorrow, agent_id=extra_id),
                "month": month_by.get(extra_id) or store.summarize_usage(since=month, agent_id=extra_id),
                "all": row,
            }
        )
    session = store.summarize_usage(session_id=session_id) if session_id else None
    last_session = store.last_usage(session_id=session_id) if session_id else None
    tts = {
        "today": store.summarize_usage(since=today, until=tomorrow, origin="tts"),
        "month": store.summarize_usage(since=month, origin="tts"),
        "all": store.summarize_usage(origin="tts"),
        "session": store.summarize_usage(session_id=session_id, origin="tts") if session_id else None,
    }
    return {
        "enabled": enabled,
        "totals": totals,
        "tts": tts,
        "last": last,
        "agents": agents,
        "session": session,
        "session_last": last_session,
    }
