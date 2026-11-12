"""Sign in with Claude through the AI Workspace Runtime, for the agent form.

The runtime runs Anthropic's `claude setup-token`; Home Assistant only passes the sign-in link to
the form and the code from Anthropic's page back. The Claude Plan token that comes back is saved
on the agent like a pasted one.
"""

from __future__ import annotations

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

# The runtime waits up to 45 s for the link and 60 s for the token.
_START_TIMEOUT = 75
_FINISH_TIMEOUT = 90
# Runtime answers that the form shows as they are; anything else is a failed sign-in.
_KNOWN = {"cli_missing", "expired", "bad_code", "code_rejected", "timeout", "no_link"}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _call(hass: HomeAssistant, method: str, url: str, token: str, timeout: float, body: dict | None = None):
    session = async_get_clientsession(hass)
    try:
        resp = await session.request(
            method, url, json=body, headers=_headers(token), timeout=ClientTimeout(total=timeout)
        )
    except (ClientError, TimeoutError, OSError):
        return None, {}
    try:
        payload = await resp.json(content_type=None)
    except (ClientError, ValueError):
        payload = {}
    finally:
        resp.release()
    return resp.status, payload if isinstance(payload, dict) else {}


def _problem(status: int | None, payload: dict) -> str:
    if status is None:
        return "no_runtime"
    if status == 401:
        return "runtime_token"
    if status in (404, 405):
        # A runtime from before 1.6.0b7 has no sign-in.
        return "cli_missing"
    detail = str(payload.get("detail") or "")
    return detail if detail in _KNOWN else "login_failed"


async def async_start_login(hass: HomeAssistant, base: str, token: str) -> tuple[dict | None, str]:
    """({"id", "url"}, "") or (None, problem)."""
    status, payload = await _call(hass, "POST", f"{base.rstrip('/')}/api/claude/login", token, _START_TIMEOUT)
    if status == 200 and payload.get("id") and str(payload.get("url") or "").startswith("https://"):
        return {"id": str(payload["id"]), "url": str(payload["url"])}, ""
    return None, _problem(status, payload)


async def async_finish_login(hass: HomeAssistant, base: str, token: str, login_id: str, code: str) -> tuple[str, str]:
    """(Claude Plan token, "") or ("", problem)."""
    status, payload = await _call(
        hass, "POST", f"{base.rstrip('/')}/api/claude/login/{login_id}", token, _FINISH_TIMEOUT, {"code": code}
    )
    plan = str(payload.get("token") or "") if status == 200 else ""
    if plan.startswith("sk-ant-oat"):
        return plan, ""
    return "", _problem(status, payload) if status != 200 else "login_failed"


async def async_cancel_login(hass: HomeAssistant, base: str, token: str, login_id: str) -> None:
    await _call(hass, "DELETE", f"{base.rstrip('/')}/api/claude/login/{login_id}", token, 10)
