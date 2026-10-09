"""Conversation agents already set up in Home Assistant, used from this chat."""

from __future__ import annotations

from typing import Any, AsyncIterator

from homeassistant.core import Context, HomeAssistant

from .const import DOMAIN, is_builtin_assist_agent


def list_assist_agents(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Agents from other integrations. Our own Assist entities are left out."""
    try:
        from homeassistant.components.conversation import get_agent_manager
        from homeassistant.components.conversation.const import DATA_COMPONENT
        from homeassistant.components.conversation.entity import ConversationEntity
    except ImportError:
        return []

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    component = hass.data.get(DATA_COMPONENT)
    if component is not None:
        for entity in component.entities:
            entity_id = str(getattr(entity, "entity_id", "") or "")
            if not entity_id or entity_id in seen:
                continue
            reg = registry.async_get(entity_id)
            platform = str(getattr(reg, "platform", "") or "")
            if platform == DOMAIN or is_builtin_assist_agent(entity_id, platform):
                continue
            state = hass.states.get(entity_id)
            name = state.name if state is not None and state.name else ""
            if not name and reg is not None:
                name = reg.name or reg.original_name or ""
            available = bool(getattr(entity, "available", True))
            found.append(
                {
                    "id": entity_id,
                    "label": name or entity_id,
                    "available": available,
                    "reason": None if available else "This Assist agent is unavailable.",
                    "kind": "assist",
                }
            )
            seen.add(entity_id)

    try:
        manager = get_agent_manager(hass)
    except Exception:
        manager = None
    if manager is not None:
        for info in manager.async_get_agent_info():
            if info.id in seen or is_builtin_assist_agent(info.id):
                continue
            agent = manager.async_get_agent(info.id)
            if isinstance(agent, ConversationEntity):
                continue
            entry = hass.config_entries.async_get_entry(info.id)
            if entry is not None and entry.domain == DOMAIN:
                continue
            found.append(
                {
                    "id": info.id,
                    "label": info.name or info.id,
                    "available": True,
                    "reason": None,
                    "kind": "assist",
                }
            )
            seen.add(info.id)
    found.sort(key=lambda item: str(item["label"]).casefold())
    return found


def assist_agent_ids(hass: HomeAssistant) -> set[str]:
    return {str(item["id"]) for item in list_assist_agents(hass)}


def _plain_speech(result: Any) -> str:
    response = getattr(result, "response", None)
    speech = getattr(response, "speech", None) or {}
    plain = speech.get("plain") if isinstance(speech, dict) else None
    if isinstance(plain, dict):
        return str(plain.get("speech") or "").strip()
    return str(plain or "").strip()


async def async_assist_events(
    hass: HomeAssistant,
    user_id: str,
    agent_id: str,
    conversation_id: str,
    text: str,
    language: str = "",
    extra_system_prompt: str = "",
) -> AsyncIterator[dict]:
    """One turn through an existing Assist conversation agent."""
    from homeassistant.components.conversation import async_converse

    yield {"type": "status", "text": "Working"}
    try:
        result = await async_converse(
            hass,
            text,
            conversation_id,
            Context(user_id=user_id or None),
            language or hass.config.language,
            agent_id=agent_id,
            extra_system_prompt=extra_system_prompt or None,
        )
    except Exception as exc:
        yield {"type": "error", "message": str(exc)[:400]}
        return
    speech = _plain_speech(result)
    if not speech:
        yield {"type": "error", "message": "The assistant returned nothing."}
        return
    yield {"type": "text", "delta": speech}
    yield {"type": "result", "text": speech, "status": "finished"}
