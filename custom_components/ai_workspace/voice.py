"""Speech through Home Assistant engines. Playback does not need HTTPS. Recording does."""

from __future__ import annotations

import wave
from io import BytesIO

from homeassistant.core import HomeAssistant

from .const import STT_BROWSER, TTS_OFF


async def async_speech_engines(hass: HomeAssistant, kind: str) -> list[dict[str, str]]:
    options = [{"value": STT_BROWSER if kind == "stt" else TTS_OFF, "label": "Browser" if kind == "stt" else "Off"}]
    try:
        if kind == "stt":
            from homeassistant.components.stt import DATA_COMPONENT, DATA_PROVIDERS

            legacy = hass.data.get(DATA_PROVIDERS) or {}
        else:
            from homeassistant.components.tts import DATA_COMPONENT, DATA_TTS_MANAGER

            manager = hass.data.get(DATA_TTS_MANAGER)
            legacy = getattr(manager, "providers", {}) if manager is not None else {}
    except ImportError:
        return options
    component = hass.data.get(DATA_COMPONENT)
    entities = getattr(component, "entities", []) if component is not None else []
    for entity in entities:
        entity_id = str(getattr(entity, "entity_id", "") or "")
        if not entity_id:
            continue
        name = str(getattr(entity, "name", "") or entity_id)
        options.append({"value": entity_id, "label": name})
    for engine_id, provider in legacy.items():
        label = str(getattr(provider, "name", "") or engine_id)
        options.append({"value": str(engine_id), "label": label})
    return options


def _wav_meta(audio: bytes) -> tuple[int, int, int]:
    with wave.open(BytesIO(audio), "rb") as handle:
        return handle.getnchannels(), handle.getframerate(), handle.getsampwidth() * 8


async def async_transcribe(hass: HomeAssistant, engine_id: str, audio: bytes, language: str) -> str:
    from homeassistant.components.stt import (
        AudioBitRates,
        AudioChannels,
        AudioCodecs,
        AudioFormats,
        AudioSampleRates,
        SpeechMetadata,
        SpeechResultState,
        async_get_speech_to_text_engine,
    )

    engine = async_get_speech_to_text_engine(hass, engine_id)
    if engine is None:
        raise RuntimeError("That speech-to-text engine is not available.")
    channels, rate, bits = _wav_meta(audio)
    channel = AudioChannels.CHANNEL_MONO if channels == 1 else AudioChannels.CHANNEL_STEREO
    sample = next((item for item in AudioSampleRates if int(item) == rate), None)
    bit = next((item for item in AudioBitRates if int(item) == bits), None)
    if sample is None or bit is None:
        raise RuntimeError("Recorded audio is not a sample rate this engine accepts.")

    async def chunks():
        yield audio

    metadata = SpeechMetadata(
        language=language or hass.config.language or "en",
        format=AudioFormats.WAV,
        codec=AudioCodecs.PCM,
        bit_rate=bit,
        sample_rate=sample,
        channel=channel,
    )
    result = await engine.async_process_audio_stream(metadata, chunks())
    if getattr(result, "result", None) != SpeechResultState.SUCCESS:
        raise RuntimeError("Speech-to-text did not understand that.")
    return str(getattr(result, "text", "") or "").strip()


async def async_speak(hass: HomeAssistant, engine_id: str, text: str, language: str) -> str:
    from homeassistant.components.tts import async_create_stream

    message = str(text or "").strip()
    if not message:
        return ""
    stream = async_create_stream(hass, engine_id, language or hass.config.language or "en")
    stream.async_set_message(message[:4000])
    return str(getattr(stream, "url", "") or "")
