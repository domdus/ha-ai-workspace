"""Agents saved as rows on the AI Workspace entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .models import ProviderInfo

from .const import (
    API_AZURE,
    API_OLLAMA,
    API_OPENAI,
    API_PROVIDERS,
    API_SHORT_LABELS,
    BORROW_DOMAINS,
    CONF_API_BASE,
    CONF_API_KEY,
    CONF_AGENT_ID,
    CONF_API_PROVIDER,
    CONF_AZURE_API_VERSION,
    CONF_CHECK_HOUSE,
    CONF_CURSOR_API_KEY,
    CONF_EFFORT,
    CONF_LOW_TOKEN,
    CONF_MODE,
    CONF_MODEL,
    DEFAULT_AZURE_API_VERSION,
    EFFORT_DEFAULT,
    EFFORTS,
    MODE_API,
    MODE_CURSOR,
    SUBENTRY_AGENT,
    assist_enabled,
    assist_stt_enabled,
    resolved_stt_model,
    default_api_base,
    default_api_model,
)

_KEY_NAMES = ("api_key", "token", "openai_api_key", "azure_api_key")
_URL_NAMES = ("api_base", "url", "endpoint", "azure_endpoint", "azure_base_url")
_MODEL_NAMES = ("model", "chat_model", "deployment", "azure_deployment")
_VERSION_NAMES = ("azure_api_version", "api_version")


@dataclass
class Agent:
    id: str
    title: str
    mode: str
    provider: str
    api_key: str = ""
    api_base: str = ""
    model: str = ""
    effort: str = ""
    enabled: bool = True
    assist: bool = True
    assist_stt: bool = False
    stt_model: str = ""
    low_token: bool = False
    check_house: bool = True
    azure_api_version: str = DEFAULT_AZURE_API_VERSION
    cursor_api_key: str = ""
    subentry_id: str = ""

    def label(self) -> str:
        name = self.title or API_SHORT_LABELS.get(self.provider, "Cursor" if self.mode == MODE_CURSOR else "Agent")
        model = (self.model or "").strip()
        effort = EFFORTS.get(self.effort or "", "")
        bits = [name]
        if model:
            bits.append(model)
        if self.effort:
            bits.append(effort or self.effort)
        return " · ".join(bits)


def _text(value: Any) -> str:
    return str(value or "").strip()


def agent_from_mapping(agent_id: str, title: str, raw: Mapping[str, Any]) -> Agent:
    provider = _text(raw.get(CONF_API_PROVIDER))
    mode = _text(raw.get(CONF_MODE))
    if provider == MODE_CURSOR or mode == MODE_CURSOR:
        mode = MODE_CURSOR
        provider = MODE_CURSOR
    elif provider not in API_PROVIDERS:
        provider = API_OPENAI
        mode = MODE_API
    else:
        mode = MODE_API
    effort = _text(raw.get(CONF_EFFORT))
    if effort not in EFFORTS or effort == EFFORT_DEFAULT:
        effort = ""
    return Agent(
        id=agent_id,
        title=_text(title) or API_SHORT_LABELS.get(provider, "Agent"),
        mode=mode,
        provider=provider,
        api_key=_text(raw.get(CONF_API_KEY)),
        api_base=_text(raw.get(CONF_API_BASE)),
        model=_text(raw.get(CONF_MODEL)),
        effort=effort,
        enabled=True,
        assist=assist_enabled(raw),
        assist_stt=assist_stt_enabled(raw, provider),
        stt_model=resolved_stt_model(raw, provider),
        low_token=bool(raw.get(CONF_LOW_TOKEN, False)),
        check_house=bool(raw.get(CONF_CHECK_HOUSE, True)),
        azure_api_version=_text(raw.get(CONF_AZURE_API_VERSION)) or DEFAULT_AZURE_API_VERSION,
        cursor_api_key=_text(raw.get(CONF_CURSOR_API_KEY)),
    )


def entry_agents(entry: ConfigEntry) -> list[Agent]:
    found: list[Agent] = []
    for sub in getattr(entry, "subentries", {}).values():
        if getattr(sub, "subentry_type", "") != SUBENTRY_AGENT:
            continue
        raw = getattr(sub, "data", {}) or {}
        agent_id = _text(raw.get(CONF_AGENT_ID)) or _text(getattr(sub, "unique_id", "")) or sub.subentry_id
        agent = agent_from_mapping(agent_id, sub.title, raw)
        agent.subentry_id = sub.subentry_id
        found.append(agent)
    return found


def _blobs(entry: ConfigEntry) -> list[Mapping[str, Any]]:
    blobs: list[Mapping[str, Any]] = [entry.data, entry.options]
    for sub in getattr(entry, "subentries", {}).values():
        blobs.append(getattr(sub, "data", {}) or {})
    return blobs


def _pick(blobs: list[Mapping[str, Any]], names: tuple[str, ...]) -> str:
    for blob in blobs:
        for name in names:
            value = blob.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _ollama_base(url: str) -> str:
    base = url.rstrip("/")
    if not base:
        return default_api_base(API_OLLAMA)
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def borrowed_setups(hass: HomeAssistant) -> list[dict[str, str]]:
    """Keys already stored by other AI integrations. Labels never include the key."""
    found: list[dict[str, str]] = []
    entries = getattr(getattr(hass, "config_entries", None), "async_entries", None)
    if not callable(entries):
        return found
    try:
        items = entries()
    except TypeError:
        return found
    for entry in items:
        domain = str(getattr(entry, "domain", "") or "")
        provider = BORROW_DOMAINS.get(domain)
        if not provider:
            continue
        blobs = _blobs(entry)
        key = _pick(blobs, _KEY_NAMES)
        url = _pick(blobs, _URL_NAMES)
        model = _pick(blobs, _MODEL_NAMES)
        version = _pick(blobs, _VERSION_NAMES) or DEFAULT_AZURE_API_VERSION
        if provider == API_OLLAMA:
            url = _ollama_base(url)
        elif provider == API_AZURE:
            if not key or not url:
                continue
        elif not key:
            continue
        title = _text(getattr(entry, "title", "")) or API_SHORT_LABELS.get(provider, provider)
        found.append(
            {
                "id": f"{domain}:{entry.entry_id}",
                "label": f"{title} ({API_SHORT_LABELS.get(provider, provider)})",
                "provider": provider,
                "api_key": key,
                "api_base": url or default_api_base(provider),
                "model": model or default_api_model(provider),
                "azure_api_version": version,
            }
        )
    return found


class CursorAgent:
    """Cursor chats go to the SDK runtime with this agent's model and effort."""

    kind = "cursor"

    def __init__(self, agent: Agent, available: bool, reason: str | None) -> None:
        self.model = agent.model
        self.effort = agent.effort
        self.api_key = agent.cursor_api_key
        self.info = ProviderInfo(agent.id, agent.label(), available, reason)


def borrow_by_id(hass: HomeAssistant, borrow_id: str) -> dict[str, str] | None:
    wanted = _text(borrow_id)
    if not wanted:
        return None
    for item in borrowed_setups(hass):
        if item["id"] == wanted:
            return item
    return None
