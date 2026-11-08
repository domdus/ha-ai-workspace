"""Keys that let the Cursor Runtime call back into Home Assistant for one chat.

Home Assistant hands the Runtime a fresh random key with every Cursor turn. The Runtime's
callbacks (Change History snapshots, MCP result notes) must carry that key. The user and
chat come from Home Assistant's own record of whom the key was issued to, never from the
request body, and there is no exception for callers on this host.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_STORE = f"{DOMAIN}_callback_keys"
# Long enough for a slow Cursor turn with many tool calls.
TTL_SECONDS = 6 * 3600
_MAX_KEYS = 256


@dataclass(frozen=True)
class Caller:
    user_id: str
    session_id: str
    agent: str
    expires: float
    # The chatting user's own login for this turn, so Change History reads helpers through
    # Home Assistant's websocket API with that user's permissions. Never sent anywhere else.
    access_token: str = ""


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _keys(hass: HomeAssistant) -> OrderedDict[str, Caller]:
    return hass.data.setdefault(_STORE, OrderedDict())


def issue(
    hass: HomeAssistant,
    user_id: str,
    session_id: str,
    agent: str = "Cursor",
    now: float | None = None,
    access_token: str = "",
) -> str:
    """A new key for one Cursor turn of this user's chat."""
    stamp = time.monotonic() if now is None else now
    keys = _keys(hass)
    _prune(keys, stamp)
    key = secrets.token_urlsafe(32)
    keys[_digest(key)] = Caller(
        str(user_id), str(session_id), str(agent or "Cursor")[:120], stamp + TTL_SECONDS, str(access_token or "")
    )
    while len(keys) > _MAX_KEYS:
        keys.popitem(last=False)
    return key


def caller(hass: HomeAssistant, authorization: str | None, now: float | None = None) -> Caller | None:
    """Whom the bearer key in this header was issued to, or None."""
    scheme, _, value = str(authorization or "").partition(" ")
    key = value.strip() if scheme.lower() == "bearer" else ""
    if not key:
        return None
    stamp = time.monotonic() if now is None else now
    found = _keys(hass).get(_digest(key))
    if found is None or found.expires < stamp:
        return None
    return found


def _prune(keys: OrderedDict[str, Caller], now: float) -> None:
    for digest in [digest for digest, item in keys.items() if item.expires < now]:
        keys.pop(digest, None)
