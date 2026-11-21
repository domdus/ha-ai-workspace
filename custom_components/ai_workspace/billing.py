"""How an agent really pays, so the chat header shows plan limits only where a plan pays.

The agent alone does not say it for a runtime agent (Claude or Codex without a key of its own): the
Runtime then uses its own credential, which can be a plan sign-in or an API key from its environment.
The Runtime reports per engine which one it uses (``credentials`` in /api/health, see the Runtime's
app/credentials.py); this module resolves ``billing`` with it:

- ``plan``    (own Plan token)                     -> plan, plan_credential = credential_id(token)
- ``runtime`` + Runtime reports ``subscription``   -> plan, plan_credential = the Runtime's ID
- ``runtime`` + Runtime reports ``api_key``        -> api_key ($)
- ``runtime`` + Runtime unreachable / no report    -> unknown ($; never plan % on uncertainty)
- anything else                                    -> unchanged ($)

The chat shows a plan snapshot for an agent only when the snapshot's ``credential`` equals the agent's
``plan_credential``: plan data from another engine, sign-in or token is never used.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .plan_quota import credential_id

_LOGGER = logging.getLogger(__name__)

CACHE_KEY = "runtime_credentials"
MAX_AGE = 30.0
KINDS = frozenset({"subscription", "api_key"})


def credentials_from_health(health: Any) -> dict[str, dict[str, Any]]:
    """The ``credentials`` block of a /api/health answer, cleaned; {} for an older or silent Runtime."""
    block = health.get("credentials") if isinstance(health, dict) else None
    if not isinstance(block, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for engine, row in block.items():
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        out[str(engine).strip().lower()] = {
            "kind": kind if kind in KINDS else None,
            "source": str(row.get("source") or ""),
            "id": str(row.get("id") or "") if kind == "subscription" else "",
        }
    return out


def store_runtime_credentials(hass: HomeAssistant, health: Any, *, now: float | None = None) -> None:
    """Remember what the Runtime reported (None health: unreachable, which forgets the last report)."""
    bucket = hass.data.setdefault(DOMAIN, {})
    bucket[CACHE_KEY] = {
        "at": time.monotonic() if now is None else now,
        "engines": credentials_from_health(health) if health is not None else {},
    }


def cached_runtime_credentials(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    cached = (hass.data.get(DOMAIN) or {}).get(CACHE_KEY)
    engines = cached.get("engines") if isinstance(cached, dict) else None
    return engines if isinstance(engines, dict) else {}


async def async_runtime_credentials(hass: HomeAssistant, *, max_age: float = MAX_AGE) -> dict[str, dict[str, Any]]:
    """The Runtime's credential report, read again when older than ``max_age``. {} when unknown."""
    bucket = hass.data.setdefault(DOMAIN, {})
    cached = bucket.get(CACHE_KEY)
    if isinstance(cached, dict) and time.monotonic() - float(cached.get("at") or 0) < max_age:
        return cached_runtime_credentials(hass)
    base = str(bucket.get("runtime_url") or "")
    health = None
    if base:
        from .discovery import async_runtime_health

        try:
            health = await async_runtime_health(hass, base)
        except Exception:  # noqa: BLE001 - unknown means $, never plan %
            _LOGGER.debug("Runtime credentials not read", exc_info=True)
    store_runtime_credentials(hass, health)
    return cached_runtime_credentials(hass)


def resolve_billing(billing: str, engine: str, own_key: str, runtime: dict[str, dict[str, Any]] | None) -> dict[str, str]:
    """{"billing": plan | api_key | unknown | ..., "billing_source": agent | runtime, "plan_credential": id}."""
    billing = str(billing or "")
    if billing == "plan":
        ident = credential_id(own_key)
        if ident:
            return {"billing": "plan", "billing_source": "agent", "plan_credential": ident}
        return {"billing": "unknown", "billing_source": "agent", "plan_credential": ""}
    if billing != "runtime":
        return {"billing": billing or "api", "billing_source": "agent", "plan_credential": ""}
    row = (runtime or {}).get(str(engine or "").strip().lower()) or {}
    kind = row.get("kind")
    if kind == "subscription" and row.get("id"):
        return {"billing": "plan", "billing_source": "runtime", "plan_credential": str(row["id"])}
    if kind == "api_key":
        return {"billing": "api_key", "billing_source": "runtime", "plan_credential": ""}
    return {"billing": "unknown", "billing_source": "runtime", "plan_credential": ""}


def resolve_row(row: dict[str, Any], provider: Any, runtime: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """An agent row of /api/ai_workspace/providers with its billing resolved (in place, returned)."""
    resolved = resolve_billing(
        str(row.get("billing") or ""),
        str(row.get("provider") or getattr(provider, "kind", "") or ""),
        str(getattr(provider, "api_key", "") or ""),
        runtime,
    )
    row.update(resolved)
    return row
