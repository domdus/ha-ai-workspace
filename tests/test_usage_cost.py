from pathlib import Path
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load(ROOT / "custom_components" / "ai_workspace" / "usage_cost.py", "ai_workspace_usage_cost")
sync = _load(ROOT / "scripts" / "sync_model_prices.py", "ai_workspace_sync_model_prices")


def test_price_file_is_loaded_and_extras_fill_gaps():
    assert len(mod._SYNCED_PRICES) > 100
    assert mod.lookup_price("gpt-5")[1] == mod._SYNCED_PRICES["gpt-5"]
    assert mod.lookup_price("composer-2.5")[1] == mod._EXTRA_PRICES["composer-2.5"]
    assert mod.lookup_price("gemma3:latest")[1] == {"input": 0.0, "output": 0.0}


def test_openrouter_dotted_claude_name():
    key, rates = mod.lookup_price("anthropic/claude-sonnet-4.5")
    assert key == "claude-sonnet-4-5"
    assert rates and rates["cache_write"] > rates["input"]


def test_sync_keeps_our_providers_and_cost_fields_only():
    raw = {
        "gpt-x": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 1e-6,
                  "output_cost_per_token": 2e-6, "max_tokens": 9},
        "azure/gpt-x": {"litellm_provider": "azure", "mode": "chat", "input_cost_per_token": 9e-6,
                        "output_cost_per_token": 9e-6},
        "dashscope/deepseek-y": {"litellm_provider": "dashscope", "mode": "chat", "input_cost_per_token": 5e-6,
                                 "output_cost_per_token": 5e-6},
        "deepseek/deepseek-y": {"litellm_provider": "deepseek", "mode": "chat", "input_cost_per_token": 1e-7,
                                "output_cost_per_token": 2e-7, "cache_read_input_token_cost": 1e-8},
        "text-embed": {"litellm_provider": "openai", "mode": "embedding", "input_cost_per_token": 1e-8},
        "tts-z": {"litellm_provider": "openai", "mode": "audio_speech", "input_cost_per_character": 1.5e-5},
        "speech-s": {"litellm_provider": "openai", "mode": "audio_speech", "output_cost_per_second": 0.00015},
    }
    data = sync.build(raw)
    assert data["models"] == {
        "deepseek-y": {"input": 1e-7, "output": 2e-7, "cache_read": 1e-8},
        "gpt-x": {"input": 1e-6, "output": 2e-6},
    }
    assert data["speech"] == {"speech-s": {"character": 1e-5}, "tts-z": {"character": 1.5e-5}}
    assert json.loads(sync.dump(data)) == data


def test_openai_usage_and_gpt5_mini_not_gpt5():
    usage = mod.parse_usage(
        {"usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 100}}}
    )
    billed = mod.estimate_cost(usage, "gpt-5-mini")
    _key, dated = mod.lookup_price("gpt-5-mini-2025-08-07")
    _key, rates = mod.lookup_price("gpt-5-mini")
    assert dated == rates != mod.lookup_price("gpt-5")[1]
    assert billed.cost_source == "estimate"
    assert billed.cost_usd is not None
    assert billed.cost_usd == (900 * rates["input"]) + (100 * rates["cache_read"]) + (200 * rates["output"])


def test_claude_exclusive_cache_tokens_match_list_price():
    usage = mod.parse_usage(
        {
            "usage": {
                "input_tokens": 36,
                "output_tokens": 2987,
                "cache_read_input_tokens": 280912,
                "cache_creation_input_tokens": 73502,
            }
        },
        model="claude-sonnet-5-5",
    )
    billed = mod.estimate_cost(usage, "claude-sonnet-5-5")
    _key, rates = mod.lookup_price("claude-sonnet-5-5")
    assert billed.total_tokens == 36 + 280912 + 73502 + 2987
    assert billed.cost_usd == round(
        36 * rates["input"]
        + 280912 * rates["cache_read"]
        + 73502 * rates["cache_write"]
        + 2987 * rates["output"],
        8,
    )
    payload = mod.usage_payload(billed)
    assert payload["total_tokens"] == billed.total_tokens
    inclusive = mod.parse_usage(
        {
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 5,
            }
        }
    )
    assert inclusive.total_tokens == 60
    assert mod.uncached_prompt_tokens(50, 20, 5) == 25
    assert mod.uncached_prompt_tokens(36, 280912, 73502) == 36


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
    key, rates = mod.lookup_speech_price("openai/gpt-4o-mini-tts")
    assert key == "gpt-4o-mini-tts"
    assert rates is not None
    assert billed.cost_usd == round(11 * rates["character"], 8)
    assert 1e-5 < rates["character"] < 3e-5
    hd = mod.estimate_tts_cost("ab", "tts-1-hd")
    std = mod.estimate_tts_cost("ab", "tts-1")
    assert hd.cost_usd == round(2 * (30.0 / 1_000_000), 8)
    assert std.cost_usd == round(2 * (15.0 / 1_000_000), 8)
    assert hd.cost_usd > std.cost_usd
    unknown = mod.estimate_tts_cost("hello", "piper-voice")
    assert unknown.characters == 5
    assert unknown.cost_usd is None
    gemini = mod.estimate_cost(
        mod.parse_usage({"promptTokenCount": 8, "candidatesTokenCount": 40, "totalTokenCount": 48}),
        "gemini-3.8-flash-tts",
    )
    assert gemini.prompt_tokens == 8
    assert gemini.completion_tokens == 40
    assert gemini.cost_usd is not None
    flash = mod.lookup_price("gemini-2.5-flash")
    tts = mod.lookup_price("gemini-3.8-flash-tts")
    assert tts[1] is not None
    assert flash[0] != tts[0]
