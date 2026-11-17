"""Read a Claude plan's current utilization without spending quota.

Claude Code's ``/usage`` reads ``GET https://api.anthropic.com/api/oauth/usage`` with the plan's OAuth
token (header ``anthropic-beta: oauth-2025-04-20``). The answer carries the 5-hour ("session") and
7-day ("week") utilization in percent and their reset times. It is not a model call: no tokens, no
plan quota.

The chat itself already brings the same numbers: Claude Code sends a ``rate_limit_event`` (with
``unifiedWindows``) after the first API answer of each turn and whenever a rounded percent changes.
This reader only fills the gap when a turn brought none, at most every ``MIN_INTERVAL`` seconds.
Tokens from ``claude setup-token`` may lack the scope the endpoint wants (401/403); then the reader
backs off for ``BACKOFF`` seconds and the Usage page keeps what the chat reported.

Set ``CLAUDE_PLAN_USAGE_READ=off`` on the Runtime to never call the endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from app.plan_quota import normalize_oauth_usage

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
MIN_INTERVAL = 600.0
BACKOFF = 6 * 3600.0
TIMEOUT = 5.0


def reading_enabled() -> bool:
    return (os.environ.get("CLAUDE_PLAN_USAGE_READ") or "on").strip().lower() not in {"0", "off", "false", "no"}


def _get(token: str) -> tuple[int, Any]:
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA,
            "Content-Type": "application/json",
            "User-Agent": "ha-ai-workspace",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - fixed https URL
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, None


class ClaudeUsageReader:
    """Throttled reads of /api/oauth/usage; one per Runtime."""

    def __init__(self, getter=_get, clock=time.monotonic) -> None:
        self._get = getter
        self._clock = clock
        self._next_at = 0.0
        self._task: asyncio.Task | None = None
        self.last_error = ""

    def due(self) -> bool:
        if not reading_enabled():
            return False
        if self._task is not None and not self._task.done():
            return False
        return self._clock() >= self._next_at

    async def read(self, token: str) -> dict[str, Any] | None:
        """One read: a snapshot, or None (and the next read waits longer)."""
        self._next_at = self._clock() + MIN_INTERVAL
        try:
            status, body = await asyncio.to_thread(self._get, token)
        except (OSError, ValueError, TimeoutError) as exc:
            self.last_error = type(exc).__name__
            logger.debug("claude plan usage read failed: %s", self.last_error)
            return None
        if status != 200:
            self.last_error = f"http {status}"
            if status in {401, 403, 404}:
                self._next_at = self._clock() + BACKOFF
                logger.info(
                    "Claude plan usage is not readable with this credential (HTTP %s); the Usage page "
                    "shows what the chat reports instead. Next try in %d h.",
                    status,
                    int(BACKOFF // 3600),
                )
            return None
        self.last_error = ""
        return normalize_oauth_usage(body if isinstance(body, dict) else {})

    def refresh_in_background(self, book, token: str) -> None:
        """Start a read that stores its snapshot under ``claude`` in ``book``."""
        if not self.due():
            return

        async def run() -> None:
            snap = await self.read(token)
            if snap:
                book.apply("claude", snap)

        try:
            self._task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            self._task = None
