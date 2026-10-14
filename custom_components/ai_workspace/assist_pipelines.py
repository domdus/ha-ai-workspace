"""Create Assist pipelines so agents show under Voice assistants."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, STT_BROWSER, TTS_OFF

_LOGGER = logging.getLogger(__name__)
_OPENAI_STT_PLATFORM = "openai_conversation"


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


def pick_assist_stt(
    *,
    setting: str = "",
    preferred: str | None = None,
    conversation_unique_id: str | None = None,
    engines: list[tuple[str, str, str]] | None = None,
) -> str | None:
    """Choose a real HA STT engine for an AI Workspace Assist pipeline.

    Order: the Speech-to-text setting when it is an ``stt.*`` engine, this
    agent's own engine, any AI Workspace engine, the official OpenAI
    integration, the default Assist pipeline, then any other HA engine.
    """
    chosen = str(setting or "").strip()
    if chosen and chosen != STT_BROWSER and chosen.startswith("stt."):
        return chosen
    rows = list(engines or [])
    wanted = f"{conversation_unique_id}-stt" if conversation_unique_id else ""
    if wanted:
        for entity_id, platform, unique_id in rows:
            if platform == DOMAIN and unique_id == wanted:
                return entity_id
    for entity_id, platform, _unique_id in rows:
        if platform == DOMAIN:
            return entity_id
    for entity_id, platform, _unique_id in rows:
        if platform == _OPENAI_STT_PLATFORM:
            return entity_id
    if preferred:
        return preferred
    for entity_id, _platform, _unique_id in rows:
        if entity_id:
            return entity_id
    return None


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
    fallback_stt: str | None = None,
    fallback_stt_language: str | None = None,
) -> dict[str, Any]:
    """STT/TTS for Assist: our engines, else a discovered engine, else the default pipeline."""
    stt = stt_setting if stt_setting and stt_setting != STT_BROWSER else (fallback_stt or preferred_stt or None)
    tts = tts_setting if tts_setting and tts_setting != TTS_OFF else (preferred_tts or None)
    if stt == preferred_stt:
        stt_language = preferred_stt_language
    elif stt == fallback_stt:
        stt_language = fallback_stt_language or language
    else:
        stt_language = language
    return {
        "stt_engine": stt or None,
        "stt_language": stt_language if stt else None,
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


def _stt_engines(hass: HomeAssistant) -> list[tuple[str, str, str]]:
    found: dict[str, tuple[str, str, str]] = {}
    try:
        from homeassistant.helpers import entity_registry as er

        for row in er.async_get(hass).entities.values():
            if row.domain != "stt" or row.disabled_by is not None:
                continue
            found[row.entity_id] = (row.entity_id, str(row.platform or ""), str(row.unique_id or ""))
    except Exception:
        _LOGGER.debug("STT registry listing skipped", exc_info=True)
    try:
        from homeassistant.components.stt import DATA_COMPONENT

        component = hass.data.get(DATA_COMPONENT)
        for entity in getattr(component, "entities", []) or []:
            entity_id = str(getattr(entity, "entity_id", "") or "")
            if not entity_id or entity_id in found:
                continue
            platform = ""
            host = getattr(entity, "platform", None)
            if host is not None:
                platform = str(getattr(host, "platform_name", "") or "")
            found[entity_id] = (entity_id, platform, str(getattr(entity, "unique_id", "") or ""))
    except Exception:
        _LOGGER.debug("STT component listing skipped", exc_info=True)
    return list(found.values())


def _conversation_unique_id(hass: HomeAssistant, entity_id: str) -> str | None:
    try:
        from homeassistant.helpers import entity_registry as er

        row = er.async_get(hass).async_get(entity_id)
    except Exception:
        return None
    if row is None:
        return None
    unique_id = str(row.unique_id or "").strip()
    return unique_id or None


def _stt_language_for(
    engine_id: str | None,
    language: str,
    engines: list[tuple[str, str, str]] | None = None,
) -> str:
    if not engine_id:
        return language
    platform = next((item[1] for item in engines or [] if item[0] == engine_id), "")
    if platform not in {DOMAIN, _OPENAI_STT_PLATFORM}:
        return language
    try:
        from .stt import _LANGUAGES
        from .voice import match_speech_language

        return match_speech_language(language, _LANGUAGES, language)
    except Exception:
        return language


def _settings(hass: HomeAssistant, entity_id: str, name: str) -> dict[str, Any]:
    language = _language(hass)
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    preferred = _preferred_voice(hass, entity_id)
    engines = _stt_engines(hass)
    fallback_stt = pick_assist_stt(
        setting="",
        preferred=preferred.get("preferred_stt"),
        conversation_unique_id=_conversation_unique_id(hass, entity_id),
        engines=engines,
    )
    voice = resolve_pipeline_voice(
        str(getattr(settings, "stt_engine", "") or ""),
        str(getattr(settings, "tts_engine", "") or ""),
        language=language,
        fallback_stt=fallback_stt,
        fallback_stt_language=_stt_language_for(fallback_stt, language, engines),
        **preferred,
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


async def async_refresh_assist_pipelines(hass: HomeAssistant) -> None:
    """Re-apply STT/TTS onto every AI Workspace Assist pipeline."""
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:
        return
    registry = er.async_get(hass)
    for row in list(registry.entities.values()):
        if row.domain != "conversation" or row.platform != DOMAIN or row.disabled_by is not None:
            continue
        name = str(row.name or row.original_name or "AI Workspace")
        await async_ensure_assist_pipeline(hass, row.entity_id, name)


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
