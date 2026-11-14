"""Talk to the AI Workspace Runtime's sign-in API (/api/auth/{engine}...).

The Runtime keeps the credential it gets from a sign-in in its own data folder. Home Assistant only
sees the sign-in link, the state and where the credential comes from, never the token.
"""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# Error keys the agent form knows; anything else is shown as login_failed.
KNOWN_ERRORS = frozenset(
    {
        "bad_code",
        "code_rejected",
        "too_many_attempts",
        "busy",
        "expired",
        "timeout",
        "cli_missing",
        "no_link",
        "login_failed",
        "not_supported",
        "no_runtime",
        "runtime_rejected",
        "runtime_old",
    }
)


class RuntimeAuthError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key if key in KNOWN_ERRORS else "login_failed"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _call(
    hass: HomeAssistant,
    method: str,
    base: str,
    path: str,
    token: str,
    *,
    body: dict | None = None,
    seconds: float = 10,
) -> dict[str, Any]:
    if not base:
        raise RuntimeAuthError("no_runtime")
    session = async_get_clientsession(hass)
    try:
        resp = await session.request(
            method,
            f"{base.rstrip('/')}{path}",
            headers=_headers(token),
            json=body,
            timeout=ClientTimeout(total=seconds),
        )
    except (ClientError, TimeoutError, OSError):
        raise RuntimeAuthError("no_runtime") from None
    try:
        if resp.status == 204:
            return {}
        try:
            payload = await resp.json(content_type=None)
        except (ClientError, ValueError):
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if resp.status == 401:
            raise RuntimeAuthError("runtime_rejected")
        if resp.status == 404 and detail in (None, "Not Found"):
            # A Runtime from before sign-in support.
            raise RuntimeAuthError("runtime_old")
        if resp.status >= 400:
            raise RuntimeAuthError(str(detail or "login_failed"))
        return payload if isinstance(payload, dict) else {}
    finally:
        resp.release()


async def async_auth_status(hass: HomeAssistant, base: str, token: str, engine: str) -> dict[str, Any]:
    return await _call(hass, "GET", base, f"/api/auth/{engine}", token, seconds=5)


async def async_login_start(hass: HomeAssistant, base: str, token: str, engine: str) -> dict[str, Any]:
    # The Runtime waits up to 45 s for the CLI to print the link.
    return await _call(hass, "POST", base, f"/api/auth/{engine}/login", token, seconds=60)


async def async_login_state(hass: HomeAssistant, base: str, token: str, engine: str, login_id: str) -> dict[str, Any]:
    return await _call(hass, "GET", base, f"/api/auth/{engine}/login/{login_id}", token, seconds=10)


async def async_login_code(
    hass: HomeAssistant, base: str, token: str, engine: str, login_id: str, code: str
) -> dict[str, Any]:
    # The Runtime waits up to 60 s for the CLI to print the token.
    return await _call(
        hass, "POST", base, f"/api/auth/{engine}/login/{login_id}", token, body={"code": code}, seconds=75
    )


async def async_login_cancel(hass: HomeAssistant, base: str, token: str, engine: str, login_id: str) -> None:
    try:
        await _call(hass, "DELETE", base, f"/api/auth/{engine}/login/{login_id}", token, seconds=5)
    except RuntimeAuthError:
        pass


async def async_logout(hass: HomeAssistant, base: str, token: str, engine: str) -> dict[str, Any]:
    return await _call(hass, "DELETE", base, f"/api/auth/{engine}", token, seconds=10)
