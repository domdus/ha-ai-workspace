"""Long-context prices, the 1-hour Claude cache, and usage of stopped or failed turns."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ai_workspace.usage_cost import (
    TokenUsage,
    estimate_cost,
    lookup_price,
    parse_usage,
    usage_payload,
)
from custom_components.ai_workspace.usage_record import finalize_usage


def _rates(model):
    name, rates = lookup_price(model)
    assert rates, model
    return rates


def test_a_long_request_is_priced_at_the_long_context_rate() -> None:
    rates = _rates("gemini-2.5-pro")
    assert rates["input_above_200k"] > rates["input"]
    short = estimate_cost(TokenUsage(prompt_tokens=150_000, completion_tokens=1_000), "gemini-2.5-pro")
    assert short.cost_usd == pytest.approx(150_000 * rates["input"] + 1_000 * rates["output"])
    long = estimate_cost(TokenUsage(prompt_tokens=250_000, completion_tokens=1_000), "gemini-2.5-pro")
    # The tier covers the whole request, output included.
    assert long.cost_usd == pytest.approx(250_000 * rates["input_above_200k"] + 1_000 * rates["output_above_200k"])


def test_tier_is_per_request_not_per_turn() -> None:
    # Two requests of 150k in one turn are two normal-price requests, not one 300k request.
    one = estimate_cost(TokenUsage(prompt_tokens=150_000), "gemini-2.5-pro")
    turn = one.add(one)
    assert estimate_cost(turn, "gemini-2.5-pro").cost_usd == pytest.approx(2 * one.cost_usd)
    # Read back from the usage event the chat records, the per-request estimate stays.
    again = finalize_usage(usage_payload(estimate_cost(turn, "gemini-2.5-pro")), model="gemini-2.5-pro")
    assert again.cost_usd == pytest.approx(2 * one.cost_usd)


def test_anthropic_input_counts_cached_tokens_for_the_tier() -> None:
    # Anthropic reports only uncached input in input_tokens; the tier is about all input.
    rates = {"input": 1.0, "output": 1.0, "cache_read": 0.1, "input_above_200k": 2.0, "cache_read_above_200k": 0.2}
    from custom_components.ai_workspace.usage_cost import input_tokens, tier_rates

    assert input_tokens(10_000, 195_000, 0) == 205_000
    assert input_tokens(205_000, 195_000, 0) == 205_000
    assert tier_rates(rates, 205_000)["cache_read"] == 0.2
    assert tier_rates(rates, 199_000) is rates


def test_one_hour_cache_writes_cost_twice_the_input_price() -> None:
    rates = _rates("claude-sonnet-4-5")
    usage = parse_usage(
        {
            "input_tokens": 50,
            "cache_creation_input_tokens": 10_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 2_000, "ephemeral_1h_input_tokens": 8_000},
            "cache_read_input_tokens": 0,
            "output_tokens": 100,
        },
        model="claude-sonnet-4-5",
    )
    assert usage.cache_write_tokens == 10_000 and usage.cache_write_1h_tokens == 8_000
    billed = estimate_cost(usage, "claude-sonnet-4-5")
    expected = (
        50 * rates["input"]
        + 2_000 * rates["cache_write"]
        + 8_000 * rates["cache_write_1h"]
        + 100 * rates["output"]
    )
    assert billed.cost_usd == pytest.approx(expected)
    assert rates["cache_write_1h"] == pytest.approx(2 * rates["input"])


def test_streamed_claude_usage_is_not_counted_twice() -> None:
    start = parse_usage({"input_tokens": 120, "cache_read_input_tokens": 9_000, "output_tokens": 1})
    # message_delta carries running totals and may repeat the input.
    delta = parse_usage({"input_tokens": 120, "cache_read_input_tokens": 9_000, "output_tokens": 340})
    merged = TokenUsage().update(start).update(delta)
    assert (merged.prompt_tokens, merged.cache_read_tokens, merged.completion_tokens) == (120, 9_000, 340)
    only_output = TokenUsage().update(start).update(parse_usage({"output_tokens": 340}))
    assert (only_output.prompt_tokens, only_output.completion_tokens) == (120, 340)


def _provider(provider="anthropic", **extra):
    from custom_components.ai_workspace.api_provider import ApiProvider
    from dataclasses import replace
    from test_force_tools import _settings

    return ApiProvider(None, replace(_settings(provider), **extra), None)


def test_one_hour_cache_marks_system_and_tools_only() -> None:
    payload = {"system": "rules", "tools": [{"name": "a"}, {"name": "b"}], "messages": []}
    marked = _provider(cache_1h=True)._apply_prompt_cache(dict(payload))
    assert marked["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert marked["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # The growing chat after them keeps the 5-minute cache.
    assert marked["cache_control"] == {"type": "ephemeral"}
    plain = _provider()._apply_prompt_cache(dict(payload))
    assert plain["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Only Claude agents use it.
    assert not _provider("openai", cache_1h=True)._cache_hour


def test_a_refused_one_hour_cache_falls_back_to_five_minutes() -> None:
    from custom_components.ai_workspace.api_provider import _strip_cache_ttl

    body = _provider(cache_1h=True)._apply_prompt_cache({"system": "rules", "tools": [{"name": "a"}]})
    assert _strip_cache_ttl(body)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert not _strip_cache_ttl(body)


def _turn(provider, error):
    """A turn whose first request finished and whose second one fails or is stopped."""

    async def loop(*_args, spent=None, **_kwargs):
        spent.usage = estimate_cost(TokenUsage(prompt_tokens=1_000, completion_tokens=50), "claude-sonnet-4-5")
        yield {"type": "tool", "name": "ha_get_state", "phase": "end"}
        raise error

    provider._anthropic = loop
    provider._http = lambda: None
    return provider.send(SimpleNamespace(id="chat"), "Ist das Licht an?", lambda _id: None, tools=False)


def test_a_failed_turn_still_reports_what_it_used() -> None:
    from custom_components.ai_workspace.api_provider import ApiError

    async def run():
        return [event async for event in _turn(_provider(), ApiError(500, "boom"))]

    events = asyncio.run(run())
    kinds = [event["type"] for event in events]
    assert kinds[-2:] == ["usage", "error"]
    assert events[-2]["prompt_tokens"] == 1_000 and events[-2]["cost_usd"] > 0


def test_a_stopped_turn_keeps_its_usage_for_the_chat_to_record() -> None:
    provider = _provider()

    async def run():
        with pytest.raises(asyncio.CancelledError):
            async for _event in _turn(provider, asyncio.CancelledError()):
                pass

    asyncio.run(run())
    left = provider.take_unbilled("chat")
    assert left is not None and left.prompt_tokens == 1_000
    assert provider.take_unbilled("chat") is None
