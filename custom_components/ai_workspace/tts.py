"""Text-to-speech from an agent key, for Assist pipelines and the overlay."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from aiohttp import ClientTimeout
from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .agents import Agent, entry_agents
from .const import (
    API_GEMINI,
    API_OPENROUTER,
    DOMAIN,
    TTS_LANGUAGES,
    default_api_base,
    default_tts_model,
    default_tts_voice,
    gemini_generate_content_headers,
    gemini_generate_content_url,
    tts_voices,
)
from .voice import gemini_inline_audio, gemini_speech_payload, match_speech_language, speech_text

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _agent_device_active(hass: HomeAssistant, entry_id: str, subentry_id: str | None) -> bool:
    if not subentry_id:
        return True
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry_id):
        if device.config_subentry_id != subentry_id:
            continue
        return device.disabled_by is None
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One TTS entity per agent that has Text-to-speech on."""
    from .assist_pipelines import async_prune_voice_entities, async_refresh_assist_pipelines

    keep: set[str] = set()
    wanted = 0
    for agent in entry_agents(entry):
        if not agent.assist_tts or not agent.api_key:
            continue
        keep.add(f"{agent.id}-tts")
        if not _agent_device_active(hass, entry.entry_id, agent.subentry_id):
            continue
        async_add_entities(
            [AiWorkspaceTTSEntity(entry, agent)],
            config_subentry_id=agent.subentry_id or None,
        )
        wanted += 1
    await async_prune_voice_entities(hass, entry.entry_id, "tts", keep)
    _LOGGER.info("Exposing %s text-to-speech engine(s)", wanted)
    await async_refresh_assist_pipelines(hass)


class AiWorkspaceTTSEntity(tts.TextToSpeechEntity):
    """Speak Assist and overlay replies with the same API key as the chat agent."""

    _attr_icon = "mdi:speaker"
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Text-to-speech"
    _attr_supported_options = [getattr(tts, "ATTR_VOICE", "voice")]

    @property
    def supported_languages(self) -> list[str]:
        return list(TTS_LANGUAGES)

    @property
    def default_language(self) -> str:
        hass_lang = str(getattr(getattr(self.hass, "config", None), "language", "") or "en")
        return match_speech_language(hass_lang, TTS_LANGUAGES, "en")

    def __init__(self, entry: ConfigEntry, agent: Agent) -> None:
        self._entry = entry
        self._agent_id = agent.id
        self._provider = agent.provider
        self._api_key = agent.api_key
        self._api_base = agent.api_base
        self._tts_model = agent.tts_model or default_tts_model(agent.provider)
        self._tts_voice = agent.tts_voice or default_tts_voice(agent.provider)
        self._tts_speed = float(agent.tts_speed or 1.0)
        self.id = agent.id
        self.title = agent.title
        self.kind = agent.provider
        self._attr_unique_id = f"{agent.id}-tts"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent:{agent.id}")},
            name=agent.title or entry.title or "AI Workspace",
            manufacturer="AI Workspace",
            model="Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        voice_cls = getattr(tts, "Voice", None)
        self._voices = (
            [voice_cls(voice, voice) for voice in tts_voices(agent.provider)] if voice_cls else []
        )

    @property
    def default_options(self) -> Mapping[str, Any]:
        return {getattr(tts, "ATTR_VOICE", "voice"): self._tts_voice}

    @callback
    def async_get_supported_voices(self, language: str) -> list:
        del language
        return list(self._voices)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from .assist_pipelines import async_refresh_assist_pipelines

        await async_refresh_assist_pipelines(self.hass)

    def _base(self) -> str:
        return (self._api_base or default_api_base(self._provider) or "https://api.openai.com/v1").rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._provider == API_GEMINI:
            headers["x-goog-api-key"] = self._api_key
        if self._provider == API_OPENROUTER:
            headers["HTTP-Referer"] = "https://github.com/domdus/ha-ai-workspace"
            headers["X-Title"] = "AI Workspace"
        return headers

    async def _record_usage(self, *, text: str, model: str, usage=None) -> None:
        try:
            from .usage_record import record_tts_usage

            provider = ((self.hass.data.get(DOMAIN) or {}).get("providers") or {}).get(self._agent_id) or self
            await record_tts_usage(
                self.hass,
                text=text,
                model=model,
                provider=provider,
                usage=usage,
            )
        except Exception:
            _LOGGER.debug("tts usage not recorded", exc_info=True)

    async def _synthesize_gemini(self, text: str, voice: str, language: str) -> bytes:
        from .usage_cost import parse_usage

        model = self._tts_model or default_tts_model(API_GEMINI)
        url = gemini_generate_content_url(self._api_base, model)
        payload = gemini_speech_payload(text, voice, language)
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                url,
                json=payload,
                headers=gemini_generate_content_headers(self._api_key),
                timeout=ClientTimeout(total=45, sock_connect=10),
            ) as resp:
                raw = await resp.read()
                if resp.status >= 400:
                    detail = raw.decode("utf-8", errors="replace")[:300]
                    _LOGGER.warning("Text-to-speech HTTP %s: %s", resp.status, detail)
                    raise HomeAssistantError(f"Text-to-speech HTTP {resp.status}")
        except TimeoutError as err:
            raise HomeAssistantError("Text-to-speech timed out.") from err
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError as err:
            raise HomeAssistantError("Text-to-speech returned no audio.") from err
        audio = gemini_inline_audio(data if isinstance(data, dict) else {})
        if not audio:
            raise HomeAssistantError("Text-to-speech returned no audio.")
        piece = parse_usage(data, model=model) if isinstance(data, dict) else None
        await self._record_usage(text=text, model=model, usage=piece)
        return audio

    async def _synthesize(self, message: str, voice: str, fmt: str = "mp3") -> bytes:
        text = speech_text(message)
        if not text:
            return b""
        payload = {
            "model": self._tts_model or default_tts_model(self._provider),
            "input": text,
            "voice": voice or self._tts_voice or default_tts_voice(self._provider),
            "response_format": fmt,
            "speed": max(0.25, min(4.0, self._tts_speed or 1.0)),
        }
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"{self._base()}/audio/speech",
                json=payload,
                headers=self._headers(),
                timeout=ClientTimeout(total=45, sock_connect=10),
            ) as resp:
                body = await resp.read()
                if resp.status >= 400:
                    detail = body.decode("utf-8", errors="replace")[:300]
                    _LOGGER.warning("Text-to-speech HTTP %s: %s", resp.status, detail)
                    raise HomeAssistantError(f"Text-to-speech HTTP {resp.status}")
        except TimeoutError as err:
            raise HomeAssistantError("Text-to-speech timed out.") from err
        if not body:
            raise HomeAssistantError("Text-to-speech returned no audio.")
        await self._record_usage(text=text, model=str(payload.get("model") or self._tts_model))
        return body

    def _voice_from(self, options: dict[str, Any]) -> str:
        key = getattr(tts, "ATTR_VOICE", "voice")
        fallback = self._tts_voice or default_tts_voice(self._provider)
        voice = str(options.get(key) or fallback).strip()
        if self._provider == API_GEMINI:
            names = {name.casefold(): name for name in tts_voices(API_GEMINI)}
            return names.get(voice.casefold(), voice or fallback)
        return voice.casefold() or fallback

    async def async_get_tts_audio(self, message: str, language: str, options: dict[str, Any]) -> tts.TtsAudioType:
        voice = self._voice_from(options)
        try:
            if self._provider == API_GEMINI:
                spoken = speech_text(message)
                if not spoken:
                    raise HomeAssistantError("Text-to-speech returned no audio.")
                audio = await self._synthesize_gemini(spoken, voice, language)
                ext = "wav"
            else:
                audio = await self._synthesize(message, voice)
                ext = "mp3"
        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.exception("Text-to-speech failed")
            raise HomeAssistantError(str(err) or "Text-to-speech failed") from err
        if not audio:
            raise HomeAssistantError("Text-to-speech returned no audio.")
        return ext, audio
