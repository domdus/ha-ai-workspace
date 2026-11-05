"""What Ollama says about a model: whether it can use tools, and how much text it can read.

Ollama's OpenAI-style endpoint quietly cuts a prompt that is longer than the context window
it runs the model with, so a request with Home Assistant tools can reach a small window
half-read. Its native API tells us both numbers up front.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from aiohttp import ClientError, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_CACHE = f"{DOMAIN}_ollama_info"
_SHOW_TTL = 600.0
_PS_TTL = 60.0
# Below this, the system prompt and a starter tool set do not fit.
MIN_TOOL_WINDOW = 8_192


@dataclass(frozen=True)
class OllamaModel:
    tools: bool | None = None
    trained: int | None = None
    running: int | None = None

    @property
    def window(self) -> int | None:
        """What the model reads right now if it is loaded, else what it was trained for."""
        return self.running or self.trained


def native_root(base: str) -> str:
    root = str(base or "").strip().rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


def _same_model(name: str, wanted: str) -> bool:
    name, wanted = name.strip(), wanted.strip()
    if ":" not in wanted:
        wanted = f"{wanted}:latest"
    if ":" not in name:
        name = f"{name}:latest"
    return name == wanted


def parse_show(body: object) -> tuple[bool | None, int | None]:
    if not isinstance(body, dict):
        return None, None
    caps = body.get("capabilities")
    tools = ("tools" in caps) if isinstance(caps, list) else None
    trained = None
    info = body.get("model_info")
    if isinstance(info, dict):
        for key, value in info.items():
            if str(key).endswith(".context_length") and isinstance(value, int) and value > 0:
                trained = value
                break
    return tools, trained


def parse_ps(body: object, model: str) -> int | None:
    rows = body.get("models") if isinstance(body, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if _same_model(str(row.get("name") or row.get("model") or ""), model):
            size = row.get("context_length")
            return size if isinstance(size, int) and size > 0 else None
    return None


async def async_ollama_model(hass: HomeAssistant, base: str, model: str) -> OllamaModel:
    """Never raises; unknown parts stay None so callers fall back to today's behavior."""
    root = native_root(base)
    if not root or not model:
        return OllamaModel()
    cache: dict = hass.data.setdefault(_CACHE, {})
    now = time.monotonic()
    http = async_get_clientsession(hass)
    show_key = ("show", root, model)
    shown = cache.get(show_key)
    if shown is None or shown[0] < now:
        tools, trained = None, None
        try:
            async with http.post(f"{root}/api/show", json={"model": model}, timeout=ClientTimeout(total=8)) as resp:
                if resp.status < 400:
                    tools, trained = parse_show(await resp.json(content_type=None))
        except (ClientError, TimeoutError, ValueError):
            pass
        shown = (now + _SHOW_TTL, tools, trained)
        cache[show_key] = shown
    ps_key = ("ps", root, model)
    loaded = cache.get(ps_key)
    if loaded is None or loaded[0] < now:
        running = None
        try:
            async with http.get(f"{root}/api/ps", timeout=ClientTimeout(total=5)) as resp:
                if resp.status < 400:
                    running = parse_ps(await resp.json(content_type=None), model)
        except (ClientError, TimeoutError, ValueError):
            pass
        loaded = (now + _PS_TTL, running)
        cache[ps_key] = loaded
    return OllamaModel(tools=shown[1], trained=shown[2], running=loaded[1])
