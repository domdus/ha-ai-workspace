import json
import re
from pathlib import Path

DOMAIN = "ai_workspace"
PANEL_URL = "ai-workspace"
PANEL_ELEMENT = "ha-ai-workspace-panel"
STATIC_URL = "/ai_workspace/static"
VERSION = json.loads(
    (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
)["version"]
# Restore from the snapshot Change History took before the write.
ACTIVITY_ROLLBACK = True
DEFAULT_CHANGE_HISTORY_TTL_DAYS = 7
CHANGE_HISTORY_TTL_MIN_DAYS = 1
CHANGE_HISTORY_TTL_MAX_DAYS = 90


def change_history_ttl_days(value) -> int:
    try:
        days = int(value if value is not None else DEFAULT_CHANGE_HISTORY_TTL_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_CHANGE_HISTORY_TTL_DAYS
    return max(CHANGE_HISTORY_TTL_MIN_DAYS, min(days, CHANGE_HISTORY_TTL_MAX_DAYS))


def activity_restore_expired(created_at: str, *, days: int, now=None) -> bool:
    """True when Rollback for this row has passed the configured TTL."""
    from datetime import datetime, timedelta, timezone

    days = change_history_ttl_days(days)
    try:
        when = datetime.fromisoformat(str(created_at or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp - when >= timedelta(days=days)


def activity_restore_flags(
    *,
    snapshot: bool,
    undone: bool,
    admin: bool,
    expired: bool = False,
) -> tuple[bool, bool]:
    """One way to undo a row: Rollback from the snapshot, or Undo with agent when there is none.

    A change the agent created has no earlier version to put back, so only the agent can undo it.
    """
    can_rollback = bool(ACTIVITY_ROLLBACK and snapshot and not undone and not expired)
    ask_restore = bool(admin and not undone and not expired and not can_rollback)
    return can_rollback, ask_restore


OVERLAY_JS = f"{STATIC_URL}/overlay.js?v={VERSION}"
PANEL_JS = f"{STATIC_URL}/panel.js?v={VERSION}"
DEFAULT_MODEL = "composer-2.5"
API_OPENAI = "openai"
API_ANTHROPIC = "anthropic"
API_GEMINI = "gemini"
API_DEEPSEEK = "deepseek"
API_QWEN = "qwen"
API_XAI = "xai"
API_OPENROUTER = "openrouter"
API_OLLAMA = "ollama"
API_AZURE = "azure"
API_COMPATIBLE = "compatible"
API_PROVIDERS = {
    API_OPENAI: "OpenAI",
    API_ANTHROPIC: "Claude (Anthropic)",
    API_GEMINI: "Google Gemini",
    API_DEEPSEEK: "DeepSeek",
    API_QWEN: "Qwen (Alibaba)",
    API_XAI: "Grok (xAI)",
    API_OPENROUTER: "OpenRouter",
    API_OLLAMA: "Local Ollama",
    API_AZURE: "Azure OpenAI",
    API_COMPATIBLE: "OpenAI-compatible (custom base URL)",
}
API_SHORT_LABELS = {
    API_OPENAI: "OpenAI",
    API_ANTHROPIC: "Claude",
    API_GEMINI: "Gemini",
    API_DEEPSEEK: "DeepSeek",
    API_QWEN: "Qwen",
    API_XAI: "Grok",
    API_OPENROUTER: "OpenRouter",
    API_OLLAMA: "Ollama",
    API_AZURE: "Azure OpenAI",
    API_COMPATIBLE: "OpenAI-compatible",
}
_API_DEFAULT_MODEL = {
    API_OPENAI: "gpt-5",
    API_ANTHROPIC: "claude-sonnet-5-5",
    API_GEMINI: "gemini-3.8-flash",
    API_DEEPSEEK: "deepseek-flash",
    API_QWEN: "qwen3.7-plus",
    API_XAI: "grok-4.7",
    API_OPENROUTER: "openai/gpt-5",
    API_OLLAMA: "llama3.2",
    API_AZURE: "",
    API_COMPATIBLE: "gpt-5",
}
# OpenRouter, Azure, and custom OpenAI-compatible servers stay free-text.
_API_MODEL_CHOICES = {
    "cursor": ["composer-2.5"],
    API_OPENAI: ["gpt-5", "gpt-6-astra", "gpt-6.1-sol", "gpt-5-mini", "gpt-4.1"],
    API_ANTHROPIC: ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-sonnet-4-5"],
    API_GEMINI: ["gemini-3.8-flash", "gemini-2.5-pro", "gemini-2.5-flash"],
    API_DEEPSEEK: ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat"],
    API_QWEN: ["qwen3.7-plus", "qwen3.8-max", "qwen3.8-flash", "qwen-plus"],
    API_XAI: ["grok-4.7", "grok-4.3", "grok-4"],
    API_OLLAMA: ["llama3.2", "llama3.1", "qwen2.5", "mistral", "gemma3"],
}
_API_DEFAULT_BASE = {
    API_OPENAI: "https://api.openai.com/v1",
    API_ANTHROPIC: "https://api.anthropic.com/v1",
    API_GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai",
    API_DEEPSEEK: "https://api.deepseek.com/v1",
    API_QWEN: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    API_XAI: "https://api.x.ai/v1",
    API_OPENROUTER: "https://openrouter.ai/api/v1",
    API_OLLAMA: "http://127.0.0.1:11434/v1",
}
DEFAULT_API_MODEL = _API_DEFAULT_MODEL[API_OPENAI]
DEFAULT_ANTHROPIC_MODEL = _API_DEFAULT_MODEL[API_ANTHROPIC]
CLOUD_ONLY_MODELS = frozenset(
    m
    for m in {
        *_API_DEFAULT_MODEL.values(),
        *[
            name
            for kind, names in _API_MODEL_CHOICES.items()
            if kind not in {API_OLLAMA, "cursor"}
            for name in names
        ],
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "claude-opus-4-5",
        "claude-haiku-4-5",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "deepseek-reasoner",
        "qwen-max",
        "qwen-turbo",
        "grok-3",
        "openai/gpt-4.1",
        "llama3.2",
    }
    if m
)
EFFORT_DEFAULT = "default"
EFFORT_FAST = "fast"
EFFORT_HIGH = "high"
EFFORT_HIGH_FAST = "high_fast"
EFFORTS = {
    EFFORT_DEFAULT: "Default",
    EFFORT_FAST: "Fast",
    EFFORT_HIGH: "High",
    EFFORT_HIGH_FAST: "High fast",
}
SUBENTRY_AGENT = "agent"
SUBENTRY_MCP = "mcp"
SUBENTRY_USAGE = "usage"


def usage_device_ident(entry_id: str) -> str:
    """Device identifiers for workspace-wide usage sensors (not an agent subentry)."""
    return f"{entry_id}:usage"


def is_usage_sensor_unique_id(unique_id: str | None) -> bool:
    """True for workspace/agent usage sensors, not conversation/STT/TTS."""
    return "_usage_" in str(unique_id or "")


CONF_AGENT_ID = "agent_id"
CONF_RUNTIME_TOKEN = "runtime_token"
STT_BROWSER = "browser"
TTS_OFF = "off"
DEFAULT_AZURE_API_VERSION = "2024-10-21"
BORROW_DOMAINS = {
    "open_router": API_OPENROUTER,
    "openai_conversation": API_OPENAI,
    "anthropic": API_ANTHROPIC,
    "google_generative_ai_conversation": API_GEMINI,
    "ollama": API_OLLAMA,
    "azure_openai_sdk_conversation": API_AZURE,
    "azure_openai": API_AZURE,
    "azure_openai_conversation": API_AZURE,
}


def default_api_model(kind: str) -> str:
    if kind == "cursor":
        return DEFAULT_MODEL
    return _API_DEFAULT_MODEL.get(kind, DEFAULT_API_MODEL)


def _load_catalog() -> dict[str, list[str]]:
    """Chat model ids from model_catalog.json (scripts/sync_model_prices.py). Read at import, off the event loop."""
    try:
        raw = json.loads(Path(__file__).with_name("model_catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): [str(n) for n in v if str(n).strip()] for k, v in raw.items() if isinstance(v, list)}


_CATALOG = _load_catalog()


def model_catalog(kind: str) -> list[str]:
    return list(_CATALOG.get(kind, ()))


def api_model_picks(kind: str) -> list[str]:
    return list(_API_MODEL_CHOICES.get(kind, ()))


def api_model_choices(kind: str) -> list[str]:
    """Picks first, then every other id the provider is known to offer."""
    out: list[str] = []
    for name in (*_API_MODEL_CHOICES.get(kind, ()), *model_catalog(kind)):
        if name not in out:
            out.append(name)
    return out


def default_api_base(kind: str) -> str:
    return _API_DEFAULT_BASE.get(kind, "")


DEFAULT_TITLE = "AI Workspace"
CONF_MCP_URL = "mcp_url"
CONF_MCP_KIND = "mcp_kind"
CONF_MCP_TOKEN = "mcp_token"
CONF_MCP_EXTRA = "mcp_extra"
CONF_CURSOR_API_KEY = "cursor_api_key"
CONF_MODEL = "model"
CONF_ENABLE_OVERLAY = "enable_overlay"
CONF_ENABLE_SIDEBAR = "enable_sidebar"
CONF_ENABLE_DICTATE = "enable_dictate"
CONF_ALLOW_USERS = "allow_users"
CONF_HOUSE_MAP = "house_map"
CONF_NOTES = "notes"
CONF_NOTES_TEXT = "notes_text"
CONF_SHORTEN_MCP_RESULTS = "shorten_mcp_results"
CONF_CHANGE_HISTORY = "change_history"
CONF_CHANGE_HISTORY_TTL_DAYS = "change_history_ttl_days"
CONF_TRACK_USAGE = "track_usage"
CONF_SHOW_CHAT_USAGE = "show_chat_usage"
CONF_HA_USAGE_SENSORS = "ha_usage_sensors"
CONF_CROSS_CHAT = "cross_chat"
CONF_DEFAULT_AGENT = "default_agent"
CONF_MODEL_SWITCHER = "model_switcher"
CONF_UI_THEME = "ui_theme"
UI_THEME_STANDARD = "standard"
UI_THEME_HA_COMPONENTS = "ha_components"
UI_THEMES = (UI_THEME_STANDARD, UI_THEME_HA_COMPONENTS)


def ui_theme_of(value) -> str:
    if value is True:
        return UI_THEME_HA_COMPONENTS
    text = str(value or "").strip().lower()
    if text in {UI_THEME_HA_COMPONENTS, "true", "on", "1"}:
        return UI_THEME_HA_COMPONENTS
    return UI_THEME_STANDARD


CONF_LOW_TOKEN = "low_token"
TOKEN_MODE_OFF = "off"
TOKEN_MODE_LIGHT = "light"
TOKEN_MODE_MEDIUM = "medium"
TOKEN_MODE_EXTREME = "extreme"
TOKEN_MODES = (TOKEN_MODE_OFF, TOKEN_MODE_LIGHT, TOKEN_MODE_MEDIUM, TOKEN_MODE_EXTREME)
_TOKEN_MODE_ON = {"1", "true", "on", "yes", TOKEN_MODE_EXTREME}
CONF_CHECK_HOUSE = "check_house"
# Agent form: Advanced section with one Save tokens box (stored as low_token medium/off).
SECTION_ADVANCED = "advanced"
CONF_SAVE_TOKENS = "save_tokens"
CONF_PROMPT_CACHE = "prompt_cache"
# Claude agents: keep the cached system prompt and tools for an hour instead of 5 minutes.
CONF_CACHE_1H = "cache_1h"
# Tokens the model can read; 0 means look it up from the model id.
CONF_CONTEXT_WINDOW = "context_window"
# Cloud agents start with a few tools and load the rest when they need them.
CONF_TOOLS_ON_DEMAND = "tools_on_demand"


def context_window_of(value) -> int:
    try:
        size = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(size, 10_000_000))

CONF_KEEP_CHATS = "keep_chats"
DEFAULT_KEEP_CHATS = 30
CONF_EFFORT = "effort"
# Per agent, off by default: web tools for cloud agents; web search, fetch and shell for Cursor.
CONF_ALLOW_INTERNET = "allow_internet"
CONF_ASSIST = "assist"
CONF_ASSIST_STT = "assist_stt"
CONF_STT_MODEL = "stt_model"
CONF_ASSIST_TTS = "assist_tts"
CONF_TTS_MODEL = "tts_model"
CONF_TTS_VOICE = "tts_voice"
CONF_TTS_SPEED = "tts_speed"
STT_PROVIDERS = frozenset({API_OPENAI, API_OPENROUTER, API_COMPATIBLE, API_GEMINI})
TTS_PROVIDERS = frozenset({API_OPENAI, API_OPENROUTER, API_COMPATIBLE, API_GEMINI, API_XAI})
_STT_MODEL = {
    API_OPENAI: "gpt-4o-mini-transcribe",
    API_OPENROUTER: "openai/whisper-1",
    API_COMPATIBLE: "whisper-1",
    API_GEMINI: "gemini-3.8-flash",
}
_STT_MODEL_CHOICES = {
    API_OPENAI: ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
    API_OPENROUTER: ["openai/whisper-1", "openai/gpt-4o-mini-transcribe", "openai/gpt-4o-transcribe"],
    API_COMPATIBLE: ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"],
    API_GEMINI: ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
}
_TTS_MODEL = {
    API_OPENAI: "gpt-4o-mini-tts",
    API_OPENROUTER: "openai/gpt-4o-mini-tts",
    API_COMPATIBLE: "gpt-4o-mini-tts",
    API_GEMINI: "gemini-3.8-flash-tts",
    # xAI /v1/tts takes no model field. The name only labels usage rows.
    API_XAI: "grok-tts",
}
_TTS_MODEL_CHOICES = {
    API_OPENAI: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
    API_OPENROUTER: ["openai/gpt-4o-mini-tts", "openai/tts-1-hd", "openai/tts-1"],
    API_COMPATIBLE: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
    API_GEMINI: ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"],
}
TTS_VOICES = [
    "coral",
    "marin",
    "cedar",
    "alloy",
    "ash",
    "ballad",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
]
DEFAULT_TTS_VOICE = "coral"
DEFAULT_GEMINI_TTS_VOICE = "Kore"
DEFAULT_XAI_TTS_VOICE = "eve"
# Built-in voices from GET https://api.x.ai/v1/tts/voices. Every voice speaks every language.
XAI_TTS_VOICES = [
    "eve",
    "ara",
    "rex",
    "sal",
    "leo",
    "luna",
    "iris",
    "carina",
    "celeste",
    "helios",
    "ursa",
    "rigel",
    "cosmo",
    "lux",
    "atlas",
    "castor",
    "naksh",
    "lumen",
    "sirius",
    "orion",
    "altair",
    "perseus",
    "zenith",
    "helix",
    "kepler",
    "zagan",
]
# xAI /v1/tts language codes. Anything else is sent as "auto".
_XAI_SPEECH_LANGUAGE = {
    "en": "en",
    "ar": "ar-SA",
    "bn": "bn",
    "zh": "zh",
    "fr": "fr",
    "de": "de",
    "hi": "hi",
    "id": "id",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "pt": "pt-BR",
    "ru": "ru",
    "es": "es-ES",
    "tr": "tr",
    "vi": "vi",
}
_XAI_REGIONAL = {"ar-eg", "ar-sa", "ar-ae", "pt-br", "pt-pt", "es-mx", "es-es"}
XAI_TTS_SPEEDS = (1.0, 1.25, 1.5)
GEMINI_TTS_VOICES = [
    "Kore",
    "Puck",
    "Charon",
    "Zephyr",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "RasAlgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
]
_GEMINI_SPEECH_LANGUAGE = {
    "ar": "ar-EG",
    "cmn": "cmn-CN",
    "cs": "cs-CZ",
    "da": "da-DK",
    "de": "de-DE",
    "el": "el-GR",
    "en": "en-US",
    "es": "es-ES",
    "fi": "fi-FI",
    "fr": "fr-FR",
    "hi": "hi-IN",
    "hu": "hu-HU",
    "id": "id-ID",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "nb": "nb-NO",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "pt": "pt-BR",
    "ro": "ro-RO",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "th": "th-TH",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "vi": "vi-VN",
    "zh": "cmn-CN",
}
DEFAULT_TTS_SPEED = 1.0
TTS_SPEEDS = (1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
# ISO 639-1 tags for OpenAI /audio/speech. One voice speaks all of these.
TTS_LANGUAGES = [
    "af",
    "ar",
    "hy",
    "az",
    "be",
    "bs",
    "bg",
    "ca",
    "zh",
    "hr",
    "cs",
    "da",
    "nl",
    "en",
    "et",
    "fi",
    "fr",
    "gl",
    "de",
    "el",
    "he",
    "hi",
    "hu",
    "is",
    "id",
    "it",
    "ja",
    "kn",
    "kk",
    "ko",
    "lv",
    "lt",
    "mk",
    "ms",
    "mr",
    "mi",
    "ne",
    "no",
    "fa",
    "pl",
    "pt",
    "ro",
    "ru",
    "sr",
    "sk",
    "sl",
    "es",
    "sw",
    "sv",
    "tl",
    "ta",
    "th",
    "tr",
    "uk",
    "ur",
    "vi",
    "cy",
]


def submitted_model(user_input: dict | None) -> str:
    """Empty model means use the provider fallback. Omitted optional fields are empty, not the old value."""
    if not user_input or CONF_MODEL not in user_input:
        return ""
    return str(user_input.get(CONF_MODEL) or "").strip()


def assist_enabled(raw: dict, *, new: bool = False) -> bool:
    """Existing agents stay in Assist. New agents are opt-in."""
    if CONF_ASSIST not in raw:
        return not new
    return bool(raw.get(CONF_ASSIST))


def provider_supports_stt(kind: str) -> bool:
    """True when this provider can register a Home Assistant STT engine."""
    return str(kind or "") in STT_PROVIDERS


def default_stt_model(kind: str) -> str:
    return _STT_MODEL.get(str(kind or ""), "whisper-1")


def stt_model_choices(kind: str) -> list[str]:
    return list(_STT_MODEL_CHOICES.get(str(kind or ""), []))


def resolved_stt_model(raw: dict, provider: str = "") -> str:
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    stored = str(raw.get(CONF_STT_MODEL) or "").strip()
    return stored or default_stt_model(kind)


def assist_stt_enabled(raw: dict, provider: str = "", *, new: bool = False) -> bool:
    """OpenAI-style agents transcribe unless turned off. Gemini is opt-in on existing rows."""
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    if not provider_supports_stt(kind):
        return False
    if CONF_ASSIST_STT not in raw:
        if kind == API_GEMINI:
            return bool(new)
        return True
    return bool(raw.get(CONF_ASSIST_STT))


def provider_supports_tts(kind: str) -> bool:
    """True when this provider can register a Home Assistant TTS engine."""
    return str(kind or "") in TTS_PROVIDERS


def provider_has_tts_model(kind: str) -> bool:
    """False for xAI: its speech endpoint has no model to pick."""
    return provider_supports_tts(kind) and str(kind or "") != API_XAI


def tts_speeds(kind: str) -> tuple[float, ...]:
    """Speed choices the provider accepts (xAI: 0.7 to 1.5)."""
    if str(kind or "") == API_XAI:
        return XAI_TTS_SPEEDS
    return TTS_SPEEDS


def xai_speech_language(language: str) -> str:
    """Map Home Assistant's language tag to an xAI /v1/tts code, or auto."""
    raw = str(language or "").strip().replace("_", "-").casefold()
    if not raw:
        return "auto"
    if raw in _XAI_REGIONAL:
        primary, region = raw.split("-", 1)
        return f"{primary}-{region.upper()}"
    return _XAI_SPEECH_LANGUAGE.get(raw.split("-", 1)[0], "auto")


def provider_supports_tts_speed(kind: str) -> bool:
    """True when the agent form can offer a speaking-speed control."""
    return provider_supports_tts(kind)


def tts_voices(kind: str) -> list[str]:
    if str(kind or "") == API_GEMINI:
        return list(GEMINI_TTS_VOICES)
    if str(kind or "") == API_XAI:
        return list(XAI_TTS_VOICES)
    return list(TTS_VOICES)


def default_tts_voice(kind: str) -> str:
    if str(kind or "") == API_GEMINI:
        return DEFAULT_GEMINI_TTS_VOICE
    if str(kind or "") == API_XAI:
        return DEFAULT_XAI_TTS_VOICE
    return DEFAULT_TTS_VOICE


def gemini_speech_language(language: str) -> str:
    """Map Home Assistant's language tag to Gemini speechConfig.languageCode."""
    raw = str(language or "").strip().replace("_", "-")
    if not raw:
        return "en-US"
    if "-" in raw:
        primary, region = raw.split("-", 1)
        if region:
            if primary.casefold() == "zh":
                return "cmn-CN" if region.casefold() in {"cn", "hans", "cmn"} else "cmn-TW"
            return f"{primary}-{region.upper() if len(region) == 2 else region}"
    primary = raw.split("-", 1)[0].casefold()
    return _GEMINI_SPEECH_LANGUAGE.get(primary, "en-US")


def gemini_generate_content_url(api_base: str, model: str) -> str:
    """Native generateContent URL from the OpenAI-compatible Gemini base."""
    base = str(api_base or default_api_base(API_GEMINI) or "").strip().rstrip("/")
    if base.endswith("/openai"):
        base = base[: -len("/openai")]
    name = str(model or default_tts_model(API_GEMINI)).strip() or default_tts_model(API_GEMINI)
    return f"{base}/models/{name}:generateContent"


def gemini_generate_content_headers(api_key: str) -> dict[str, str]:
    """AI Studio keys on generateContent. A Bearer header is treated as OAuth and returns 401."""
    key = str(api_key or "").strip()
    if not key:
        return {}
    return {"x-goog-api-key": key}


def default_tts_model(kind: str) -> str:
    return _TTS_MODEL.get(str(kind or ""), "gpt-4o-mini-tts")


def tts_model_choices(kind: str) -> list[str]:
    return list(_TTS_MODEL_CHOICES.get(str(kind or ""), []))


def resolved_tts_model(raw: dict, provider: str = "") -> str:
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    stored = str(raw.get(CONF_TTS_MODEL) or "").strip()
    return stored or default_tts_model(kind)


def resolved_tts_voice(raw: dict, provider: str = "") -> str:
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    stored = str(raw.get(CONF_TTS_VOICE) or "").strip()
    if kind == API_GEMINI:
        voices = {name.casefold(): name for name in GEMINI_TTS_VOICES}
        if stored:
            return voices.get(stored.casefold(), stored)
        return DEFAULT_GEMINI_TTS_VOICE
    return stored.casefold() or default_tts_voice(kind)


def tts_speed_choice(value: float) -> str:
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def resolved_tts_speed(raw: dict, provider: str = "") -> float:
    try:
        value = float(raw.get(CONF_TTS_SPEED, DEFAULT_TTS_SPEED) or DEFAULT_TTS_SPEED)
    except (TypeError, ValueError):
        value = DEFAULT_TTS_SPEED
    if str(provider or raw.get(CONF_API_PROVIDER) or "") == API_XAI:
        return max(0.7, min(1.5, value))
    return max(0.25, min(4.0, value))


def assist_tts_enabled(raw: dict, provider: str = "", *, new: bool = False) -> bool:
    """OpenAI-style agents speak unless turned off. Gemini and xAI are opt-in on existing rows."""
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    if not provider_supports_tts(kind):
        return False
    if CONF_ASSIST_TTS not in raw:
        if kind in {API_GEMINI, API_XAI}:
            return bool(new)
        return True
    return bool(raw.get(CONF_ASSIST_TTS))


def is_placeholder_tts(engine: str) -> bool:
    """True for Off / empty. Google Translate is a real engine the user may keep."""
    low = str(engine or "").strip().casefold()
    return (not low) or low == TTS_OFF


_BUILTIN_ASSIST = {
    "conversation.home_assistant",
    "homeassistant",
}


def is_builtin_assist_agent(agent_id: str, platform: str = "") -> bool:
    """True for Home Assistant's intent matcher ('Sorry, I didn't understand')."""
    eid = str(agent_id or "").strip()
    if eid in _BUILTIN_ASSIST:
        return True
    return platform == "homeassistant" and eid.startswith("conversation.")


CONF_STT_ENGINE = "stt_engine"
CONF_TTS_ENGINE = "tts_engine"
CONF_SPEAK_REPLIES = "speak_replies"
CONF_TTS_NATURAL = "tts_natural"
CONF_AZURE_API_VERSION = "azure_api_version"
CONF_BORROW = "borrow"
CONF_RUNTIME_URL = "runtime_url"
CONF_MODE = "mode"
CONF_API_PROVIDER = "api_provider"
CONF_API_KEY = "api_key"
CONF_API_BASE = "api_base"
CONF_SYSTEM_PROMPT = "system_prompt"
MODE_CURSOR = "cursor"
MODE_API = "api"
API_KEY_URLS = {
    API_OPENAI: "https://platform.openai.com/api-keys",
    API_ANTHROPIC: "https://console.anthropic.com/settings/keys",
    API_GEMINI: "https://aistudio.google.com/apikey",
    API_DEEPSEEK: "https://platform.deepseek.com/api_keys",
    API_QWEN: "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
    API_XAI: "https://console.x.ai/",
    API_OPENROUTER: "https://openrouter.ai/keys",
    API_AZURE: "https://oai.azure.com/",
    MODE_CURSOR: "https://cursor.com/dashboard/integrations",
}


def api_key_url(kind: str) -> str:
    """Provider console that issues API keys. Empty when there is no public key page."""
    return API_KEY_URLS.get(kind, "")


ADDON_SLUG = "ai_workspace"
ADDON_PORT = 8090
MCP_HA = "ha"
MCP_HA_MCP = "ha_mcp"
MCP_COOLVER = "coolver"
MCP_CUSTOM = "custom"


def ha_mcp_is_connected(mcp_kind: str, mcp_rows: list | None = None) -> bool:
    """True when HA-MCP is the primary connection or an extra MCP row."""
    if str(mcp_kind or "").strip() == MCP_HA_MCP:
        return True
    for row in mcp_rows or []:
        if isinstance(row, dict) and str(row.get("kind") or "").strip() == MCP_HA_MCP:
            return True
    return False


MCP_KINDS = {
    MCP_HA: "Home Assistant MCP Server (built-in)",
    MCP_HA_MCP: "HA-MCP",
    MCP_COOLVER: "HA Vibecode Agent (Coolver)",
    MCP_CUSTOM: "Custom MCP URL",
}
MCP_CONNECTION_TITLES = {
    MCP_HA: "Home Assistant",
    MCP_HA_MCP: "HA-MCP",
    MCP_COOLVER: "Coolver",
}
_MCP_KIND_ORDER = (MCP_HA, MCP_HA_MCP, MCP_COOLVER)


def mcp_kind_options(detected: set[str] | frozenset[str] | list[str], current: str = "") -> list[str]:
    """Detected MCP providers, the saved choice, and always Custom URL."""
    found = set(detected)
    options = [kind for kind in _MCP_KIND_ORDER if kind in found or kind == current]
    options.append(MCP_CUSTOM)
    return options


def mcp_connection_menu(
    detected: set[str] | frozenset[str] | list[str],
    used: set[str] | frozenset[str] | list[str] | None = None,
) -> list[str]:
    """Detected MCP servers not already added, plus Custom URL."""
    skip = set(used or ())
    options = [kind for kind in _MCP_KIND_ORDER if kind in detected and kind not in skip]
    options.append(MCP_CUSTOM)
    return options
DEFAULT_MCP_URL = "http://127.0.0.1:8086/mcp"
COMPOSE_MCP_URL = "http://ha-mcp:8086/mcp"
DEFAULT_COOLVER_URL = "http://127.0.0.1:8099"
DEFAULT_SYSTEM_PROMPT = """You help with this Home Assistant installation: automations, entities, dashboards, and what ran or failed.

Prefer a specific tool over a full-installation overview when the question is narrow. A large entity listing may come back as an area map of ids. Use that map, then ask a tool for one area or one entity before you claim its state. If more than one connection is set up, use the tool from the connection that matches the question.

Be concise. If a tool fails, say so. Ask before doing something hard to undo, such as deleting automations, unlocking doors, or turning off many devices at once.
"""
# Kept outside DEFAULT_SYSTEM_PROMPT so a custom prompt does not drop them.
HOUSE_RULES = (
    "A hello, thanks, or other small talk gets a short friendly reply. "
    "Do not list what you can do until the user asks about the house.\n\n"
    "Home Assistant is reached only through the connected MCP tools. Before you answer any question about "
    "this house (automations, entities, devices, states, counts, weather), call a Home Assistant tool. "
    "Never answer those from memory, and never invent entity ids, dashboard ids, states, or history. "
    "Before you say what a saved automation, script, scene, or dashboard contains, read it again with a tool: "
    "earlier messages in this chat may describe an older version or a plan that was never saved."
)
LOVELACE_DASHBOARD_RULES = """
Lovelace / dashboards (strict):
- Dashboards live only in the running Home Assistant. Read and write them with the MCP tools of one connection. Do not read from one connection and write to another.
- Read with the dashboard read tool, scoped to a view or card when a full pull is not needed. Write with the config hash from that read, as a small patch rather than a whole view.
- On a hash mismatch: one fresh read and one retry.
- Resolve entity ids with a search tool before you put them on a card.
- Screenshots or visual checks only when the user asks or the change is large or unclear.
- Tool budget: a simple card copy, move, removal, or reorder takes at most about twelve MCP calls. If you reach that, stop and say what is missing (dashboard url_path, view id, card index), or do one targeted read.
- Skill guides may be in English while the user writes another language. Still follow them.
""".strip()
BPS_KEY_INSTRUCTIONS = (
    "If a write tool has a BestPracticeKey field, read the matching skill guide from the "
    "same MCP connection (HA-MCP: ha_get_skill_guide) once before the first write in this chat, and pass "
    "the acknowledgment key from its top as BestPracticeKey. AI Workspace keeps that key current on your "
    "later writes and turns off the repeated guide text, so do not read the guide again before each write. "
    "If a write still fails because of the key, read the guide once more and retry once. "
    "If that field or tool does not exist, skip this. "
    "Do not ask the user for a key. Do not call a tool that is not listed."
)
WRITE_RULES = (
    "Only create, change, or delete what the user asked for. Never make a placeholder, test, or helper "
    "automation, script, scene, or entity to pass a key or get around a tool error. "
    "A dashboard change is one dashboard write and never needs an automation. "
    "If a write stays blocked, stop and tell the user. "
    "Only report errors and results that a tool actually returned. "
    "Never say a change is done before the write result confirms it. "
    "If asked where something in Home Assistant came from and you do not know, say so instead of guessing."
)
STATUS_LINE_INSTRUCTIONS = (
    "You may write one short status sentence before the first tool call when the "
    "answer needs tools, or when you start real work (a change or a write). "
    "If you do, make it a natural sentence in the user's language about "
    "what you are about to do for this request, not a generic filler. "
    "Write at most one status sentence per request. Between tool calls write nothing at all; "
    "the UI already shows them. Your next text is the answer."
)
# Sent with a voice turn: the status sentence would be read aloud before every answer.
VOICE_TURN_NOTE = "This is a voice request. Skip the status sentence and answer directly."
LOW_TOKEN_PROMPT = (
    "You help with this Home Assistant. Answer in a few short sentences. "
    "You cannot check or change the house in this mode."
)
LOW_TOKEN_MEDIUM_PROMPT = (
    "You help with this Home Assistant. Be brief. "
    "Use the connected tools to inspect or change the house. "
    "Do not invent entity ids or states."
)


def token_mode_of(value) -> str:
    """Map saved agent config (bool or string) to off/light/medium/extreme."""
    if value is True:
        return TOKEN_MODE_EXTREME
    if value is False or value is None:
        return TOKEN_MODE_OFF
    text = str(value).strip().lower()
    if text in _TOKEN_MODE_ON:
        return TOKEN_MODE_EXTREME
    if text in TOKEN_MODES:
        return text
    return TOKEN_MODE_OFF


def settings_token_mode(settings) -> str:
    if settings is None:
        return TOKEN_MODE_OFF
    return token_mode_of(getattr(settings, "token_mode", None))


def provider_token_mode(provider) -> str:
    """Cloud agents keep it on their settings, Cursor agents on the agent itself."""
    if provider is None:
        return TOKEN_MODE_OFF
    if hasattr(provider, "token_mode"):
        return token_mode_of(provider.token_mode)
    return settings_token_mode(getattr(provider, "settings", None))


def token_mode_fresh_agent(mode: str) -> bool:
    """Medium and Extreme start a new Cursor agent each turn, so its thread cannot grow."""
    return mode in {TOKEN_MODE_MEDIUM, TOKEN_MODE_EXTREME}


def token_mode_allows_tools(mode: str) -> bool:
    return mode != TOKEN_MODE_EXTREME


def token_mode_history_limit(mode: str) -> int:
    if mode == TOKEN_MODE_LIGHT:
        return 12
    if mode == TOKEN_MODE_MEDIUM:
        return 4
    if mode == TOKEN_MODE_OFF:
        return 12
    # Chat only still remembers the last few messages; a chat without memory is no chat.
    return 4


def token_mode_allows_extras(mode: str) -> bool:
    """Page note, Assist extra prompt, cross-chat, auto title, effort."""
    return mode == TOKEN_MODE_OFF


def token_mode_allows_files(mode: str) -> bool:
    return mode in {TOKEN_MODE_OFF, TOKEN_MODE_LIGHT}


def token_mode_checks_house(mode: str, check_house: bool) -> bool:
    """The agent's own switch. Extreme has no tools, so there is nothing to check with."""
    return bool(check_house) and mode != TOKEN_MODE_EXTREME


def token_mode_reply_limit(mode: str) -> int | None:
    if mode == TOKEN_MODE_EXTREME:
        return 256
    if mode == TOKEN_MODE_MEDIUM:
        return 1024
    return None


def token_mode_clip_user(mode: str) -> int | None:
    if mode in {TOKEN_MODE_EXTREME, TOKEN_MODE_MEDIUM}:
        return 1200
    return None


LANGUAGE_INSTRUCTION = (
    "Always answer in the same language the user wrote their latest message in."
)
_LANGUAGE_NAMES = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "eo": "Esperanto",
    "es": "Spanish",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "nb": "Norwegian",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
}


def language_name(code: str) -> str:
    primary = str(code or "").replace("_", "-").split("-")[0].strip().lower()
    return _LANGUAGE_NAMES.get(primary, "")


def language_instruction(code: str = "") -> str:
    name = language_name(code)
    if not name:
        return LANGUAGE_INSTRUCTION
    fallback = (
        f"If that message does not make the language clear, answer in {name}, "
        "the language set in Home Assistant."
    )
    if name != "English":
        fallback += " Do not assume English."
    return f"{LANGUAGE_INSTRUCTION} {fallback}"


def workspace_system_prompt(settings, *, admin: bool = True) -> str:
    """Built-in or custom system prompt plus the rules every agent gets."""
    base = str(getattr(settings, "system_prompt", "") or "").strip() or DEFAULT_SYSTEM_PROMPT
    parts = [base, HOUSE_RULES, LOVELACE_DASHBOARD_RULES, BPS_KEY_INSTRUCTIONS, WRITE_RULES, STATUS_LINE_INSTRUCTIONS]
    if admin and getattr(settings, "house_map", False):
        from .house_map import CATALOG_INSTRUCTIONS

        parts.append(CATALOG_INSTRUCTIONS)
    try:
        from .notes import notes_prompt
    except ImportError:
        notes_prompt = None
    if notes_prompt is not None:
        parts.append(notes_prompt(settings, admin=admin, write=admin))
    return "\n\n".join(part.strip() for part in parts if part.strip())


_CHAT_SCOPE = (
    "This chat is separate from the user's other chats. "
    "Do not assume what was said in them. "
    "Use another chat only when the message includes a read-only excerpt from it. "
    "When the user confirms an action, do it and then answer. Do not ask again. "
    "Do not repeat a tool call you already made in this turn. "
    "If a device is already in the requested state, say so."
)


def with_language_rule(text: str, language: str = "") -> str:
    body = str(text or "").rstrip()
    if LANGUAGE_INSTRUCTION in body:
        body = body.replace(LANGUAGE_INSTRUCTION, "").rstrip()
    rule = language_instruction(language)
    scoped = f"{body}\n\n{_CHAT_SCOPE}".strip() if body else _CHAT_SCOPE
    return f"{scoped}\n\n{rule}".strip()


def with_time_rule(text: str, rule: str = "") -> str:
    """The house's time zone goes last, after the language rule, so the rest stays a stable prefix."""
    return f"{text}\n\n{rule}" if rule else text


TONE_INSTRUCTIONS = (
    "List capabilities, URLs, or entity links only when the user asks about the house. "
    "Keep MCP, tool names, Docker, and loopback addresses out of the reply the user reads. "
    "Earlier replies may end with a [tools: ...] line. AI Workspace adds it as a note of what those tools "
    "returned. Use it to avoid repeating lookups, but check live state again before you change something, "
    "and never write such a line yourself."
)
HA_LINK_INSTRUCTIONS = """Every automation, script, scene, device, helper, entity, or dashboard/view you mention must be a Markdown link. Do not list plain names or bare paths. Do not ask whether the user wants links. Use root-relative paths that start with /. Never use 127.0.0.1, localhost, or an MCP URL in those links — those are only how tools reach Home Assistant from Docker. Do not link the words Home Assistant.

URL rules (wrong ids open a blank editor):
- Automations: [Name](/config/automation/edit/{id}) where {id} is the automation config id / unique_id from the tool. That may be a yaml id (balcony_irrigation) or a numeric timestamp (1687972788597). NEVER use entity_id. Wrong: /config/automation/edit/automation.balcony_irrigation Right: /config/automation/edit/balcony_irrigation
- Scripts: [Name](/config/script/edit/{id}) using the script unique_id or object_id, not script.entity_id.
- Scenes: [Name](/config/scene/edit/{id}) using the scene unique_id, not scene.entity_id.
- Devices: [Name](/config/devices/device/{device_id}) using the hex device_id (for example ce88feb75016ee2f89ed363b4995a1c8), never an entity_id.
- Entities: [Name](/config/entities/entity/{entity_id}) using the full entity_id (light.kitchen).
- Helpers (input_boolean, input_number, counter, timer, schedule, …): [Name](/config/entities/entity/{entity_id}) using the helper entity_id, not a generic /config/helpers list.
- Dashboards and views: [Media](/lovelace/media) or [Overview](/lovelace/0).
Take id, unique_id, and device_id from the MCP tool result.

Put names in a markdown table only when every name cell is already a Markdown link. Example: | [Bewässerung](/config/automation/edit/balcony_irrigation) | on |"""
# Cursor agents also have file tools; cloud agents do not, so they never get this.
WORKSPACE_FILES_RULE = (
    "Home Assistant configuration is not in this workspace. Do not use grep, glob, read, shell, or "
    "Task/explore subagents to look for automations.yaml, dashboards.yaml, .storage, ui-lovelace, or other "
    "Home Assistant files, unless the user opened a Home Assistant config repository. Use the MCP tools."
)
MCP_BULK_LIST_INSTRUCTIONS = """Bulk lists (automations, scripts, scenes, entities, helpers):
- Answer with one or two Home Assistant MCP calls: a domain-filtered listing that returns every matching item with live state (on/off) when the user asked for it. Use entity search/list tools with domain_filter (or the server equivalent), not one get-config call per item.
- For automation, script, and scene edit links, use config id / unique_id from that listing (entity attributes such as id, or registry unique_id in the same batch). Never call ha_config_get_automation, ha_config_get_script, or ha_config_get_scene once per row only to learn the edit id. Load full config for a single named item only when the user asks what it triggers, conditions, or actions do.
- A full automation list with links and on/off should take about 1–3 MCP calls total, not dozens."""


def ui_link_instructions(origin: str = "") -> str:
    text = f"{TONE_INSTRUCTIONS}\n\n{MCP_BULK_LIST_INSTRUCTIONS}\n\n{HA_LINK_INSTRUCTIONS}"
    origin = str(origin or "").strip().rstrip("/")
    if origin:
        text = (
            f"{text}\n\nThe browser origin is {origin}. Use it only to understand where the UI is. "
            "Never write that origin, 127.0.0.1, or localhost in a reply unless the user asks for the address."
        )
    return text


def with_ui_context(message: str, origin: str = "") -> str:
    return f"{ui_link_instructions(origin)}\n\n{message}"


# Cursor cannot be forced to call a tool first, so it is asked to.
CHECK_HOUSE_NOTE = (
    "If this message is about the house (devices, states, lists, weather), call a Home Assistant tool before you answer."
)


def standing_chat_prompt(
    settings,
    *,
    admin: bool = True,
    language: str = "",
    origin: str = "",
    mode: str = TOKEN_MODE_OFF,
    time_zone_rule: str = "",
) -> str:
    """Workspace rules plus UI/MCP instructions for one Cursor agent lifetime. Same levels as cloud agents."""
    return with_time_rule(
        _standing_text(settings, admin=admin, language=language, origin=origin, mode=mode), time_zone_rule
    )


def _standing_text(settings, *, admin: bool, language: str, origin: str, mode: str) -> str:
    if mode == TOKEN_MODE_EXTREME:
        return with_language_rule(LOW_TOKEN_PROMPT, language)
    if mode == TOKEN_MODE_MEDIUM:
        try:
            from .notes import notes_prompt
        except ImportError:
            extra = ""
        else:
            extra = notes_prompt(settings, admin=admin, write=admin)
        head = f"{LOW_TOKEN_MEDIUM_PROMPT}\n\n{extra}".strip() if extra else LOW_TOKEN_MEDIUM_PROMPT
        text = f"{head}\n\n{WORKSPACE_FILES_RULE}\n\n{ui_link_instructions(origin)}"
        return with_language_rule(text, language)
    body = f"{workspace_system_prompt(settings, admin=admin)}\n\n{WORKSPACE_FILES_RULE}"
    return with_language_rule(f"{body}\n\n{ui_link_instructions(origin)}", language)


_ENTITY_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-zA-Z0-9_]+$")
_PAGE_TEXT = 120


def parse_ui_page(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    path = str(raw.get("path") or "").strip()[:200]
    if not path.startswith("/") or path.startswith("/ai-workspace"):
        return {}
    page: dict[str, object] = {"path": path}
    for key in ("title", "dashboard", "view", "area", "area_id"):
        value = str(raw.get(key) or "").strip().replace("\n", " ")[:_PAGE_TEXT]
        if value:
            page[key] = value
    entities: list[str] = []
    seen: set[str] = set()
    for item in raw.get("entities") or []:
        entity = str(item or "").strip()
        if not _ENTITY_ID.match(entity) or entity in seen:
            continue
        seen.add(entity)
        entities.append(entity)
        if len(entities) >= 40:
            break
    if entities:
        page["entities"] = entities
    return page


def format_ui_page(page: dict[str, object] | None) -> str:
    if not page:
        return ""
    lines = [
        "The user is currently looking at this Home Assistant UI page "
        "(the dashboard or view behind the chat, not the chat itself):",
        f"- Path: {page['path']}",
    ]
    for key, label in (
        ("title", "Page title"),
        ("dashboard", "Dashboard"),
        ("view", "View"),
        ("area", "Area"),
    ):
        value = page.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    entities = page.get("entities") or []
    if isinstance(entities, list) and entities:
        lines.append("- Entities visible on this view: " + ", ".join(str(item) for item in entities))
    lines.append(
        "If they say the lights, this room, or this dashboard, they mean this view "
        "unless they say otherwise. Use MCP tools for live state. Do not invent extra entities."
    )
    return "\n".join(lines)


COMPOSE_RUNTIME_URL = "http://ai-workspace:8090"
COMPOSE_RUNTIME_URLS = (
    "http://ai-workspace:8090",
    "http://cursor-sdk:8090",
)
HOST_RUNTIME_URL = "http://127.0.0.1:8090"
