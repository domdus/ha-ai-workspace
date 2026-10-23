#!/usr/bin/env python3
"""Refresh custom_components/ai_workspace/model_prices.json from LiteLLM.

LiteLLM keeps a community-maintained list of model prices:
https://github.com/BerriAI/litellm (model_prices_and_context_window.json, MIT).
We keep only the providers AI Workspace talks to and only the cost fields.

It also writes model_catalog.json: the chat model ids each provider offers, used
as suggestions in the agent forms when the provider's own list cannot be fetched.

Usage: python3 scripts/sync_model_prices.py [--catalog-only] [path-or-url]
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
OUT = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "model_prices.json"
CATALOG = OUT.with_name("model_catalog.json")

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


# LiteLLM provider -> AI Workspace provider whose model dropdown lists it.
CATALOG_PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "xai": "xai",
    "deepseek": "deepseek",
    "dashscope": "qwen",
    "openrouter": "openrouter",
    "ollama": "ollama",
}
# Dated snapshots and non-chat variants make the dropdowns noisy; they can still be typed in.
_SKIP = re.compile(
    r"(-\d{4}-\d{2}-\d{2}|-\d{8}|-\d{2}-\d{4}|-\d{4}|-\d{3})$"
    r"|audio|realtime|tts|transcribe|search|image|embed|moderation|computer-use|robotics"
    r"|deep-research|experimental|-exp|preview-\d|gv2|customtools|vision-exp|lyria|-\d{4}-"
)
# Kept as-is on regenerate: the Cursor SDK lists its own models (scripts cannot reach it without a key).
_KEEP = ("cursor",)


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


def _natural(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def build_catalog(raw: dict, previous: dict | None = None) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    for key, row in raw.items():
        if not isinstance(row, dict) or row.get("mode") not in CHAT_MODES:
            continue
        target = CATALOG_PROVIDERS.get(str(row.get("litellm_provider") or ""))
        if not target:
            continue
        name = key.strip()
        prefix = f"{row['litellm_provider']}/"
        if name.startswith(prefix):
            name = name[len(prefix):]
        if target != "openrouter":
            name = _name(name)
        if not name or _SKIP.search(name.lower()):
            continue
        found.setdefault(target, set()).add(name)
    out = {kind: sorted(names, key=_natural, reverse=True) for kind, names in sorted(found.items())}
    for kind in _KEEP:
        if previous and previous.get(kind):
            out[kind] = previous[kind]
    return dict(sorted(out.items()))


def dump_catalog(data: dict[str, list[str]]) -> str:
    lines = ["{"]
    items = list(data.items())
    for i, (kind, names) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"  {json.dumps(kind)}: {json.dumps(names)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


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
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    raw = _load(args[0] if args else SOURCE)
    previous = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else None
    catalog = build_catalog(raw, previous)
    CATALOG.write_text(dump_catalog(catalog), encoding="utf-8")
    print(f"Wrote {sum(len(v) for v in catalog.values())} model ids for {len(catalog)} providers to {CATALOG}")
    if "--catalog-only" in sys.argv:
        return 0
    data = build(raw)
    if len(data["models"]) < 100:
        print(f"Only {len(data['models'])} models found; refusing to overwrite.", file=sys.stderr)
        return 1
    OUT.write_text(dump(data), encoding="utf-8")
    print(f"Wrote {len(data['models'])} models and {len(data['speech'])} voices to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
