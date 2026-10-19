#!/usr/bin/env python3
"""Refresh custom_components/ai_workspace/model_prices.json from LiteLLM.

LiteLLM keeps a community-maintained list of model prices:
https://github.com/BerriAI/litellm (model_prices_and_context_window.json, MIT).
We keep only the providers AI Workspace talks to and only the cost fields.

Usage: python3 scripts/sync_model_prices.py [path-or-url]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
OUT = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "model_prices.json"

# First provider wins when two list the same model name.
PROVIDERS = ("openai", "anthropic", "gemini", "xai", "deepseek", "dashscope", "mistral")
CHAT_MODES = {"chat", "responses"}
FIELDS = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_write": "cache_creation_input_token_cost",
}
# Speech priced per second is turned into per character (about 15 spoken characters per second).
CHARS_PER_SECOND = 15
CHARS_PER_TOKEN = 4


def _load(where: str) -> dict:
    if where.startswith("http"):
        with urllib.request.urlopen(where, timeout=60) as resp:
            return json.load(resp)
    return json.loads(Path(where).read_text(encoding="utf-8"))


def _name(key: str) -> str:
    return key.rsplit("/", 1)[-1].strip().lower()


def _num(value: object) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _speech_rate(row: dict) -> float | None:
    per_char = _num(row.get("input_cost_per_character"))
    if per_char is not None:
        return per_char
    per_second = _num(row.get("output_cost_per_second"))
    if per_second is None:
        return None
    per_token = _num(row.get("input_cost_per_token")) or 0.0
    return per_second / CHARS_PER_SECOND + per_token / CHARS_PER_TOKEN


def build(raw: dict) -> dict:
    rank = {p: i for i, p in enumerate(PROVIDERS)}
    rows = [
        (rank[row["litellm_provider"]], "/" in key, key, row)
        for key, row in raw.items()
        if isinstance(row, dict) and row.get("litellm_provider") in rank
    ]
    models: dict[str, dict[str, float]] = {}
    speech: dict[str, dict[str, float]] = {}
    for _rank, _prefixed, key, row in sorted(rows):
        name = _name(key)
        mode = row.get("mode")
        if mode in CHAT_MODES and name not in models:
            price = {short: _num(row.get(field)) for short, field in FIELDS.items()}
            if price["input"] is None or price["output"] is None:
                continue
            models[name] = {k: v for k, v in price.items() if v is not None}
        elif mode == "audio_speech" and name not in speech:
            rate = _speech_rate(row)
            if rate is not None:
                speech[name] = {"character": round(rate, 12)}
    return {"source": SOURCE, "models": dict(sorted(models.items())), "speech": dict(sorted(speech.items()))}


def dump(data: dict) -> str:
    lines = ["{", f'  "source": {json.dumps(data["source"])},']
    for section in ("models", "speech"):
        items = list(data[section].items())
        lines.append(f'  "{section}": {{')
        for i, (name, price) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            lines.append(f"    {json.dumps(name)}: {json.dumps(price, sort_keys=True)}{comma}")
        lines.append("  }," if section == "models" else "  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    data = build(_load(sys.argv[1] if len(sys.argv) > 1 else SOURCE))
    if len(data["models"]) < 100:
        print(f"Only {len(data['models'])} models found; refusing to overwrite.", file=sys.stderr)
        return 1
    OUT.write_text(dump(data), encoding="utf-8")
    print(f"Wrote {len(data['models'])} models and {len(data['speech'])} voices to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
