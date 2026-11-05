"""A running reply can be followed again after the page reloads."""

import asyncio
from types import SimpleNamespace

from custom_components.ai_workspace.live_turn import LiveTurn, end_turn, live_turn, start_turn


def test_follower_gets_everything_so_far_then_the_rest() -> None:
    async def run():
        turn = LiveTurn()
        turn.publish({"type": "status", "text": "Working"})
        turn.publish({"type": "text", "delta": "Ich "})
        turn.publish({"type": "text", "delta": "prüfe."})
        turn.publish({"type": "usage", "prompt_tokens": 5})
        turn.publish({"type": "tool", "name": "ha_get_state", "phase": "start", "text": "Calling"})
        so_far, queue = turn.follow()
        turn.publish({"type": "text", "delta": " Fertig."})
        turn.publish({"type": "done", "answer": "Ich prüfe. Fertig."})
        turn.finish()
        later = []
        while (item := await queue.get()) is not None:
            later.append(item)
        return so_far, later

    so_far, later = asyncio.run(run())
    # Text pieces are joined, usage is left out.
    assert so_far == [
        {"type": "status", "text": "Working"},
        {"type": "text", "delta": "Ich prüfe."},
        {"type": "tool", "name": "ha_get_state", "phase": "start", "text": "Calling"},
    ]
    assert [item["type"] for item in later] == ["text", "done"]


def test_finished_turn_ends_followers_and_ignores_more_events() -> None:
    async def run():
        turn = LiveTurn()
        turn.publish({"type": "text", "delta": "a"})
        turn.finish()
        turn.publish({"type": "text", "delta": "b"})
        so_far, queue = turn.follow()
        return so_far, await queue.get()

    so_far, end = asyncio.run(run())
    assert so_far == [{"type": "text", "delta": "a"}]
    assert end is None


def test_slow_follower_is_dropped_instead_of_growing_forever() -> None:
    async def run():
        turn = LiveTurn()
        _, queue = turn.follow()
        for index in range(2100):
            turn.publish({"type": "tool", "name": f"t{index}", "text": "x"})
        items = []
        while (item := queue.get_nowait()) is not None:
            items.append(item)
        return len(items), len(turn._followers)

    count, followers = asyncio.run(run())
    assert count == 2000
    assert followers == 0


def test_registry_keeps_only_the_running_turn() -> None:
    hass = SimpleNamespace(data={})
    first = start_turn(hass, "chat")
    assert live_turn(hass, "chat") is first
    second = start_turn(hass, "chat")
    assert first.done and live_turn(hass, "chat") is second
    # Ending an old turn does not remove the new one.
    end_turn(hass, "chat", first)
    assert live_turn(hass, "chat") is second
    end_turn(hass, "chat", second)
    assert live_turn(hass, "chat") is None
