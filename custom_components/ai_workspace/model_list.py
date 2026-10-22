"""Model ids an agent can pick: the provider's own list when it answers, else the bundled catalog."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_ANTHROPIC,
    API_AZURE,
    DOMAIN,
    MODE_CURSOR,
    api_model_choices,
    api_model_picks,
    default_api_base,
    default_api_model,
)

_LOGGER = logging.getLogger(__name__)
_CACHE = f"{DOMAIN}_model_lists"
_TTL = 3600
# A provider that does not answer is not asked again for a minute, so forms do not wait each time.
_MISS_TTL = 60
_ANTHROPIC_VERSION = "2023-06-01"
# /models also lists embeddings, speech, images, video and dated snapshots. Those can still be typed in.
_NOT_CHAT = re.compile(
    r"embed|whisper|tts|transcribe|dall-e|image|audio|realtime|moderation|davinci|babbage"
    r"|search|computer-use|veo|imagen|lyria|aqa|rerank|guard|sora|nano-banana|robotics"
    r"|(^|-)live(-|$)|translate|turbo-instruct"
    r"|-\d{4}-\d{2}-\d{2}$|-\d{8}$|-\d{4}$",
    re.IGNORECASE,
)


def _natural(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def _tag(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def _ids(rows: Any) -> list[str]:
    out: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        ident = str((row.get("id") if isinstance(row, dict) else row) or "").strip()
        if ident.startswith("models/"):
            ident = ident[len("models/") :]
        if ident and not _NOT_CHAT.search(ident) and ident not in out:
            out.append(ident)
    return out


async def _get_json(hass: HomeAssistant, url: str, headers: dict[str, str]) -> Any:
    try:
        async with async_get_clientsession(hass).get(
            url, headers=headers, timeout=ClientTimeout(total=6)
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except (ClientError, TimeoutError, OSError, ValueError):
        _LOGGER.debug("model list from %s failed", url.split("?")[0], exc_info=True)
        return None


async def _cached(hass: HomeAssistant, tag: str, fetch) -> list[str]:
    cache: dict = hass.data.setdefault(_CACHE, {})
    hit = cache.get(tag)
    if hit and hit[0] > time.monotonic():
        return list(hit[1])
    found = await fetch()
    cache[tag] = (time.monotonic() + (_TTL if found else _MISS_TTL), found)
    return list(found)


async def async_provider_models(hass: HomeAssistant, provider: str, api_key: str = "", api_base: str = "") -> list[str]:
    """GET {base}/models. OpenRouter and Ollama answer without a key; Azure lists deployments elsewhere."""
    if provider in {MODE_CURSOR, API_AZURE}:
        return []
    base = (str(api_base or "").strip() or default_api_base(provider)).rstrip("/")
    key = str(api_key or "").strip()
    if not base:
        return []
    if provider == API_ANTHROPIC:
        if not key:
            return []
        url = f"{base}/models?limit=1000"
        headers = {"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION}
    else:
        url = f"{base}/models"
        headers = {"Authorization": f"Bearer {key}"} if key else {}

    async def fetch() -> list[str]:
        body = await _get_json(hass, url, headers)
        rows = body.get("data") if isinstance(body, dict) else body
        return sorted(_ids(rows), key=_natural, reverse=True)

    return await _cached(hass, _tag(provider, base, key), fetch)


async def async_cursor_models(hass: HomeAssistant, api_key: str = "") -> list[str]:
    """The Cursor SDK's own list, through the Runtime (GET /api/models)."""
    data = hass.data.get(DOMAIN) or {}
    base = str(data.get("runtime_url") or "").rstrip("/")
    if not base:
        return []
    headers = {"Accept": "application/json"}
    token = str(data.get("runtime_token") or "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    key = str(api_key or "").strip()
    if key:
        headers["X-Cursor-Api-Key"] = key

    async def fetch() -> list[str]:
        return _ids(await _get_json(hass, f"{base}/api/models", headers))

    return await _cached(hass, _tag(MODE_CURSOR, base, key), fetch)


def merge_models(kind: str, configured: str, live: list[str]) -> list[str]:
    """Configured model first, then our picks, then the rest. Bundled catalog when the live list is empty."""
    out: list[str] = []
    picks = api_model_picks(kind)
    rest = live if live else api_model_choices(kind)
    for name in (configured, *(p for p in picks if not live or p in live), *rest):
        name = str(name or "").strip()
        if name and name not in out:
            out.append(name)
    return out


async def async_agent_models(hass: HomeAssistant, agent) -> list[str]:
    """Everything the chat model switcher offers for one agent."""
    if agent.mode == MODE_CURSOR:
        live = await async_cursor_models(hass, agent.cursor_api_key)
        return merge_models(MODE_CURSOR, agent.model or default_api_model(MODE_CURSOR), live)
    if agent.provider == API_AZURE:
        return [agent.model] if agent.model else []
    live = await async_provider_models(hass, agent.provider, agent.api_key, agent.api_base)
    return merge_models(agent.provider, agent.model or default_api_model(agent.provider), live)
