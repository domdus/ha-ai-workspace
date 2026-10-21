"""Speech through Home Assistant engines. Playback does not need HTTPS. Recording does."""

from __future__ import annotations

import base64
import re
import wave
from io import BytesIO

from homeassistant.core import HomeAssistant

from .const import DOMAIN, STT_BROWSER, TTS_OFF, is_placeholder_tts

_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARK = re.compile(r"[*_`#~]+")
_ARROW = re.compile(r"[→➡➜➤▶►▸▹↦⇒]+")
_RULE = re.compile(r"^\s*[-*_]{3,}\s*$", re.MULTILINE)
_PCM_RATE = re.compile(r"rate=(\d+)", re.I)


def pcm_wav(pcm: bytes, *, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM in a WAV header so Home Assistant can play it."""
    buf = BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(max(1, int(channels)))
        handle.setsampwidth(max(1, int(sample_width)))
        handle.setframerate(max(1, int(sample_rate)))
        handle.writeframes(pcm)
    return buf.getvalue()


def gemini_speech_style(speed: float) -> str:
    """Gemini TTS has no numeric speed field. Map 1×–4× onto speech_metadata.style."""
    try:
        value = float(speed)
    except (TypeError, ValueError):
        return ""
    if abs(value - 1.0) < 0.05:
        return ""
    if value >= 3.5:
        return "speaking extremely fast"
    if value >= 2.5:
        return "speaking very rapidly"
    if value >= 1.75:
        return "speaking rapidly"
    if value >= 1.4:
        return "speaking quickly"
    if value > 1.05:
        return "speaking slightly quickly"
    if value <= 0.4:
        return "speaking extremely slowly"
    if value <= 0.7:
        return "speaking slowly"
    return "speaking slightly slowly"


def gemini_speech_payload(text: str, voice: str, language: str = "", speed: float = 1.0) -> dict:
    from .const import DEFAULT_GEMINI_TTS_VOICE, gemini_speech_language

    spoken = gemini_speech_language(language)
    name = str(voice or DEFAULT_GEMINI_TTS_VOICE).strip() or DEFAULT_GEMINI_TTS_VOICE
    config: dict = {
        "responseModalities": ["AUDIO"],
        "speechConfig": {
            "voiceConfig": {
                "prebuiltVoiceConfig": {"voiceName": name},
            }
        },
    }
    if spoken:
        config["speechConfig"]["languageCode"] = spoken
    part: dict = {"text": str(text or "")}
    style = gemini_speech_style(speed)
    if style:
        part["speech_metadata"] = {"style": style}
    return {
        "contents": [{"role": "user", "parts": [part]}],
        "generationConfig": config,
    }


def gemini_transcribe_payload(audio: bytes, mime: str, language: str = "") -> dict:
    from .const import gemini_speech_language

    spoken = gemini_speech_language(language) if str(language or "").strip() else ""
    if spoken:
        instruction = (
            f"Transcribe this audio. The spoken language is {spoken}. "
            "Reply with the transcript only. Do not add commentary, labels, or quotation marks."
        )
    else:
        instruction = (
            "Transcribe this audio. Reply with the transcript only. "
            "Do not add commentary, labels, or quotation marks."
        )
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": instruction},
                    {
                        "inlineData": {
                            "mimeType": str(mime or "audio/wav"),
                            "data": base64.b64encode(bytes(audio or b"")).decode("ascii"),
                        }
                    },
                ],
            }
        ]
    }


def gemini_response_text(payload: dict) -> str:
    """Plain text from a Gemini generateContent reply, skipping thought parts."""
    if not isinstance(payload, dict):
        return ""
    bits: list[str] = []
    for cand in payload.get("candidates") or []:
        content = cand.get("content") if isinstance(cand, dict) else None
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict) or part.get("thought"):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                bits.append(text.strip())
    return "\n".join(bits).strip()


def gemini_inline_audio(payload: dict) -> bytes:
    """Decode Gemini generateContent audio (WAV or raw PCM) to a WAV body."""
    if not isinstance(payload, dict):
        return b""
    for cand in payload.get("candidates") or []:
        content = cand.get("content") if isinstance(cand, dict) else None
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if not isinstance(inline, dict):
                continue
            raw = inline.get("data")
            if not raw:
                continue
            try:
                audio = base64.b64decode(raw)
            except (ValueError, TypeError):
                continue
            if not audio:
                continue
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "")
            if audio.startswith(b"RIFF") or "wav" in mime.casefold():
                return audio
            rate = 24000
            found = _PCM_RATE.search(mime)
            if found:
                rate = int(found.group(1))
            return pcm_wav(audio, sample_rate=rate)
    return b""


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


def speech_text(text: str, *, natural: bool = True) -> str:
    """Plain words for TTS — skip tables, markdown, links, and decorative symbols."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    if not natural:
        return raw[:4000]
    out = _without_tables(raw)
    out = _LINK.sub(r"\1", out)
    out = _URL.sub("", out)
    out = _MARK.sub("", out)
    out = _ARROW.sub(" ", out)
    out = _RULE.sub("", out)
    out = re.sub(r"^\s*>\s?", "", out, flags=re.MULTILINE)
    lines = [" ".join(line.split()) for line in out.splitlines()]
    return "\n".join(line for line in lines if line).strip()[:4000]


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
        device = getattr(entity, "device_info", None) or {}
        device_name = ""
        if isinstance(device, dict):
            device_name = str(device.get("name") or "").strip()
        else:
            device_name = str(getattr(device, "name", "") or "").strip()
        if device_name and name and name.casefold() not in device_name.casefold():
            name = f"{device_name} {name}"
        elif device_name:
            name = device_name
        options.append({"value": entity_id, "label": name})
    for engine_id, provider in legacy.items():
        label = str(getattr(provider, "name", "") or engine_id)
        options.append({"value": str(engine_id), "label": label})
    return options


def _tts_engine_exists(hass: HomeAssistant, engine: str) -> bool:
    chosen = str(engine or "").strip()
    if not chosen or chosen == TTS_OFF:
        return False
    try:
        from homeassistant.helpers import entity_registry as er

        row = er.async_get(hass).async_get(chosen)
    except Exception:
        row = None
    if row is not None:
        return row.domain == "tts" and row.disabled_by is None
    try:
        from homeassistant.components.tts import DATA_COMPONENT, DATA_TTS_MANAGER

        component = hass.data.get(DATA_COMPONENT)
        for entity in getattr(component, "entities", []) or []:
            if str(getattr(entity, "entity_id", "") or "") == chosen:
                return True
        manager = hass.data.get(DATA_TTS_MANAGER)
        providers = getattr(manager, "providers", {}) if manager is not None else {}
        if chosen in providers:
            return True
    except Exception:
        pass
    try:
        return hass.states.get(chosen) is not None
    except Exception:
        return False


def resolved_overlay_tts(hass: HomeAssistant, engine: str) -> str:
    """Keep the saved overlay voice. Off if that engine is gone."""
    chosen = str(engine or "").strip() or TTS_OFF
    if chosen == TTS_OFF:
        return TTS_OFF
    if _tts_engine_exists(hass, chosen):
        return chosen
    return TTS_OFF


def overlay_tts_heavy(hass: HomeAssistant, engine: str) -> bool:
    """True when overlay TTS is an AI Workspace OpenAI-style engine (slow per clip)."""
    chosen = str(engine or "").strip()
    if not chosen or chosen == TTS_OFF or is_placeholder_tts(chosen):
        return False
    try:
        from homeassistant.helpers import entity_registry as er

        row = er.async_get(hass).async_get(chosen)
    except Exception:
        row = None
    if row is None:
        return False
    return str(getattr(row, "platform", "") or "") == DOMAIN


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


async def async_speak(
    hass: HomeAssistant,
    engine_id: str,
    text: str,
    language: str,
    *,
    natural: bool = True,
) -> tuple[bytes, str]:
    from homeassistant.components.tts import async_create_stream

    try:
        from homeassistant.components.tts.helper import get_engine_instance
    except ImportError:
        get_engine_instance = None

    message = speech_text(text, natural=natural)
    if not message:
        return b"", ""
    engine = get_engine_instance(hass, engine_id) if get_engine_instance else None
    spoken = _engine_language(engine, language, str(hass.config.language or "en")) if engine is not None else (
        language or hass.config.language or "en"
    )
    getter = getattr(engine, "async_internal_get_tts_audio", None) if engine is not None else None
    if callable(getter):
        options = dict(getattr(engine, "default_options", None) or {})
        extension, data = await getter(message, spoken or "", options)
        if not data:
            raise RuntimeError("Text-to-speech returned no audio.")
        ext = str(extension or "mp3").lstrip(".")
        mime = f"audio/{'mpeg' if ext == 'mp3' else ext}"
        return data, mime
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
