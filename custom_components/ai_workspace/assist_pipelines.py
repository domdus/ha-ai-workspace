"""Create Assist pipelines so agents show under Voice assistants."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _pipeline_store(hass: HomeAssistant):
    if "assist_pipeline" not in hass.config.components:
        return None
    try:
        from homeassistant.components.assist_pipeline.pipeline import KEY_ASSIST_PIPELINE
    except ImportError:
        return None
    data = hass.data.get(KEY_ASSIST_PIPELINE)
    if data is None:
        return None
    return getattr(data, "pipeline_store", None)


def _language(hass: HomeAssistant) -> str:
    return str(getattr(hass.config, "language", None) or "en").strip() or "en"


def _settings(entity_id: str, name: str, language: str) -> dict[str, Any]:
    return {
        "conversation_engine": entity_id,
        "conversation_language": language,
        "language": language,
        "name": name,
        "stt_engine": None,
        "stt_language": None,
        "tts_engine": None,
        "tts_language": None,
        "tts_voice": None,
        "wake_word_entity": None,
        "wake_word_id": None,
        "prefer_local_intents": False,
    }


async def async_ensure_assist_pipeline(hass: HomeAssistant, entity_id: str, name: str) -> None:
    """Make sure Voice assistants has a ready pipeline for this conversation agent."""
    entity_id = str(entity_id or "").strip()
    name = str(name or "").strip() or entity_id
    if not entity_id.startswith("conversation."):
        return
    store = _pipeline_store(hass)
    if store is None:
        return
    language = _language(hass)
    for pipeline in list(store.data.values()):
        if getattr(pipeline, "conversation_engine", None) != entity_id:
            continue
        if getattr(pipeline, "name", None) != name:
            try:
                await store.async_update_item(
                    pipeline.id,
                    _settings(entity_id, name, language),
                )
            except Exception:
                _LOGGER.debug("Assist pipeline rename skipped for %s", entity_id, exc_info=True)
        return
    try:
        await store.async_create_item(_settings(entity_id, name, language))
        _LOGGER.info("Assist pipeline ready for %s", entity_id)
    except Exception:
        _LOGGER.exception("Could not create Assist pipeline for %s", entity_id)


async def async_remove_assist_pipeline(hass: HomeAssistant, entity_id: str) -> None:
    """Remove the Voice assistants pipeline that pointed at this conversation agent."""
    entity_id = str(entity_id or "").strip()
    if not entity_id.startswith("conversation."):
        return
    store = _pipeline_store(hass)
    if store is None:
        return
    for pipeline in list(store.data.values()):
        if getattr(pipeline, "conversation_engine", None) != entity_id:
            continue
        preferred = store.async_get_preferred_item()
        if preferred == pipeline.id:
            for other in store.data.values():
                if other.id != pipeline.id:
                    store.async_set_preferred_item(other.id)
                    break
        try:
            await store.async_delete_item(pipeline.id)
        except Exception:
            _LOGGER.debug("Assist pipeline remove skipped for %s", entity_id, exc_info=True)
