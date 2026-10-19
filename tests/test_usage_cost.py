from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "custom_components" / "ai_workspace" / "usage_cost.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_usage_cost", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load()


def test_openai_usage_and_gpt5_mini_not_gpt5():
    usage = mod.parse_usage(
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 100}}}
    )
    billed = mod.estimate_cost(usage, "gpt-5-mini")
    key, rates = mod.lookup_price("gpt-5-mini-2025-08-07")
    assert key == "gpt-5-mini"
    assert billed.cost_source == "estimate"
    assert billed.cost_usd is not None
    assert billed.cost_usd == (900 * rates["input"]) + (100 * rates["cache_read"]) + (200 * rates["output"])


def test_anthropic_cache_and_cursor_cents():
    claude = mod.parse_usage(
        {
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 5,
            }
        },
        model="claude-sonnet-4-5-20250929",
    )
    billed = mod.estimate_cost(claude, "claude-sonnet-4-5-20250929")
    assert billed.cache_read_tokens == 20
    assert billed.cost_usd and billed.cost_usd > 0
    cursor = mod.parse_usage({"charged_cents": 37, "input_tokens": 10, "output_tokens": 4})
    billed = mod.estimate_cost(cursor, "composer-2.5")
    assert billed.cost_source == "cursor_sdk"
    assert billed.cost_usd == 0.37


def test_provider_reported_cost_and_ollama_zero():
    openrouter = mod.parse_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0123}})
    billed = mod.estimate_cost(openrouter, "openai/gpt-5")
    assert billed.cost_source == "provider"
    assert billed.cost_usd == 0.0123
    local = mod.estimate_cost(mod.parse_usage({"prompt_tokens": 8, "completion_tokens": 3}), "llama3.2")
    assert local.cost_usd == 0.0


def test_unknown_model_keeps_tokens_without_price():
    usage = mod.estimate_cost(mod.parse_usage({"prompt_tokens": 12, "completion_tokens": 3}), "mystery-model-9")
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 3
    assert usage.cost_usd is None
    assert usage.cost_source == ""


def test_openrouter_prefix_and_longest_match():
    key, rates = mod.lookup_price("openai/gpt-5-mini")
    assert key == "gpt-5-mini"
    assert rates is not None
    key, _rates = mod.lookup_price("gpt-5")
    assert key == "gpt-5"


def test_tts_uses_character_prices_not_chat_tokens():
    billed = mod.estimate_tts_cost("Hello world", "gpt-4o-mini-tts")
    assert billed.characters == 11
    assert billed.prompt_tokens == 0
    assert billed.total_tokens == 0
    assert billed.cost_source == "estimate"
    assert billed.cost_usd == round(11 * (0.60 / 1_000_000), 8)
    key, rates = mod.lookup_speech_price("openai/gpt-4o-mini-tts")
    assert key == "gpt-4o-mini-tts"
    assert rates is not None
    hd = mod.estimate_tts_cost("ab", "tts-1-hd")
    std = mod.estimate_tts_cost("ab", "tts-1")
    assert hd.cost_usd == round(2 * (30.0 / 1_000_000), 8)
    assert std.cost_usd == round(2 * (15.0 / 1_000_000), 8)
    assert hd.cost_usd > std.cost_usd
    unknown = mod.estimate_tts_cost("hello", "piper-voice")
    assert unknown.characters == 5
    assert unknown.cost_usd is None
