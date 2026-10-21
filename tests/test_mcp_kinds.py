import importlib.util
from pathlib import Path


def _const():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "const.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_const", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_provider_model_defaults_and_dropdown_choices() -> None:
    const = _const()
    assert const.default_api_model("openai") == "gpt-5"
    assert const.default_api_model("anthropic") == "claude-sonnet-5-5"
    assert const.default_api_model("gemini") == "gemini-3.8-flash"
    assert const.default_api_model("deepseek") == "deepseek-flash"
    assert const.default_api_model("qwen") == "qwen3.7-plus"
    assert const.default_api_model("xai") == "grok-4.7"
    assert const.default_api_model("openrouter") == "openai/gpt-5"
    assert const.default_api_model("ollama") == "llama3.2"
    assert const.default_api_model("cursor") == "composer-2.5"
    assert const.default_api_model("azure") == ""
    for kind in ("openai", "anthropic", "gemini", "deepseek", "qwen", "xai", "ollama", "cursor"):
        choices = const.api_model_choices(kind)
        assert choices
        assert choices[0] == const.default_api_model(kind)
    assert const.api_model_choices("openrouter") == []
    assert const.api_model_choices("azure") == []
    assert const.api_model_choices("compatible") == []


def test_cleared_model_uses_fallback_not_the_old_value() -> None:
    const = _const()
    assert const.submitted_model({"model": ""}) == ""
    assert const.submitted_model({}) == ""
    assert const.submitted_model(None) == ""
    assert const.submitted_model({"model": "  grok-4.7  "}) == "grok-4.7"


def test_assist_defaults_on_for_existing_off_for_new() -> None:
    const = _const()
    assert const.assist_enabled({}) is True
    assert const.assist_enabled({}, new=True) is False
    assert const.assist_enabled({"assist": False}) is False
    assert const.assist_enabled({"assist": True}, new=True) is True
    assert const.assist_enabled({"assist": False}, new=True) is False


def test_speech_to_text_defaults_on_for_openai_style_agents() -> None:
    const = _const()
    assert const.provider_supports_stt("openai")
    assert const.provider_supports_stt("openrouter")
    assert const.provider_supports_stt("compatible")
    assert const.provider_supports_stt("gemini")
    assert not const.provider_supports_stt("cursor")
    assert not const.provider_supports_stt("anthropic")
    assert not const.provider_supports_stt("azure")
    assert const.default_stt_model("openai") == "gpt-4o-mini-transcribe"
    assert const.default_stt_model("openrouter") == "openai/whisper-1"
    assert const.default_stt_model("compatible") == "whisper-1"
    assert const.default_stt_model("gemini") == "gemini-3.8-flash"
    assert const.assist_stt_enabled({}, "openai") is True
    assert const.assist_stt_enabled({"api_provider": "openai"}) is True
    assert const.assist_stt_enabled({"assist_stt": False}, "openai") is False
    assert const.assist_stt_enabled({"assist_stt": True}, "openai") is True
    assert const.assist_stt_enabled({}, "cursor") is False
    assert const.assist_stt_enabled({"assist_stt": True}, "cursor") is False
    assert const.assist_stt_enabled({}, "gemini") is False
    assert const.assist_stt_enabled({}, "gemini", new=True) is True
    assert const.assist_stt_enabled({"assist_stt": True}, "gemini") is True
    assert const.stt_model_choices("openai")[0] == "gpt-4o-mini-transcribe"
    assert const.stt_model_choices("gemini")[0] == "gemini-3.8-flash"
    assert const.resolved_stt_model({}, "openai") == "gpt-4o-mini-transcribe"
    assert const.resolved_stt_model({"stt_model": "whisper-1"}, "openai") == "whisper-1"
    assert const.resolved_stt_model({}, "openrouter") == "openai/whisper-1"
    assert const.resolved_stt_model({}, "gemini") == "gemini-3.8-flash"


def test_text_to_speech_defaults_on_for_openai_style_agents() -> None:
    const = _const()
    assert const.provider_supports_tts("openai")
    assert const.provider_supports_tts("openrouter")
    assert const.provider_supports_tts("compatible")
    assert const.provider_supports_tts("gemini")
    assert not const.provider_supports_tts("cursor")
    assert not const.provider_supports_tts("anthropic")
    assert const.provider_supports_tts_speed("gemini")
    assert const.provider_supports_tts_speed("openai")
    assert const.default_tts_model("openai") == "gpt-4o-mini-tts"
    assert const.default_tts_model("openrouter") == "openai/gpt-4o-mini-tts"
    assert const.default_tts_model("gemini") == "gemini-3.8-flash-tts"
    assert const.assist_tts_enabled({}, "openai") is True
    assert const.assist_tts_enabled({"assist_tts": False}, "openai") is False
    assert const.assist_tts_enabled({}, "cursor") is False
    assert const.assist_tts_enabled({}, "gemini") is False
    assert const.assist_tts_enabled({}, "gemini", new=True) is True
    assert const.assist_tts_enabled({"assist_tts": True}, "gemini") is True
    assert const.resolved_tts_voice({}) == "coral"
    assert const.resolved_tts_voice({"tts_voice": "nova"}) == "nova"
    assert const.resolved_tts_voice({}, "gemini") == "Kore"
    assert const.resolved_tts_voice({"tts_voice": "puck"}, "gemini") == "Puck"
    assert const.resolved_tts_speed({}) == 1.0
    assert const.resolved_tts_speed({"tts_speed": "1.5"}) == 1.5
    assert const.resolved_tts_speed({"tts_speed": "9"}) == 4.0
    assert const.tts_speed_choice(1.0) == "1"
    assert const.tts_speed_choice(1.5) == "1.5"
    assert const.is_placeholder_tts("off")
    assert const.is_placeholder_tts("")
    assert not const.is_placeholder_tts("tts.google_translate_en_com")
    assert not const.is_placeholder_tts("tts.piper")


def test_mcp_dropdown_keeps_detected_saved_and_custom() -> None:
    const = _const()
    assert const.mcp_kind_options({"ha"}, current="coolver") == ["ha", "coolver", "custom"]
    assert const.mcp_kind_options({"ha", "ha_mcp"}) == ["ha", "ha_mcp", "custom"]
    assert const.mcp_kind_options(set()) == ["custom"]
    assert const.mcp_kind_options(set(), current="custom") == ["custom"]


def test_mcp_connection_menu_lists_found_and_skips_already_added() -> None:
    const = _const()
    assert const.mcp_connection_menu({"ha"}) == ["ha", "custom"]
    assert const.mcp_connection_menu({"ha", "ha_mcp"}, used={"ha"}) == ["ha_mcp", "custom"]
    assert const.mcp_connection_menu(set()) == ["custom"]
