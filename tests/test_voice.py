import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace"
PKG = "ai_workspace_comp"

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core

if PKG not in sys.modules:
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(ROOT)]
    pkg.__package__ = PKG
    sys.modules[PKG] = pkg


def _load(mod_name: str, file_name: str):
    full = f"{PKG}.{mod_name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, ROOT / file_name)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = PKG
    sys.modules[full] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_tts_languages_include_german_and_map_region() -> None:
    const = _load("const", "const.py")
    voice = _load("voice", "voice.py")
    assert "de" in const.TTS_LANGUAGES
    assert "fr" in const.TTS_LANGUAGES
    assert "it" in const.TTS_LANGUAGES
    assert voice.match_speech_language("de-DE", const.TTS_LANGUAGES, "en") == "de"
    assert voice.match_speech_language("de", const.TTS_LANGUAGES, "en") == "de"


def test_match_maps_locale_to_engine_tag() -> None:
    voice = _load("voice", "voice.py")
    assert voice.match_speech_language("de-DE", ["de", "en"], "en") == "de"
    assert voice.match_speech_language("de-DE", ["de_DE", "en_US"], "en") == "de_DE"
    assert voice.match_speech_language("en", ["en", "de"], "en") == "en"
    assert voice.match_speech_language("pt-BR", ["pt_BR"], "en") == "pt_BR"


def test_speech_text_strips_arrows_and_markdown() -> None:
    voice = _load("voice", "voice.py")
    spoken = voice.speech_text("**Bold** move → next step")
    assert "**" not in spoken
    assert "→" not in spoken
    assert "Bold move next step" in spoken
    assert voice.speech_text("keep stars", natural=False) == "keep stars"


def test_speech_text_drops_links() -> None:
    voice = _load("voice", "voice.py")
    assert (
        voice.speech_text("The [pump](/config/entities/switch.pump) is on. https://example.local/x")
        == "The pump is on."
    )


def test_speech_text_keeps_list_lines() -> None:
    voice = _load("voice", "voice.py")
    spoken = voice.speech_text(
        "Here are your automations:\n"
        "- [Close balcony reminder](/config/automation/edit/close_balcony_reminder) — on\n"
        "- [Hallway motion light](/config/automation/edit/hallway_motion_light) — on"
    )
    assert "\n" in spoken
    assert spoken.splitlines()[0] == "Here are your automations:"
    assert "Close balcony reminder — on" in spoken
    assert "/config/" not in spoken


def test_speech_text_skips_tables_keeps_intro_and_close() -> None:
    voice = _load("voice", "voice.py")
    spoken = voice.speech_text(
        "54 Automatisierungen (43 aktiv · 11 aus):\n\n"
        "| Automatisierung | Status |\n"
        "| --- | --- |\n"
        "| 00:00 | aktiv |\n"
        "| Bewässerung - Balkon | aktiv |\n"
        "| Wäsche fertig | aktiv |\n\n"
        "Aktiv = Schalter der Automatisierung ist an (on), aus = aus (off)."
    )
    assert spoken.startswith("54 Automatisierungen")
    assert "Wäsche fertig" not in spoken
    assert "00:00" not in spoken
    assert spoken.endswith("aus = aus (off).") or "aus = aus (off)." in spoken


def test_pipeline_voice_uses_ha_engines_then_preferred() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    ours = pipes.resolve_pipeline_voice("stt.whisper", "tts.piper", language="de")
    assert ours["stt_engine"] == "stt.whisper"
    assert ours["tts_engine"] == "tts.piper"
    assert ours["stt_language"] == "de"
    borrowed = pipes.resolve_pipeline_voice(
        "browser",
        "off",
        language="de",
        preferred_stt="stt.cloud",
        preferred_stt_language="en",
        preferred_tts="tts.piper",
        preferred_tts_language="de",
        preferred_tts_voice="de_DE-thorsten-medium",
    )
    assert borrowed["stt_engine"] == "stt.cloud"
    assert borrowed["tts_engine"] == "tts.piper"
    assert borrowed["stt_language"] == "en"
    assert borrowed["tts_voice"] == "de_DE-thorsten-medium"
    ours_voice = pipes.resolve_pipeline_voice(
        "browser",
        "tts.open_ai_text_to_speech",
        language="de",
        preferred_tts="tts.piper",
        preferred_tts_voice="de_DE-thorsten-medium",
        engine_tts_voice="ash",
    )
    assert ours_voice["tts_engine"] == "tts.open_ai_text_to_speech"
    assert ours_voice["tts_voice"] == "ash"
    empty = pipes.resolve_pipeline_voice("browser", "off", language="de")
    assert empty["stt_engine"] is None
    assert empty["tts_engine"] is None
    google = pipes.resolve_pipeline_voice(
        "browser",
        "tts.google_translate_en_com",
        language="de",
        fallback_tts="tts.open_ai_text_to_speech",
    )
    assert google["tts_engine"] == "tts.google_translate_en_com"
    discovered = pipes.resolve_pipeline_voice(
        "browser",
        "off",
        language="de",
        fallback_stt="stt.open_ai_speech_to_text",
        fallback_stt_language="de-DE",
    )
    assert discovered["stt_engine"] == "stt.open_ai_speech_to_text"
    assert discovered["stt_language"] == "de-DE"


def test_pick_assist_stt_prefers_our_engine_then_official_openai() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    engines = [
        ("stt.piper_local", "wyoming", "wyoming-stt"),
        ("stt.openai_conversation_stt", "openai_conversation", "stt-sub"),
        ("stt.cursor_speech_to_text", "ai_workspace", "cursor-1-stt"),
        ("stt.open_ai_speech_to_text", "ai_workspace", "openai-1-stt"),
    ]
    assert (
        pipes.pick_assist_stt(setting="stt.whisper", engines=engines)
        == "stt.whisper"
    )
    assert pipes.pick_assist_stt(setting="browser", engines=engines, conversation_unique_id="openai-1") == (
        "stt.open_ai_speech_to_text"
    )
    assert pipes.pick_assist_stt(setting="browser", engines=engines, conversation_unique_id="cursor-1") == (
        "stt.cursor_speech_to_text"
    )
    cursor_pipeline = [row for row in engines if row[2] != "cursor-1-stt"]
    assert pipes.pick_assist_stt(setting="browser", engines=cursor_pipeline, conversation_unique_id="cursor-agent") == (
        "stt.open_ai_speech_to_text"
    )
    without_ours = [row for row in engines if row[1] != "ai_workspace"]
    assert pipes.pick_assist_stt(setting="browser", engines=without_ours) == "stt.openai_conversation_stt"
    assert pipes.pick_assist_stt(setting="browser", engines=[("stt.cloud", "cloud", "cloud")]) == "stt.cloud"
    assert pipes.pick_assist_stt(setting="browser", preferred="stt.cloud", engines=[]) == "stt.cloud"
    assert pipes.pick_assist_stt(setting="browser") is None


def test_tts_language_for_maps_german_region() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    engines = [("tts.open_ai_text_to_speech", "ai_workspace", "openai-1-tts")]
    assert pipes._tts_language_for("tts.open_ai_text_to_speech", "de-DE", engines) == "de"
    assert pipes._tts_language_for("tts.open_ai_text_to_speech", "de", engines) == "de"


def test_pick_assist_tts_keeps_google_translate() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    engines = [
        ("tts.google_translate_en_com", "google_translate", "google"),
        ("tts.openai_conversation_tts", "openai_conversation", "tts-sub"),
        ("tts.open_ai_text_to_speech", "ai_workspace", "openai-1-tts"),
        ("tts.piper", "wyoming", "piper"),
    ]
    assert pipes.pick_assist_tts(setting="tts.piper", engines=engines) == "tts.piper"
    assert pipes.pick_assist_tts(setting="tts.google_translate_en_com", engines=engines) == (
        "tts.google_translate_en_com"
    )
    assert pipes.pick_assist_tts(setting="off", engines=engines, conversation_unique_id="openai-1") == (
        "tts.open_ai_text_to_speech"
    )


def test_existing_engine_drops_removed_stt() -> None:
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    engines = [("stt.whisper", "wyoming", "whisper")]
    assert pipes._existing_engine("stt.whisper", engines) == "stt.whisper"
    assert pipes._existing_engine("stt.open_ai_speech_to_text", engines) == ""
    assert pipes._existing_engine("browser", engines) == "browser"


def test_keep_pipeline_engine_leaves_none_when_gone() -> None:
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    engines = [("tts.google_translate_en_com", "google_translate", "google")]
    assert pipes._keep_pipeline_engine("tts.google_translate_en_com", engines) == "tts.google_translate_en_com"
    assert pipes._keep_pipeline_engine("tts.open_ai_text_to_speech", engines) is None
    assert pipes._keep_pipeline_engine(None, engines) is None


def test_assist_pipeline_keeps_agent_title() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    assert pipes.conversation_pipeline_name("AI Workspace", "Cursor") == "Cursor"
    assert pipes.conversation_pipeline_name("", None, "OpenAI") == "OpenAI"
    assert pipes.conversation_pipeline_name("Ollama", "AI Workspace") == "Ollama"
    assert pipes.conversation_pipeline_name("AI Workspace", "Agent", "") == "AI Workspace"


def test_gemini_tts_url_strips_openai_compat_suffix() -> None:
    const = _load("const", "const.py")
    url = const.gemini_generate_content_url("", "gemini-3.8-flash-tts")
    assert url.endswith("/v1beta/models/gemini-3.8-flash-tts:generateContent")
    assert "/openai/" not in url
    custom = const.gemini_generate_content_url(
        "https://example.googleapis.com/v1beta/openai",
        "gemini-2.5-flash-preview-tts",
    )
    assert custom == "https://example.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
    assert const.gemini_speech_language("de") == "de-DE"
    assert const.gemini_speech_language("de-DE") == "de-DE"
    assert const.gemini_speech_language("en") == "en-US"


def test_gemini_inline_audio_wraps_pcm_and_keeps_wav() -> None:
    import base64
    import wave
    from io import BytesIO

    voice = _load("voice", "voice.py")
    pcm = b"\x01\x00" * 24
    wrapped = voice.pcm_wav(pcm, sample_rate=24000)
    with wave.open(BytesIO(wrapped), "rb") as handle:
        assert handle.getframerate() == 24000
        assert handle.getnchannels() == 1
        assert handle.readframes(24) == pcm
    body = voice.gemini_speech_payload("Hallo", "Puck", "de")
    assert body["contents"][0]["parts"][0]["text"] == "Hallo"
    assert body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    assert body["generationConfig"]["speechConfig"]["languageCode"] == "de-DE"
    encoded = base64.b64encode(pcm).decode("ascii")
    audio = voice.gemini_inline_audio(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "audio/L16;codec=pcm;rate=24000",
                                    "data": encoded,
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    with wave.open(BytesIO(audio), "rb") as handle:
        assert handle.readframes(24) == pcm
    wav_b64 = base64.b64encode(wrapped).decode("ascii")
    kept = voice.gemini_inline_audio(
        {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": wav_b64}}]}}]}
    )
    assert kept.startswith(b"RIFF")


def test_gemini_transcribe_payload_and_response_text() -> None:
    import base64

    voice = _load("voice", "voice.py")
    audio = b"RIFF" + b"\x00" * 12
    body = voice.gemini_transcribe_payload(audio, "audio/wav", "de")
    parts = body["contents"][0]["parts"]
    assert "de-DE" in parts[0]["text"]
    assert "transcript only" in parts[0]["text"].casefold()
    assert parts[1]["inlineData"]["mimeType"] == "audio/wav"
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == audio
    text = voice.gemini_response_text(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "hmm"},
                            {"text": "  Licht an.  "},
                        ]
                    }
                }
            ]
        }
    )
    assert text == "Licht an."
    assert voice.gemini_response_text({}) == ""
