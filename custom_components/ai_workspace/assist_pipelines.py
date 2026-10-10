"""Create Assist pipelines so agents show under Voice assistants."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, STT_BROWSER, TTS_OFF

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


def resolve_pipeline_voice(
    stt_setting: str,
    tts_setting: str,
    *,
    language: str = "en",
    preferred_stt: str | None = None,
    preferred_stt_language: str | None = None,
    preferred_tts: str | None = None,
    preferred_tts_language: str | None = None,
    preferred_tts_voice: str | None = None,
) -> dict[str, Any]:
    """STT/TTS for Assist: our engines, else the default Assist pipeline."""
    stt = stt_setting if stt_setting and stt_setting != STT_BROWSER else (preferred_stt or None)
    tts = tts_setting if tts_setting and tts_setting != TTS_OFF else (preferred_tts or None)
    return {
        "stt_engine": stt or None,
        "stt_language": (preferred_stt_language if stt == preferred_stt else language) if stt else None,
        "tts_engine": tts or None,
        "tts_language": (preferred_tts_language if tts == preferred_tts else language) if tts else None,
        "tts_voice": preferred_tts_voice if tts and tts == preferred_tts else None,
    }


def _preferred_voice(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    store = _pipeline_store(hass)
    if store is None:
        return {}
    try:
        pref_id = store.async_get_preferred_item()
    except Exception:
        return {}
    pipeline = (store.data or {}).get(pref_id) if pref_id else None
    if pipeline is None:
        return {}
    if str(getattr(pipeline, "conversation_engine", "") or "") == entity_id:
        return {}
    return {
        "preferred_stt": getattr(pipeline, "stt_engine", None) or None,
        "preferred_stt_language": getattr(pipeline, "stt_language", None) or None,
        "preferred_tts": getattr(pipeline, "tts_engine", None) or None,
        "preferred_tts_language": getattr(pipeline, "tts_language", None) or None,
        "preferred_tts_voice": getattr(pipeline, "tts_voice", None) or None,
    }


def _settings(hass: HomeAssistant, entity_id: str, name: str) -> dict[str, Any]:
    language = _language(hass)
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    voice = resolve_pipeline_voice(
        str(getattr(settings, "stt_engine", "") or ""),
        str(getattr(settings, "tts_engine", "") or ""),
        language=language,
        **_preferred_voice(hass, entity_id),
    )
    return {
        "conversation_engine": entity_id,
        "conversation_language": language,
        "language": language,
        "name": name,
        "wake_word_entity": None,
        "wake_word_id": None,
        "prefer_local_intents": False,
        **voice,
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
    wanted = _settings(hass, entity_id, name)
    for pipeline in list(store.data.values()):
        if getattr(pipeline, "conversation_engine", None) != entity_id:
            continue
        try:
            await store.async_update_item(pipeline.id, wanted)
        except Exception:
            _LOGGER.debug("Assist pipeline update skipped for %s", entity_id, exc_info=True)
        return
    try:
        await store.async_create_item(wanted)
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
