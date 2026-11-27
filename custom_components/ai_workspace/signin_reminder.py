"""A repair notice a few weeks before the Runtime's Claude plan sign-in runs out.

`claude setup-token` gives a token that lasts one year, and nothing renews it: the user signs in
again on the agent form. The Runtime reports when the token was saved and when it runs out
(GET /api/auth/claude, never the token). Home Assistant checks that a few times a day while a
Claude (runtime) agent exists and shows a repair notice from WARN_DAYS before the date.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ISSUE_ID = "claude_signin_expiring"
WARN_DAYS = 30
_CHECK_EVERY = 6 * 3600
_CHECKED = f"{DOMAIN}_claude_signin_checked"


def days_left(status: dict[str, Any] | None, now: datetime | None = None) -> tuple[int, str] | None:
    """(whole days until the sign-in runs out, date) for a Runtime signed in here; else None."""
    if not isinstance(status, dict) or status.get("credential") != "signed-in":
        return None
    signed = status.get("signed_in")
    expires = str((signed or {}).get("expires_at") or "") if isinstance(signed, dict) else ""
    try:
        when = datetime.fromisoformat(expires)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return int((when - current).total_seconds() // 86400), when.date().isoformat()


def update_issue(hass: HomeAssistant, left: tuple[int, str] | None) -> None:
    """Show the notice from WARN_DAYS before the date (and after it); remove it otherwise."""
    if left is None or left[0] > WARN_DAYS:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
        return
    days, date = left
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ID,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR if days < 0 else ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ID,
        translation_placeholders={"date": date, "days": str(max(days, 0))},
    )


def signed_in_again(hass: HomeAssistant) -> None:
    """A new sign-in on the agent form: the notice goes now, the next check reads the new date."""
    try:
        hass.data.pop(_CHECKED, None)
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    except Exception:  # noqa: BLE001 - never stop the sign-in step over a notice.
        _LOGGER.debug("Claude sign-in notice not removed", exc_info=True)


async def async_check_claude_signin(hass: HomeAssistant, data: dict, url: str, token: str) -> None:
    """Read the Runtime's Claude sign-in date at most every few hours and update the notice."""
    providers = (data.get("providers") or {}).values()
    if not any(getattr(item, "kind", "") == "claude" for item in providers):
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
        return
    now = time.monotonic()
    last = hass.data.get(_CHECKED)
    if last is not None and now - float(last) < _CHECK_EVERY:
        return
    hass.data[_CHECKED] = now
    from .runtime_auth import async_auth_status

    try:
        status = await async_auth_status(hass, url, token, "claude")
    except Exception:  # noqa: BLE001 - a reminder must never break binding the Runtime.
        _LOGGER.debug("Claude sign-in date not read from the Runtime", exc_info=True)
        return
    update_issue(hass, days_left(status))
