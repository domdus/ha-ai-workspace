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


def test_match_maps_locale_to_engine_tag() -> None:
    voice = _load("voice", "voice.py")
    assert voice.match_speech_language("de-DE", ["de", "en"], "en") == "de"
    assert voice.match_speech_language("de-DE", ["de_DE", "en_US"], "en") == "de_DE"
    assert voice.match_speech_language("en", ["en", "de"], "en") == "en"
    assert voice.match_speech_language("pt-BR", ["pt_BR"], "en") == "pt_BR"


def test_speech_text_drops_links() -> None:
    voice = _load("voice", "voice.py")
    assert (
        voice.speech_text("The [pump](/config/entities/switch.pump) is on. https://example.local/x")
        == "The pump is on."
    )


def test_pipeline_voice_uses_ha_engines_then_preferred() -> None:
    _load("const", "const.py")
    pipes = _load("assist_pipelines", "assist_pipelines.py")
    ours = pipes.resolve_pipeline_voice("stt.whisper", "tts.google_translate_en_com", language="de")
    assert ours["stt_engine"] == "stt.whisper"
    assert ours["tts_engine"] == "tts.google_translate_en_com"
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
    empty = pipes.resolve_pipeline_voice("browser", "off", language="de")
    assert empty["stt_engine"] is None
    assert empty["tts_engine"] is None
