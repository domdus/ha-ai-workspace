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


def api_model_choices(kind: str) -> list[str]:
    return list(_API_MODEL_CHOICES.get(kind, ()))


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
CONF_CROSS_CHAT = "cross_chat"
CONF_LOW_TOKEN = "low_token"
CONF_CHECK_HOUSE = "check_house"
CONF_KEEP_CHATS = "keep_chats"
DEFAULT_KEEP_CHATS = 30
CONF_EFFORT = "effort"
CONF_ASSIST = "assist"
CONF_ASSIST_STT = "assist_stt"
CONF_STT_MODEL = "stt_model"
CONF_ASSIST_TTS = "assist_tts"
CONF_TTS_MODEL = "tts_model"
CONF_TTS_VOICE = "tts_voice"
STT_PROVIDERS = frozenset({API_OPENAI, API_OPENROUTER, API_COMPATIBLE})
TTS_PROVIDERS = STT_PROVIDERS
_STT_MODEL = {
    API_OPENAI: "gpt-4o-mini-transcribe",
    API_OPENROUTER: "openai/whisper-1",
    API_COMPATIBLE: "whisper-1",
}
_STT_MODEL_CHOICES = {
    API_OPENAI: ["gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
    API_OPENROUTER: ["openai/whisper-1", "openai/gpt-4o-mini-transcribe", "openai/gpt-4o-transcribe"],
    API_COMPATIBLE: ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"],
}
_TTS_MODEL = {
    API_OPENAI: "gpt-4o-mini-tts",
    API_OPENROUTER: "openai/gpt-4o-mini-tts",
    API_COMPATIBLE: "gpt-4o-mini-tts",
}
_TTS_MODEL_CHOICES = {
    API_OPENAI: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
    API_OPENROUTER: ["openai/gpt-4o-mini-tts", "openai/tts-1-hd", "openai/tts-1"],
    API_COMPATIBLE: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"],
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
    """True when this provider has an OpenAI-style /audio/transcriptions API."""
    return str(kind or "") in STT_PROVIDERS


def default_stt_model(kind: str) -> str:
    return _STT_MODEL.get(str(kind or ""), "whisper-1")


def stt_model_choices(kind: str) -> list[str]:
    return list(_STT_MODEL_CHOICES.get(str(kind or ""), []))


def resolved_stt_model(raw: dict, provider: str = "") -> str:
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    stored = str(raw.get(CONF_STT_MODEL) or "").strip()
    return stored or default_stt_model(kind)


def assist_stt_enabled(raw: dict, provider: str = "") -> bool:
    """OpenAI-style agents transcribe for Assist unless the row turned it off."""
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    if not provider_supports_stt(kind):
        return False
    if CONF_ASSIST_STT not in raw:
        return True
    return bool(raw.get(CONF_ASSIST_STT))


def provider_supports_tts(kind: str) -> bool:
    """True when this provider has an OpenAI-style /audio/speech API."""
    return str(kind or "") in TTS_PROVIDERS


def default_tts_model(kind: str) -> str:
    return _TTS_MODEL.get(str(kind or ""), "gpt-4o-mini-tts")


def tts_model_choices(kind: str) -> list[str]:
    return list(_TTS_MODEL_CHOICES.get(str(kind or ""), []))


def resolved_tts_model(raw: dict, provider: str = "") -> str:
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    stored = str(raw.get(CONF_TTS_MODEL) or "").strip()
    return stored or default_tts_model(kind)


def resolved_tts_voice(raw: dict) -> str:
    stored = str(raw.get(CONF_TTS_VOICE) or "").strip().casefold()
    return stored or DEFAULT_TTS_VOICE


def assist_tts_enabled(raw: dict, provider: str = "") -> bool:
    """OpenAI-style agents speak for Assist unless the row turned it off."""
    kind = str(provider or raw.get(CONF_API_PROVIDER) or "")
    if not provider_supports_tts(kind):
        return False
    if CONF_ASSIST_TTS not in raw:
        return True
    return bool(raw.get(CONF_ASSIST_TTS))


def is_placeholder_tts(engine: str) -> bool:
    """True for Off and Google Translate (the usual HA default)."""
    low = str(engine or "").strip().casefold()
    return (not low) or low == TTS_OFF or "google_translate" in low


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
ADDON_SLUG = "ai_workspace"
ADDON_PORT = 8090
MCP_HA = "ha"
MCP_HA_MCP = "ha_mcp"
MCP_COOLVER = "coolver"
MCP_CUSTOM = "custom"
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

A hello, thanks, or other small talk gets a short friendly reply. Do not list what you can do until the user asks about the house.

Home Assistant is reached only through the connected MCP tools. Use those tools to inspect or change anything. Do not invent entity ids, states, or history. Prefer a specific tool over a full-installation overview when the question is narrow. A large entity listing may come back as an area map of ids. Use that map, then ask a tool for one area or one entity before you claim its state. If more than one connection is set up, use the tool from the connection that matches the question.

Before you answer any question about this house (automations, entities, devices, states, counts), call a Home Assistant tool. Never answer those from memory.

Be concise. Call tools without announcing them; the UI already shows that. If a tool fails, say so. Ask before doing something hard to undo, such as deleting automations, unlocking doors, or turning off many devices at once.

"""
LOW_TOKEN_PROMPT = (
    "You help with this Home Assistant. Answer in a few short sentences. "
    "You cannot check or change the house in this mode."
)
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


TONE_INSTRUCTIONS = (
    "A hello, thanks, or other small talk gets a short friendly reply. "
    "List capabilities, URLs, or entity links only when the user asks about the house. "
    "Do not link the words Home Assistant. "
    "Keep MCP, tool names, Docker, and loopback addresses out of the reply the user reads. "
    "Call tools silently: the UI already shows tool chips. Answer with the result. Only explain tools if the user asks."
)
HA_LINK_INSTRUCTIONS = """Every automation, script, scene, device, helper, entity, or dashboard/view you mention must be a Markdown link. Do not list plain names or bare paths. Do not ask whether the user wants links. Use root-relative paths that start with /. Never use 127.0.0.1, localhost, or an MCP URL in those links — those are only how tools reach Home Assistant from Docker. Do not link the words Home Assistant.

URL rules (wrong ids open a blank editor):
- Automations: [Name](/config/automation/edit/{id}) where {id} is the automation config id / unique_id from the tool. That may be a yaml id (balcony_irrigation) or a numeric timestamp (1687972788597). NEVER use entity_id. Wrong: /config/automation/edit/automation.balcony_irrigation Right: /config/automation/edit/balcony_irrigation
- Scripts: [Name](/config/script/edit/{id}) using the script unique_id or object_id, not script.entity_id.
- Scenes: [Name](/config/scene/edit/{id}) using the scene unique_id, not scene.entity_id.
- Devices: [Name](/config/devices/device/{device_id}) using the hex device_id (for example ce88feb75016ee2f89ed363b4995a1c8), never an entity_id.
- Entities: [Name](/config/entities/entity/{entity_id}) using the full entity_id (light.kitchen).
- Helpers (input_boolean, input_number, counter, timer, schedule, …): [Name](/config/entities/entity/{entity_id}) using the helper entity_id, not a generic /config/helpers list.
- Dashboards and views: [Media](/lovelace/media) or [Overview](/lovelace/0). Never write a bare /lovelace/... path without a Markdown link.
Take id, unique_id, and device_id from the MCP tool result. If a tool only returned entity_id for an automation, look up its id before linking.

Never list plain names. Never put names in a markdown table unless every name cell is already a Markdown link. Example: | [Bewässerung](/config/automation/edit/balcony_irrigation) | on |"""
MCP_FIRST_INSTRUCTIONS = """Home Assistant lives in the MCP tools (home-assistant / ha-mcp), not in this workspace. For automations, entities, devices, scripts, or house state, call those MCP tools first. Do not use grep, glob, read, or shell to hunt for automations.yaml or HA config — those files are not here."""
BPS_KEY_INSTRUCTIONS = (
    "If a write tool has BestPracticeKey, call ha_get_skill_guide, copy the acknowledgment key "
    "from the top of the result, and pass it as BestPracticeKey. Do not ask the user for it."
)


def ui_link_instructions(origin: str = "") -> str:
    text = f"{TONE_INSTRUCTIONS} {MCP_FIRST_INSTRUCTIONS} {HA_LINK_INSTRUCTIONS}"
    origin = str(origin or "").strip().rstrip("/")
    if origin:
        text = (
            f"{text} The browser origin is {origin}. Use it only to understand where the UI is. "
            "Never write that origin, 127.0.0.1, or localhost in a reply unless the user asks for the address."
        )
    return text


def with_ui_context(message: str, origin: str = "") -> str:
    return f"{ui_link_instructions(origin)}\n\n{message}"


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


COMPOSE_RUNTIME_URL = "http://cursor-sdk:8090"
COMPOSE_RUNTIME_URLS = (
    "http://cursor-sdk:8090",
    "http://ai-workspace:8090",
)
HOST_RUNTIME_URL = "http://127.0.0.1:8090"
