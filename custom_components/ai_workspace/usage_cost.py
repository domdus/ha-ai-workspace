"""Mini LiteLLM-style cost math: vendor prices + usage from provider replies.

Cursor billed cents win when the SDK reports them. Cloud agents use list prices
(per token) plus cache/reasoning when those fields exist. Unknown models still
record tokens with cost left empty.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

SIGNAL_USAGE_UPDATE = "ai_workspace_usage_update"
EVENT_USAGE = "ai_workspace_usage"

# USD per token. Keep aliases so dated / vendor-prefixed ids still match.
# Figures are public list prices (approximate, 2026). Cursor values are estimates
# unless charged_cents is present on the turn.
_PRICES: dict[str, dict[str, float]] = {
    # Cursor (estimate until SDK billed cents arrive)
    "composer-2.5": {"input": 1.25e-6, "output": 6.0e-6, "cache_read": 1.25e-7},
    "composer-2": {"input": 1.25e-6, "output": 6.0e-6, "cache_read": 1.25e-7},
    "composer-1.5": {"input": 1.25e-6, "output": 6.0e-6, "cache_read": 1.25e-7},
    "cursor-small": {"input": 1.5e-7, "output": 6.0e-7},
    # OpenAI
    "gpt-5": {"input": 1.25e-6, "output": 1.0e-5, "cache_read": 1.25e-7},
    "gpt-5-mini": {"input": 2.5e-7, "output": 2.0e-6, "cache_read": 2.5e-8},
    "gpt-5-nano": {"input": 5.0e-8, "output": 4.0e-7, "cache_read": 5.0e-9},
    "gpt-4.1": {"input": 2.0e-6, "output": 8.0e-6, "cache_read": 5.0e-7},
    "gpt-4.1-mini": {"input": 4.0e-7, "output": 1.6e-6, "cache_read": 1.0e-7},
    "gpt-4.1-nano": {"input": 1.0e-7, "output": 4.0e-7, "cache_read": 2.5e-8},
    "gpt-4o": {"input": 2.5e-6, "output": 1.0e-5, "cache_read": 1.25e-6},
    "gpt-4o-mini": {"input": 1.5e-7, "output": 6.0e-7, "cache_read": 7.5e-8},
    "o3": {"input": 2.0e-6, "output": 8.0e-6, "cache_read": 5.0e-7},
    "o3-mini": {"input": 1.1e-6, "output": 4.4e-6, "cache_read": 5.5e-7},
    "o4-mini": {"input": 1.1e-6, "output": 4.4e-6, "cache_read": 2.75e-7},
    "gpt-6-astra": {"input": 1.25e-6, "output": 1.0e-5, "cache_read": 1.25e-7},
    "gpt-6.1-sol": {"input": 1.25e-6, "output": 1.0e-5, "cache_read": 1.25e-7},
    # Anthropic
    "claude-opus-4": {"input": 1.5e-5, "output": 7.5e-5, "cache_read": 1.5e-6, "cache_write": 1.875e-5},
    "claude-opus-4-1": {"input": 1.5e-5, "output": 7.5e-5, "cache_read": 1.5e-6, "cache_write": 1.875e-5},
    "claude-opus-4-5": {"input": 5.0e-6, "output": 2.5e-5, "cache_read": 5.0e-7, "cache_write": 6.25e-6},
    "claude-opus-5-5": {"input": 5.0e-6, "output": 2.5e-5, "cache_read": 5.0e-7, "cache_write": 6.25e-6},
    "claude-sonnet-4": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 3.0e-7, "cache_write": 3.75e-6},
    "claude-sonnet-4-5": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 3.0e-7, "cache_write": 3.75e-6},
    "claude-sonnet-5-5": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 3.0e-7, "cache_write": 3.75e-6},
    "claude-haiku-4-5": {"input": 8.0e-7, "output": 4.0e-6, "cache_read": 8.0e-8, "cache_write": 1.0e-6},
    "claude-haiku-5-5": {"input": 8.0e-7, "output": 4.0e-6, "cache_read": 8.0e-8, "cache_write": 1.0e-6},
    "claude-3-5-sonnet": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 3.0e-7, "cache_write": 3.75e-6},
    "claude-3-5-haiku": {"input": 8.0e-7, "output": 4.0e-6, "cache_read": 8.0e-8, "cache_write": 1.0e-6},
    "claude-3-opus": {"input": 1.5e-5, "output": 7.5e-5, "cache_read": 1.5e-6, "cache_write": 1.875e-5},
    "claude-3-haiku": {"input": 2.5e-7, "output": 1.25e-6, "cache_read": 3.0e-8, "cache_write": 3.0e-7},
    # Google
    "gemini-2.5-pro": {"input": 1.25e-6, "output": 1.0e-5, "cache_read": 3.125e-7},
    "gemini-2.5-flash": {"input": 3.0e-7, "output": 2.5e-6, "cache_read": 7.5e-8},
    "gemini-2.0-flash": {"input": 1.0e-7, "output": 4.0e-7, "cache_read": 2.5e-8},
    "gemini-2.0-flash-lite": {"input": 7.5e-8, "output": 3.0e-7},
    "gemini-1.5-pro": {"input": 1.25e-6, "output": 5.0e-6},
    "gemini-1.5-flash": {"input": 7.5e-8, "output": 3.0e-7},
    "gemini-3.8-flash": {"input": 3.0e-7, "output": 2.5e-6, "cache_read": 7.5e-8},
    # DeepSeek
    "deepseek-chat": {"input": 2.7e-7, "output": 1.1e-6, "cache_read": 2.7e-8},
    "deepseek-reasoner": {"input": 5.5e-7, "output": 2.19e-6, "cache_read": 1.4e-7},
    "deepseek-v3": {"input": 2.7e-7, "output": 1.1e-6, "cache_read": 2.7e-8},
    "deepseek-flash": {"input": 1.4e-7, "output": 2.8e-7, "cache_read": 1.4e-8},
    "deepseek-v4-pro": {"input": 5.5e-7, "output": 2.19e-6, "cache_read": 1.4e-7},
    # Qwen / Alibaba
    "qwen-plus": {"input": 4.0e-7, "output": 1.2e-6, "cache_read": 1.0e-7},
    "qwen-turbo": {"input": 5.0e-8, "output": 2.0e-7},
    "qwen-max": {"input": 1.6e-6, "output": 6.4e-6},
    "qwen3-plus": {"input": 4.0e-7, "output": 1.2e-6, "cache_read": 1.0e-7},
    "qwen3.7-plus": {"input": 4.0e-7, "output": 1.2e-6, "cache_read": 1.0e-7},
    "qwen3.8-max": {"input": 1.6e-6, "output": 6.4e-6},
    "qwen3.8-flash": {"input": 5.0e-8, "output": 2.0e-7},
    "qwen2.5": {"input": 4.0e-7, "output": 1.2e-6},
    # xAI
    "grok-4": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 7.5e-7},
    "grok-4.3": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 7.5e-7},
    "grok-4.7": {"input": 3.0e-6, "output": 1.5e-5, "cache_read": 7.5e-7},
    "grok-3": {"input": 3.0e-6, "output": 1.5e-5},
    "grok-3-mini": {"input": 3.0e-7, "output": 5.0e-7},
    "grok-2": {"input": 2.0e-6, "output": 1.0e-5},
    "grok-2-vision": {"input": 2.0e-6, "output": 1.0e-5},
    # Local
    "llama3.2": {"input": 0.0, "output": 0.0},
    "llama3.1": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "gemma3": {"input": 0.0, "output": 0.0},
}

_ALIASES = {
    "gpt-5-chat-latest": "gpt-5",
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "claude-3-5-sonnet-latest": "claude-3-5-sonnet",
    "claude-3-5-haiku-latest": "claude-3-5-haiku",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
    "deepseek-chat-v3": "deepseek-chat",
    "qwen2.5:latest": "qwen2.5",
    "llama3.2:latest": "llama3.2",
}


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    charged_cents: int | None = None
    cost_source: str = ""
    model: str = ""
    run_id: str = ""

    def add(self, other: "TokenUsage") -> "TokenUsage":
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        cents = None
        if self.charged_cents is not None or other.charged_cents is not None:
            cents = (self.charged_cents or 0) + (other.charged_cents or 0)
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost_usd=cost,
            charged_cents=cents,
            cost_source=other.cost_source or self.cost_source,
            model=other.model or self.model,
            run_id=other.run_id or self.run_id,
        )

    def empty(self) -> bool:
        return not (
            self.prompt_tokens
            or self.completion_tokens
            or self.total_tokens
            or self.cache_read_tokens
            or self.cache_write_tokens
            or self.charged_cents
            or (self.cost_usd is not None and self.cost_usd != 0)
        )


def _int(value: object) -> int:
    try:
        if value is None or value is False:
            return 0
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float | None:
    try:
        if value is None or value is False:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
        "cachedContentTokenCount",
        "thoughtsTokenCount",
        "prompt_tokens_details",
        "completion_tokens_details",
        "input_tokens_details",
        "output_tokens_details",
        "usageMetadata",
        "usage",
        "cost",
        "total_cost",
        "charged_cents",
        "total_cents",
        "model",
        "run_id",
    ):
        if hasattr(value, name):
            out[name] = getattr(value, name)
    return out


def normalize_model(name: str) -> str:
    text = str(name or "").strip().lower()
    if not text:
        return ""
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if ":" in text and not text.startswith("gpt"):
        text = text.split(":", 1)[0]
    return text


def lookup_price(model: str) -> tuple[str, dict[str, float] | None]:
    raw = normalize_model(model)
    if not raw:
        return "", None
    key = _ALIASES.get(raw, raw)
    if key in _PRICES:
        return key, _PRICES[key]
    best = ""
    for candidate in _PRICES:
        if key.startswith(candidate) and len(candidate) > len(best):
            best = candidate
    if best:
        return best, _PRICES[best]
    parts = key.split("-")
    while len(parts) > 2:
        parts.pop()
        guess = "-".join(parts)
        if guess in _PRICES:
            return guess, _PRICES[guess]
    return key, None


def parse_usage(blob: object, *, model: str = "", run_id: str = "") -> TokenUsage:
    data = _as_dict(blob)
    nested = data.get("usage") or data.get("usageMetadata")
    if isinstance(nested, dict) or nested is not None:
        inner = _as_dict(nested)
        if inner:
            data = {**inner, **{k: v for k, v in data.items() if k not in inner}}
    details_in = _as_dict(data.get("prompt_tokens_details") or data.get("input_tokens_details"))
    details_out = _as_dict(data.get("completion_tokens_details") or data.get("output_tokens_details"))
    prompt = _int(
        data.get("prompt_tokens")
        or data.get("input_tokens")
        or data.get("promptTokenCount")
        or data.get("inputTokenCount")
    )
    completion = _int(
        data.get("completion_tokens")
        or data.get("output_tokens")
        or data.get("candidatesTokenCount")
        or data.get("outputTokenCount")
    )
    cache_read = _int(
        data.get("cache_read_tokens")
        or data.get("cache_read_input_tokens")
        or data.get("cachedContentTokenCount")
        or details_in.get("cached_tokens")
        or details_in.get("cache_read")
    )
    cache_write = _int(
        data.get("cache_write_tokens")
        or data.get("cache_creation_input_tokens")
        or details_in.get("cache_write")
        or details_in.get("cache_creation")
    )
    reasoning = _int(
        data.get("reasoning_tokens")
        or data.get("thoughtsTokenCount")
        or details_out.get("reasoning_tokens")
    )
    total = _int(data.get("total_tokens") or data.get("totalTokenCount"))
    if not total:
        total = prompt + completion
    cost = _float(data.get("cost") if data.get("cost") is not None else data.get("total_cost"))
    cents = data.get("charged_cents")
    if cents is None:
        cents = data.get("total_cents")
    charged = _int(cents) if cents is not None else None
    if charged == 0 and cents is None:
        charged = None
    source = ""
    if charged is not None:
        source = "cursor_sdk"
        cost = charged / 100.0
    elif cost is not None:
        source = "provider"
    used_model = str(data.get("model") or model or "").strip()
    used_run = str(data.get("run_id") or run_id or "").strip()
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
        total_tokens=total,
        cost_usd=cost,
        charged_cents=charged,
        cost_source=source,
        model=used_model,
        run_id=used_run,
    )


def estimate_cost(usage: TokenUsage, model: str = "") -> TokenUsage:
    if usage.charged_cents is not None:
        return replace(usage, cost_usd=usage.charged_cents / 100.0, cost_source="cursor_sdk")
    if usage.cost_usd is not None and usage.cost_source == "provider":
        return usage
    name, rates = lookup_price(model or usage.model)
    out = replace(usage, model=usage.model or name)
    if not rates:
        return out
    billed_prompt = max(0, out.prompt_tokens - out.cache_read_tokens - out.cache_write_tokens)
    cost = billed_prompt * rates.get("input", 0.0)
    cost += out.cache_read_tokens * rates.get("cache_read", rates.get("input", 0.0) * 0.1)
    cost += out.cache_write_tokens * rates.get("cache_write", rates.get("input", 0.0) * 1.25)
    output_tokens = out.completion_tokens
    # Some providers already fold reasoning into completion_tokens.
    if out.reasoning_tokens and out.reasoning_tokens > out.completion_tokens:
        output_tokens = out.reasoning_tokens
    cost += output_tokens * rates.get("output", 0.0)
    return replace(out, cost_usd=round(cost, 8), cost_source="estimate")


def usage_payload(usage: TokenUsage) -> dict[str, Any]:
    return {
        "type": "usage",
        "model": usage.model,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens),
        "cost_usd": usage.cost_usd,
        "cost_source": usage.cost_source,
        "charged_cents": usage.charged_cents,
        "run_id": usage.run_id,
    }


def empty_summary() -> dict[str, Any]:
    return {
        "turns": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "missing_cost": False,
    }
