DOMAIN = "ai_workspace"
PANEL_URL = "ai-workspace"
PANEL_ELEMENT = "ha-ai-workspace-panel"
STATIC_URL = "/ai_workspace/static"
FRONTEND_CACHE = "47"
OVERLAY_JS = f"{STATIC_URL}/overlay.js?v={FRONTEND_CACHE}"
PANEL_JS = f"{STATIC_URL}/panel.js?v={FRONTEND_CACHE}"
DEFAULT_MODEL = "composer-2.5"
DEFAULT_API_MODEL = "gpt-4.1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_TITLE = "AI Workspace"
CONF_MCP_URL = "mcp_url"
CONF_MCP_KIND = "mcp_kind"
CONF_MCP_TOKEN = "mcp_token"
CONF_CURSOR_API_KEY = "cursor_api_key"
CONF_MODEL = "model"
CONF_ENABLE_OVERLAY = "enable_overlay"
CONF_ENABLE_SIDEBAR = "enable_sidebar"
CONF_RUNTIME_URL = "runtime_url"
CONF_MODE = "mode"
CONF_API_PROVIDER = "api_provider"
CONF_API_KEY = "api_key"
CONF_API_BASE = "api_base"
CONF_SYSTEM_PROMPT = "system_prompt"
MODE_CURSOR = "cursor"
MODE_API = "api"
API_OPENAI = "openai"
API_ANTHROPIC = "anthropic"
API_COMPATIBLE = "compatible"
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
DEFAULT_MCP_URL = "http://127.0.0.1:8086/mcp"
COMPOSE_MCP_URL = "http://ha-mcp:8086/mcp"
DEFAULT_COOLVER_URL = "http://127.0.0.1:8099"
DEFAULT_SYSTEM_PROMPT = """You help with this Home Assistant installation: automations, entities, dashboards, and what ran or failed.

Home Assistant is reached only through the connected MCP tools. Use those tools to inspect or change anything. Do not invent entity ids, states, or history. Prefer a specific tool over a full-installation overview when the question is narrow.

Be concise. If a tool fails, say so. Ask before doing something hard to undo, such as deleting automations, unlocking doors, or turning off many devices at once."""
HA_LINK_INSTRUCTIONS = """When you mention automations, scripts, scenes, devices, helpers, or entities, include a Markdown link the user can open in this Home Assistant UI. Use root-relative paths that start with /. Never use 127.0.0.1, localhost, or an MCP URL in those links — those are only how tools reach Home Assistant from Docker.

URL rules (wrong ids open a blank editor):
- Automations: [Name](/config/automation/edit/{id}) where {id} is the automation config id / unique_id (often a numeric timestamp such as 1687972788597). NEVER use entity_id. Wrong: /config/automation/edit/automation.07_00_am_wochenende Right: /config/automation/edit/1687972788597
- Scripts: [Name](/config/script/edit/{id}) using the script unique_id or object_id, not script.entity_id.
- Scenes: [Name](/config/scene/edit/{id}) using the scene unique_id, not scene.entity_id.
- Devices: [Name](/config/devices/device/{device_id}) using the hex device_id (for example ce88feb75016ee2f89ed363b4995a1c8), never an entity_id.
- Entities: [Name](/config/entities/entity/{entity_id}) using the full entity_id (light.kitchen).
- Helpers (input_boolean, input_number, counter, timer, schedule, …): [Name](/config/helpers)
Take id, unique_id, and device_id from the MCP tool result. If a tool only returned entity_id for an automation, look up its id before linking."""
MCP_FIRST_INSTRUCTIONS = """Home Assistant lives in the MCP tools (home-assistant / ha-mcp), not in this workspace. For automations, entities, devices, scripts, or house state, call those MCP tools first. Do not use grep, glob, read, or shell to hunt for automations.yaml or HA config — those files are not here."""


def ui_link_instructions(origin: str = "") -> str:
    text = f"{MCP_FIRST_INSTRUCTIONS} {HA_LINK_INSTRUCTIONS}"
    origin = str(origin or "").strip().rstrip("/")
    if origin:
        text = f"{text} This user's Home Assistant UI is {origin}."
    return text


def with_ui_context(message: str, origin: str = "") -> str:
    return f"{ui_link_instructions(origin)}\n\n{message}"


COMPOSE_RUNTIME_URL = "http://cursor-sdk:8090"
COMPOSE_RUNTIME_URLS = (
    "http://cursor-sdk:8090",
    "http://ai-workspace:8090",
)
HOST_RUNTIME_URL = "http://127.0.0.1:8090"
