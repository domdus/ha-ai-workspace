"""Create Assist pipelines so agents show under Voice assistants."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DEFAULT_TTS_VOICE, DOMAIN, STT_BROWSER, TTS_LANGUAGES, is_placeholder_tts

_LOGGER = logging.getLogger(__name__)
_OPENAI_STT_PLATFORM = "openai_conversation"
_GENERIC_PIPELINE_NAMES = frozenset({"", "ai workspace", "agent"})


def conversation_pipeline_name(*candidates: str) -> str:
    """Prefer the agent title over the integration name."""
    texts = [str(item or "").strip() for item in candidates]
    for text in texts:
        if text and text.casefold() not in _GENERIC_PIPELINE_NAMES:
            return text
    for text in texts:
        if text:
            return text
    return "AI Workspace"


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


def pick_assist_tts(
    *,
    setting: str = "",
    preferred: str | None = None,
    conversation_unique_id: str | None = None,
    engines: list[tuple[str, str, str]] | None = None,
) -> str | None:
    """Choose a TTS engine for a new AI Workspace Assist pipeline.

    Order: an explicit setting (including Google Translate), this agent's own
    engine, any AI Workspace engine, the official OpenAI integration, the
    default Assist pipeline, then any other HA engine.
    """
    chosen = str(setting or "").strip()
    if chosen and not is_placeholder_tts(chosen):
        return chosen
    rows = list(engines or [])
    wanted = f"{conversation_unique_id}-tts" if conversation_unique_id else ""
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
    if preferred and not is_placeholder_tts(str(preferred)):
        return preferred
    for entity_id, _platform, _unique_id in rows:
        if entity_id and not is_placeholder_tts(entity_id):
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
    fallback_tts: str | None = None,
    engine_tts_voice: str | None = None,
) -> dict[str, Any]:
    """STT/TTS for Assist: our engines, else a discovered engine, else the default pipeline."""
    stt = stt_setting if stt_setting and stt_setting != STT_BROWSER else (fallback_stt or preferred_stt or None)
    tts = (
        tts_setting
        if tts_setting and not is_placeholder_tts(tts_setting)
        else (fallback_tts or preferred_tts or None)
    )
    if stt == preferred_stt:
        stt_language = preferred_stt_language
    elif stt == fallback_stt:
        stt_language = fallback_stt_language or language
    else:
        stt_language = language
    if tts and engine_tts_voice:
        tts_voice = engine_tts_voice
    elif tts and tts == preferred_tts:
        tts_voice = preferred_tts_voice
    else:
        tts_voice = None
    return {
        "stt_engine": stt or None,
        "stt_language": stt_language if stt else None,
        "tts_engine": tts or None,
        "tts_language": (preferred_tts_language if tts == preferred_tts else language) if tts else None,
        "tts_voice": tts_voice,
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


def _speech_engines(hass: HomeAssistant, domain: str) -> list[tuple[str, str, str]]:
    found: dict[str, tuple[str, str, str]] = {}
    try:
        from homeassistant.helpers import entity_registry as er

        for row in er.async_get(hass).entities.values():
            if row.domain != domain or row.disabled_by is not None:
                continue
            found[row.entity_id] = (row.entity_id, str(row.platform or ""), str(row.unique_id or ""))
    except Exception:
        _LOGGER.debug("%s registry listing skipped", domain, exc_info=True)
    try:
        if domain == "stt":
            from homeassistant.components.stt import DATA_COMPONENT
        else:
            from homeassistant.components.tts import DATA_COMPONENT

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
        _LOGGER.debug("%s component listing skipped", domain, exc_info=True)
    return list(found.values())


def _stt_engines(hass: HomeAssistant) -> list[tuple[str, str, str]]:
    return _speech_engines(hass, "stt")


def _tts_engines(hass: HomeAssistant) -> list[tuple[str, str, str]]:
    return _speech_engines(hass, "tts")


def _workspace_tts_voice(hass: HomeAssistant, engine_id: str) -> str | None:
    """Voice stored on the AI Workspace agent that owns this TTS engine."""
    engine_id = str(engine_id or "").strip()
    if not engine_id.startswith("tts."):
        return None
    try:
        from homeassistant.helpers import entity_registry as er

        row = er.async_get(hass).async_get(engine_id)
    except Exception:
        return None
    if row is None or row.domain != "tts" or row.platform != DOMAIN:
        return None
    unique = str(row.unique_id or "")
    if not unique.endswith("-tts"):
        return None
    agent_id = unique[: -len("-tts")]
    entry = (hass.data.get(DOMAIN) or {}).get("entry")
    if entry is None:
        return None
    try:
        from .agents import entry_agents
    except Exception:
        return None
    for agent in entry_agents(entry):
        if agent.id == agent_id and agent.assist_tts:
            return str(agent.tts_voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    return None


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


def _tts_language_for(
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
        from .voice import match_speech_language

        return match_speech_language(language, TTS_LANGUAGES, "en")
    except Exception:
        return language


def _existing_engine(entity_id: str, engines: list[tuple[str, str, str]]) -> str:
    chosen = str(entity_id or "").strip()
    if not chosen:
        return ""
    if chosen in {row[0] for row in engines}:
        return chosen
    if chosen.startswith(("stt.", "tts.")):
        return ""
    return chosen


def _keep_pipeline_engine(entity_id: str | None, engines: list[tuple[str, str, str]]) -> str | None:
    """Keep a pipeline engine the user set, or None if that entity is gone."""
    kept = _existing_engine(str(entity_id or ""), engines)
    return kept or None


def _settings(hass: HomeAssistant, entity_id: str, name: str, existing: Any = None) -> dict[str, Any]:
    language = str(getattr(existing, "language", None) or "").strip() or _language(hass)
    conversation_language = (
        str(getattr(existing, "conversation_language", None) or "").strip() or language
    )
    engines = _stt_engines(hass)
    tts_engines = _tts_engines(hass)
    if existing is not None:
        stt = _keep_pipeline_engine(getattr(existing, "stt_engine", None), engines)
        tts = _keep_pipeline_engine(getattr(existing, "tts_engine", None), tts_engines)
        return {
            "conversation_engine": entity_id,
            "conversation_language": conversation_language,
            "language": language,
            "name": name,
            "wake_word_entity": getattr(existing, "wake_word_entity", None),
            "wake_word_id": getattr(existing, "wake_word_id", None),
            "prefer_local_intents": bool(getattr(existing, "prefer_local_intents", False)),
            "stt_engine": stt,
            "stt_language": (getattr(existing, "stt_language", None) or None) if stt else None,
            "tts_engine": tts,
            "tts_language": (getattr(existing, "tts_language", None) or None) if tts else None,
            "tts_voice": (getattr(existing, "tts_voice", None) or None) if tts else None,
        }
    preferred = _preferred_voice(hass, entity_id)
    unique_id = _conversation_unique_id(hass, entity_id)
    fallback_stt = pick_assist_stt(
        setting="",
        preferred=preferred.get("preferred_stt"),
        conversation_unique_id=unique_id,
        engines=engines,
    )
    fallback_tts = pick_assist_tts(
        setting="",
        preferred=preferred.get("preferred_tts"),
        conversation_unique_id=unique_id,
        engines=tts_engines,
    )
    voice = resolve_pipeline_voice(
        "",
        "",
        language=language,
        fallback_stt=fallback_stt,
        fallback_stt_language=_stt_language_for(fallback_stt, language, engines),
        fallback_tts=fallback_tts,
        engine_tts_voice=_workspace_tts_voice(hass, str(fallback_tts or "")),
        **preferred,
    )
    tts_engine = voice.get("tts_engine")
    if tts_engine:
        voice["tts_language"] = _tts_language_for(
            str(tts_engine),
            str(voice.get("tts_language") or language),
            tts_engines,
        )
    return {
        "conversation_engine": entity_id,
        "conversation_language": conversation_language,
        "language": language,
        "name": name,
        "wake_word_entity": None,
        "wake_word_id": None,
        "prefer_local_intents": False,
        **voice,
    }


def _existing_pipeline_name(hass: HomeAssistant, entity_id: str) -> str:
    store = _pipeline_store(hass)
    if store is None:
        return ""
    for pipeline in list(store.data.values()):
        if getattr(pipeline, "conversation_engine", None) == entity_id:
            return str(getattr(pipeline, "name", "") or "")
    return ""


def _device_name_for_entity(hass: HomeAssistant, device_id: str | None) -> str:
    if not device_id:
        return ""
    try:
        from homeassistant.helpers import device_registry as dr

        device = dr.async_get(hass).async_get(device_id)
    except Exception:
        return ""
    if device is None:
        return ""
    return str(getattr(device, "name_by_user", None) or getattr(device, "name", "") or "").strip()


async def async_ensure_assist_pipeline(hass: HomeAssistant, entity_id: str, name: str) -> None:
    """Make sure Voice assistants has a ready pipeline for this conversation agent."""
    entity_id = str(entity_id or "").strip()
    name = conversation_pipeline_name(name, _existing_pipeline_name(hass, entity_id))
    if not entity_id.startswith("conversation."):
        return
    store = _pipeline_store(hass)
    if store is None:
        return
    for pipeline in list(store.data.values()):
        if getattr(pipeline, "conversation_engine", None) != entity_id:
            continue
        wanted = _settings(hass, entity_id, name, existing=pipeline)
        try:
            await store.async_update_item(pipeline.id, wanted)
        except Exception:
            _LOGGER.debug("Assist pipeline update skipped for %s", entity_id, exc_info=True)
        return
    wanted = _settings(hass, entity_id, name)
    try:
        await store.async_create_item(wanted)
        _LOGGER.info("Assist pipeline ready for %s", entity_id)
    except Exception:
        _LOGGER.exception("Could not create Assist pipeline for %s", entity_id)


async def async_prune_voice_entities(
    hass: HomeAssistant,
    entry_id: str,
    domain: str,
    wanted_unique_ids: set[str],
) -> None:
    """Remove leftover Assist/STT/TTS entities after those options are turned off."""
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:
        return
    registry = er.async_get(hass)
    wanted = {str(item) for item in wanted_unique_ids}
    for row in list(er.async_entries_for_config_entry(registry, entry_id)):
        if row.domain != domain or row.platform != DOMAIN:
            continue
        if str(row.unique_id or "") in wanted:
            continue
        if domain == "conversation":
            await async_remove_assist_pipeline(hass, row.entity_id)
        try:
            registry.async_remove(row.entity_id)
        except Exception:
            _LOGGER.debug("voice entity prune skipped for %s", row.entity_id, exc_info=True)


async def async_refresh_assist_pipelines(hass: HomeAssistant) -> None:
    """Refresh AI Workspace Assist pipelines without overwriting STT/TTS the user set."""
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:
        return
    registry = er.async_get(hass)
    for row in list(registry.entities.values()):
        if row.domain != "conversation" or row.platform != DOMAIN or row.disabled_by is not None:
            continue
        name = conversation_pipeline_name(
            _device_name_for_entity(hass, row.device_id),
            row.name,
            row.original_name,
            _existing_pipeline_name(hass, row.entity_id),
        )
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
