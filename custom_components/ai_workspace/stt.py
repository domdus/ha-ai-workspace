"""Speech-to-text from an agent key, for Assist pipelines."""

from __future__ import annotations

import io
import json
import logging
import wave
from collections.abc import AsyncIterable

from aiohttp import ClientTimeout, FormData
from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .agents import Agent, entry_agents
from .const import (
    API_GEMINI,
    API_OPENROUTER,
    DOMAIN,
    default_api_base,
    default_stt_model,
    gemini_generate_content_url,
)
from .voice import gemini_response_text, gemini_transcribe_payload

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

_LANGUAGES = [
    "af-ZA",
    "ar-SA",
    "az-AZ",
    "be-BY",
    "bg-BG",
    "bs-BA",
    "ca-ES",
    "cs-CZ",
    "cy-GB",
    "da-DK",
    "de-DE",
    "el-GR",
    "en-US",
    "es-ES",
    "et-EE",
    "fa-IR",
    "fi-FI",
    "fil-PH",
    "fr-FR",
    "gl-ES",
    "he-IL",
    "hi-IN",
    "hr-HR",
    "hu-HU",
    "hy-AM",
    "id-ID",
    "is-IS",
    "it-IT",
    "ja-JP",
    "kk-KZ",
    "kn-IN",
    "ko-KR",
    "lt-LT",
    "lv-LV",
    "mi-NZ",
    "mk-MK",
    "mr-IN",
    "ms-MY",
    "ne-NP",
    "nl-NL",
    "no-NO",
    "pl-PL",
    "pt-PT",
    "ro-RO",
    "ru-RU",
    "sk-SK",
    "sl-SI",
    "sr-RS",
    "sv-SE",
    "sw-KE",
    "ta-IN",
    "th-TH",
    "tr-TR",
    "uk-UA",
    "ur-PK",
    "vi-VN",
    "zh-CN",
]


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
    """One STT entity per agent that has Speech-to-text on."""
    from .assist_pipelines import async_prune_voice_entities, async_refresh_assist_pipelines

    keep: set[str] = set()
    wanted = 0
    for agent in entry_agents(entry):
        if not agent.assist_stt or not agent.api_key:
            continue
        keep.add(f"{agent.id}-stt")
        if not _agent_device_active(hass, entry.entry_id, agent.subentry_id):
            continue
        async_add_entities(
            [AiWorkspaceSTTEntity(entry, agent)],
            config_subentry_id=agent.subentry_id or None,
        )
        wanted += 1
    await async_prune_voice_entities(hass, entry.entry_id, "stt", keep)
    _LOGGER.info("Exposing %s speech-to-text engine(s)", wanted)
    await async_refresh_assist_pipelines(hass)


class AiWorkspaceSTTEntity(stt.SpeechToTextEntity):
    """Transcribe Assist audio with the same API key as the chat agent."""

    _attr_icon = "mdi:microphone"
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Speech-to-text"

    def __init__(self, entry: ConfigEntry, agent: Agent) -> None:
        self._entry = entry
        self._agent_id = agent.id
        self._provider = agent.provider
        self._api_key = agent.api_key
        self._api_base = agent.api_base
        self._stt_model = agent.stt_model or default_stt_model(agent.provider)
        self._attr_unique_id = f"{agent.id}-stt"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent:{agent.id}")},
            name=agent.title or entry.title or "AI Workspace",
            manufacturer="AI Workspace",
            model="Agent",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str]:
        return list(_LANGUAGES)

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        return [stt.AudioFormats.WAV, stt.AudioFormats.OGG]

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        return [stt.AudioCodecs.PCM, stt.AudioCodecs.OPUS]

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        return [
            stt.AudioBitRates.BITRATE_8,
            stt.AudioBitRates.BITRATE_16,
            stt.AudioBitRates.BITRATE_24,
            stt.AudioBitRates.BITRATE_32,
        ]

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        return [
            stt.AudioSampleRates.SAMPLERATE_8000,
            stt.AudioSampleRates.SAMPLERATE_11000,
            stt.AudioSampleRates.SAMPLERATE_16000,
            stt.AudioSampleRates.SAMPLERATE_18900,
            stt.AudioSampleRates.SAMPLERATE_22000,
            stt.AudioSampleRates.SAMPLERATE_32000,
            stt.AudioSampleRates.SAMPLERATE_37800,
            stt.AudioSampleRates.SAMPLERATE_44100,
            stt.AudioSampleRates.SAMPLERATE_48000,
        ]

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        return [stt.AudioChannels.CHANNEL_MONO, stt.AudioChannels.CHANNEL_STEREO]

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

    def _audio_file(self, metadata: stt.SpeechMetadata, payload: bytes) -> bytes:
        if metadata.format != stt.AudioFormats.WAV:
            return payload
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(metadata.channel.value)
            wav.setsampwidth(metadata.bit_rate.value // 8)
            wav.setframerate(metadata.sample_rate.value)
            wav.writeframes(payload)
        return buf.getvalue()

    async def _transcribe_gemini(self, metadata: stt.SpeechMetadata, payload: bytes) -> str:
        model = self._stt_model or default_stt_model(API_GEMINI)
        mime = "audio/ogg" if metadata.format == stt.AudioFormats.OGG else "audio/wav"
        url = gemini_generate_content_url(self._api_base, model)
        body = gemini_transcribe_payload(payload, mime, str(metadata.language or ""))
        session = async_get_clientsession(self.hass)
        async with session.post(
            url,
            json=body,
            headers=self._headers(),
            timeout=ClientTimeout(total=45, sock_connect=10),
        ) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                detail = raw.decode("utf-8", errors="replace")[:300]
                _LOGGER.warning("Speech-to-text HTTP %s: %s", resp.status, detail)
                return ""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return ""
        return gemini_response_text(data if isinstance(data, dict) else {})

    async def _transcribe_openai(self, metadata: stt.SpeechMetadata, payload: bytes) -> str:
        form = FormData()
        form.add_field(
            "file",
            payload,
            filename=f"speech.{metadata.format.value}",
            content_type="application/octet-stream",
        )
        form.add_field("model", self._stt_model or default_stt_model(self._provider))
        form.add_field("response_format", "json")
        lang = str(metadata.language or "").split("-", 1)[0].strip()
        if lang:
            form.add_field("language", lang)
        session = async_get_clientsession(self.hass)
        async with session.post(
            f"{self._base()}/audio/transcriptions",
            data=form,
            headers=self._headers(),
            timeout=ClientTimeout(total=45, sock_connect=10),
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status >= 400:
                _LOGGER.warning("Speech-to-text HTTP %s: %s", resp.status, body)
                return ""
        return str((body or {}).get("text") or "").strip()

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        audio = bytearray()
        async for chunk in stream:
            audio.extend(chunk)
        payload = self._audio_file(metadata, bytes(audio))
        if not payload:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            if self._provider == API_GEMINI:
                text = await self._transcribe_gemini(metadata, payload)
            else:
                text = await self._transcribe_openai(metadata, payload)
        except Exception:
            _LOGGER.exception("Speech-to-text failed")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        if not text:
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        return stt.SpeechResult(text, stt.SpeechResultState.SUCCESS)
