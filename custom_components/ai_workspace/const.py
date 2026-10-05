DOMAIN = "ai_workspace"
PANEL_URL = "ai-workspace"
PANEL_ELEMENT = "ha-ai-workspace-panel"
STATIC_URL = "/ai_workspace/static"
FRONTEND_CACHE = "22"
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
COMPOSE_RUNTIME_URL = "http://ai-workspace:8090"
HOST_RUNTIME_URL = "http://127.0.0.1:8090"
