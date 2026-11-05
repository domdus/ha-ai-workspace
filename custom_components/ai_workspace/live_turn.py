"""A running chat reply that a reloaded page can pick up again.

The reply runs in Home Assistant, not in the browser, so it keeps going when the page
reloads. Every event the chat sends is also kept here until the reply ends: a page that
comes back gets everything so far and then the rest as it happens.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .const import DOMAIN

_STORE = f"{DOMAIN}_live_turns"
# Events a follower does not need: usage is shown from the stored message, titles after the end.
_SKIP = frozenset({"usage"})
# A page that stops reading must not hold memory forever.
_QUEUE_MAX = 2000


class LiveTurn:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.done = False
        self._followers: set[asyncio.Queue] = set()

    def publish(self, event: dict[str, Any]) -> None:
        if self.done or str(event.get("type")) in _SKIP:
            return
        last = self.events[-1] if self.events else None
        if event.get("type") == "text" and last is not None and last.get("type") == "text":
            # One growing text event instead of thousands of small ones.
            self.events[-1] = {"type": "text", "delta": f"{last.get('delta') or ''}{event.get('delta') or ''}"}
        else:
            self.events.append(dict(event))
        for queue in list(self._followers):
            if queue.qsize() >= _QUEUE_MAX:
                self._followers.discard(queue)
                queue.put_nowait(None)
                continue
            queue.put_nowait(dict(event))

    def follow(self) -> tuple[list[dict[str, Any]], asyncio.Queue]:
        """Everything so far, and a queue with what comes next. None in the queue means the end."""
        queue: asyncio.Queue = asyncio.Queue()
        if self.done:
            queue.put_nowait(None)
        else:
            self._followers.add(queue)
        return [dict(item) for item in self.events], queue

    def unfollow(self, queue: asyncio.Queue) -> None:
        self._followers.discard(queue)

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        for queue in list(self._followers):
            queue.put_nowait(None)
        self._followers.clear()


def _turns(hass) -> dict[str, LiveTurn]:
    return hass.data.setdefault(_STORE, {})


def start_turn(hass, session_id: str) -> LiveTurn:
    turn = LiveTurn()
    old = _turns(hass).get(session_id)
    if old is not None:
        old.finish()
    _turns(hass)[session_id] = turn
    return turn


def end_turn(hass, session_id: str, turn: LiveTurn) -> None:
    turn.finish()
    if _turns(hass).get(session_id) is turn:
        _turns(hass).pop(session_id, None)


def live_turn(hass, session_id: str) -> LiveTurn | None:
    turn = _turns(hass).get(session_id)
    return None if turn is None or turn.done else turn
