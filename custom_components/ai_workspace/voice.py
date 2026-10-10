"""Speech through Home Assistant engines. Playback does not need HTTPS. Recording does."""

from __future__ import annotations

import re
import wave
from io import BytesIO

from homeassistant.core import HomeAssistant

from .const import STT_BROWSER, TTS_OFF

_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARK = re.compile(r"[*_`#]+")


def match_speech_language(requested: str, supported: list[str] | tuple[str, ...] | None, default: str = "") -> str:
    """Map de-DE / de_DE onto what the engine actually lists (de, de_DE, …)."""
    tags = [str(item).strip() for item in (supported or []) if str(item).strip()]
    wanted = str(requested or "").replace("_", "-").strip()
    if wanted and wanted in tags:
        return wanted
    underscored = wanted.replace("-", "_")
    if underscored and underscored in tags:
        return underscored
    primary = wanted.split("-", 1)[0].casefold() if wanted else ""
    if primary:
        for tag in tags:
            norm = tag.replace("_", "-").casefold()
            if norm == wanted.casefold() or norm.split("-", 1)[0] == primary:
                return tag
    if default in tags:
        return default
    if default:
        return default
    return wanted or (tags[0] if tags else "")


_TABLE_LINE = re.compile(
    r"""
    ^\s*
    (
      \|.*\|                                 # | cell | cell |
      | \|?[\s:|-]*---[\s:|-]*               # --- | ---
      | [^\n|]+\s\|\s[^\n|]+(\s\|\s[^\n|]*)* # cell | cell
    )
    \s*$
    """,
    re.VERBOSE,
)


def _without_tables(text: str) -> str:
    """Keep the intro and closing line; skip markdown tables in between."""
    kept: list[str] = []
    for line in str(text or "").splitlines():
        if _TABLE_LINE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def speech_text(text: str) -> str:
    """Plain words for TTS — skip tables, markdown links, and raw URLs."""
    out = _without_tables(str(text or ""))
    out = _LINK.sub(r"\1", out)
    out = _URL.sub("", out)
    out = _MARK.sub("", out)
    return " ".join(out.split())[:4000]


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


def _engine_language(engine, requested: str, fallback: str) -> str:
    supported = list(getattr(engine, "supported_languages", None) or [])
    default = str(getattr(engine, "default_language", "") or "") or fallback
    return match_speech_language(requested or fallback, supported, default)


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
    spoken = _engine_language(engine, language, str(hass.config.language or "en"))

    async def chunks():
        yield audio

    metadata = SpeechMetadata(
        language=spoken or hass.config.language or "en",
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


async def async_speak(hass: HomeAssistant, engine_id: str, text: str, language: str) -> tuple[bytes, str]:
    from homeassistant.components.tts import async_create_stream

    try:
        from homeassistant.components.tts.helper import get_engine_instance
    except ImportError:
        get_engine_instance = None

    message = speech_text(text)
    if not message:
        return b"", ""
    engine = get_engine_instance(hass, engine_id) if get_engine_instance else None
    spoken = _engine_language(engine, language, str(hass.config.language or "en")) if engine is not None else (
        language or hass.config.language or "en"
    )
    stream = async_create_stream(hass, engine_id, spoken or None)
    stream.async_set_message(message)
    chunks = getattr(stream, "async_stream_result", None)
    if not callable(chunks):
        raise RuntimeError("Text-to-speech returned no audio.")
    data = b"".join([piece async for piece in chunks()])
    if not data:
        raise RuntimeError("Text-to-speech returned no audio.")
    ext = str(getattr(stream, "extension", "") or "mp3").lstrip(".")
    mime = str(getattr(stream, "content_type", "") or "") or f"audio/{ext or 'mpeg'}"
    return data, mime
