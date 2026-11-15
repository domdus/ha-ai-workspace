"""Claude fields that left the App options in 1.6.0b12: read the old values once more, quietly.

Up to 1.6.0b11 the App had claude_oauth_token, anthropic_api_key and claude_model. Since then
Claude signs in on the agent in Home Assistant (the Plan token lives in DATA_DIR/auth), and Docker
runtimes use CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY / CLAUDE_MODEL.

So nobody loses Claude on update:

* A Plan token in the old options moves into the sign-in once, when nobody signed in yet.
* An old Anthropic API key and Claude model keep working as a fallback, without a field.

The Supervisor writes /data/options.json through the App's schema on every start, so fields that
left the schema are no longer in that file. The App's stored options still have them, and an App
may read its own info (``/addons/self/info``) with the SUPERVISOR_TOKEN it always gets. Both
places are read; the file wins. Nothing here is ever logged except which fields were found.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import replace
from typing import Any

from app.settings import LEGACY_CLAUDE_OPTIONS, Settings

logger = logging.getLogger(__name__)

# One file per data folder: the old Plan token was handled, do not bring it back after a sign-out.
MOVED_MARKER = "claude-options-token-moved"
_SUPERVISOR = "http://supervisor"


def supervisor_options(timeout: float = 3.0) -> dict[str, Any]:
    """The App's stored options from the Supervisor, or {} outside Home Assistant OS or on any error."""
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        return {}
    base = (os.environ.get("SUPERVISOR_URL", "").strip() or _SUPERVISOR).rstrip("/")
    request = urllib.request.Request(
        f"{base}/addons/self/info",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 - fixed Supervisor URL
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:  # noqa: BLE001 - optional, a start must never fail here
        logger.debug("Supervisor App info not available: %s", type(exc).__name__)
        return {}
    data = body.get("data") if isinstance(body, dict) else None
    options = data.get("options") if isinstance(data, dict) else None
    return dict(options) if isinstance(options, dict) else {}


def _text(options: dict[str, Any], key: str) -> str:
    return str((options or {}).get(key) or "").strip()


def with_legacy_options(settings: Settings, stored: dict[str, Any] | None) -> Settings:
    """Fill what /data/options.json no longer carries from the App's stored options.

    Environment variables and the file come first (they are already in ``settings``).
    """
    stored = stored or {}
    changes: dict[str, Any] = {}
    found = list(settings.legacy_claude_options)
    for key, attr, current in (
        ("claude_oauth_token", "legacy_claude_token", settings.legacy_claude_token),
        ("anthropic_api_key", "anthropic_api_key", settings.anthropic_api_key),
        ("claude_model", "claude_model", settings.claude_model),
    ):
        value = _text(stored, key)
        if value and not current:
            changes[attr] = value
            if key not in found:
                found.append(key)
    if not changes:
        return settings
    ordered = tuple(key for key in LEGACY_CLAUDE_OPTIONS if key in found)
    return replace(settings, **changes, legacy_claude_options=ordered)


def move_legacy_token(settings: Settings) -> str:
    """Move the old options Plan token into the sign-in, once.

    Returns what happened: ``none`` (no old token), ``done`` (handled on an earlier start),
    ``moved``, ``kept`` (someone signed in already; that sign-in stays), ``invalid`` (not a Plan
    token) or ``failed`` (could not be saved).
    """
    from app.claude_login import LoginError, load_token, save_token

    token = (settings.legacy_claude_token or "").strip()
    if not token:
        return "none"
    marker = settings.claude_token_path.parent / MOVED_MARKER
    if marker.exists():
        return "done"
    if load_token(settings.claude_token_path):
        outcome = "kept"
    else:
        try:
            save_token(settings.claude_token_path, token)
        except LoginError:
            # Not an sk-ant-oat… token. Nothing to move; the agent form asks for a sign-in.
            outcome = "invalid"
        except OSError:
            return "failed"
        else:
            outcome = "moved"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(outcome + "\n", encoding="utf-8")
    except OSError:
        logger.debug("could not write %s", marker.name)
    return outcome


_TOKEN_NOTE = {
    "moved": "the Plan token now counts as a sign-in with Claude",
    "kept": "the Plan token was not needed; the existing sign-in with Claude stays",
    "invalid": "the Plan token is not a Claude Plan token (sk-ant-oat…) and was ignored",
    "failed": "the Plan token could not be saved; sign in with Claude on the agent",
}


def apply_legacy_options(settings: Settings, stored: dict[str, Any] | None = None) -> Settings:
    """Runtime start: merge the old options, move the Plan token, say so once in the log."""
    settings = with_legacy_options(settings, stored)
    found = list(settings.legacy_claude_options)
    if not found:
        return settings
    outcome = move_legacy_token(settings)
    notes = [_TOKEN_NOTE[outcome]] if outcome in _TOKEN_NOTE else []
    if "anthropic_api_key" in found:
        notes.append("the Anthropic API key is still used when nobody signed in")
    if "claude_model" in found:
        notes.append("the Claude model is still the default")
    logger.info(
        "Old Claude App options found (%s). The App no longer shows them: sign in with Claude on the agent "
        "in Home Assistant (Docker: CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY / CLAUDE_MODEL). %s.",
        ", ".join(found),
        _sentence("; ".join(notes)) or "Nothing else to do",
    )
    return settings



def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]
