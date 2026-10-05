Evening on the couch: ideas and questions about automations. The Cursor AI that could help is on the computer — not on the phone in my hands.

This integration puts your AI right into Home Assistant.

# AI Workspace

A chat in Home Assistant that can look at **your** house, using the Home Assistant tools you already expose over MCP (for example [ha-mcp](https://github.com/homeassistant-ai/ha-mcp)). Cursor is one option for the agent — not a requirement of the UI.

## What it does

- Adds an **AI Workspace** page in Home Assistant (`/ai-workspace`) with chat history.
- Optionally shows a floating **AI** button on other pages so you can ask something without leaving the current view (not on Settings pages, so it does not cover **Add integration**).
- Follows your Home Assistant theme and the usual header (sidebar toggle and title).
- Talks to an agent: **API provider** (OpenAI or Claude) in the integration, or **Cursor** in the Runtime app (Home Assistant OS).
- Uses the Home Assistant MCP you already run: built-in **MCP Server**, **HA-MCP**, **HA Vibecode Agent**, or a custom MCP HTTP URL.
- Model traffic is **outbound HTTPS**. Nothing inbound is required. MCP stays on the LAN.

## What it does not

- It is **not** Assist, voice control, or a Lovelace card. It does not replace the built-in conversation agent.
- It does **not** start a second Home Assistant MCP server. Point it at the MCP you already have (built-in MCP Server, HA-MCP, or Vibecode Agent).
- It does **not** publish MCP to the internet. Do not expose those ports.
- It does **not** use a Home Assistant long-lived access token as the model key.

## Two pieces

The HACS integration is always the chat UI. The agent is either an **API provider** (key + MCP on this integration, no app) or **Cursor** (Runtime app).

| Piece | Role | You configure |
|---|---|---|
| **AI Workspace** (HACS integration) | Sidebar, floating **AI** button, chat page | Chat Backend, API key, MCP type / URL / token, floating button, sidebar |
| **AI Workspace Runtime** (app) | Optional Cursor SDK agent | **Cursor API key**, MCP type / URL / token, model |

## Configure the HACS integration

**Settings → Devices & services → AI Workspace → Configure**

| Option | What it does |
|---|---|
| **Chat Backend** | First step: **Cloud API Provider** or **Cursor Runtime app**. Provider fields open after you pick Cloud API Provider. |
| **Provider** | Shown only for Cloud API Provider: OpenAI or Claude, plus API key and optional model |
| **MCP type** | **Home Assistant MCP Server** (built-in `/api/mcp` — add that integration first), **HA-MCP**, **HA Vibecode Agent (Coolver)**, or **Custom MCP URL** |
| **MCP URL** | Leave empty for the default of that type. HA-MCP needs the connect URL from that integration. Custom needs a full MCP HTTP URL. |
| **MCP token** | Built-in: Home Assistant long-lived access token (or empty to use your current login in this chat). HA-MCP: usually empty. Vibecode: Agent Key. Custom: optional Bearer token. |
| **System prompt** | How the Cloud API model should behave. Empty uses the built-in Home Assistant prompt. |
| **Show floating AI button on every page** | Bottom-right **AI** button. Hidden on Settings. |
| **Show AI Workspace in the sidebar** | Sidebar item. `/ai-workspace` still works if this is off. |

Cursor’s API key and model stay on the Runtime app. MCP type, URL, and token are on this form for both backends.

**Runtime URL** is advanced and not on this dialog for a normal install. Home Assistant OS auto-detects the app. Only set it in YAML (or on first setup if the app was not found) if the agent runs somewhere else that speaks **this** integration’s chat API — not a generic OpenAI, Ollama, or “any local API” URL. On Container, that is the Runtime container hostname, for example `runtime_url: http://ai-workspace:8090`.

## Configure the Runtime app

**Settings → Apps → AI Workspace Runtime → Configuration**

| Option | What it is |
|---|---|
| **Cursor API key** | User API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) |
| **MCP type** | Built-in MCP Server, HA-MCP, Vibecode Agent, or custom |
| **MCP URL** | HTTP URL for HA-MCP / custom / Vibecode. Empty uses the default for that type. |
| **MCP token** | Home Assistant long-lived token, Vibecode Agent Key, or optional Bearer token |
| **Extra MCP servers** (`mcp_config`) | Optional JSON object |
| **Model** | Cursor model id, for example `composer-2.5` |

## Requirements

- Home Assistant with HACS: **OS** (Apps) or **Container** (Docker), including Raspberry Pi.
- An MCP on this installation (built-in MCP Server, HA-MCP, or Vibecode Agent) or another MCP HTTP endpoint on the LAN.
- **Either** an OpenAI or Anthropic API key (no Runtime), **or** Cursor plus the Runtime (an **App** on HA OS, or a Docker sidecar on Container).

## Install (Home Assistant OS)

1. **Settings → Apps → Install app → ⋮ → Repositories** and add this GitHub repository.
2. Install **AI Workspace Runtime**. The first start builds the image and can take a few minutes.
3. On the app **Configuration** tab:
   - **Cursor API key** — Cursor Dashboard → Integrations (not a Home Assistant token).
   - **MCP type / URL / token** — built-in MCP Server, HA-MCP connect URL, or Vibecode Agent Key. Example HA-MCP URL: `http://127.0.0.1:8086/mcp`.
   - Optional **Extra MCP servers** (`mcp_config`) — JSON in Cursor `mcpServers` shape for GitHub, Synology, and similar.
4. Start the app.
5. In HACS, add `https://github.com/domdus/ha-ai-workspace` as a custom **integration**, install **AI Workspace**, and restart Home Assistant.
6. **Settings → Devices & services → Add integration → AI Workspace**.
   - **Cloud API Provider:** pick OpenAI or Claude, paste that key, then MCP type, URL, and token. Skip the Runtime app.
   - **Cursor:** start the Runtime app first. Runtime URL is filled in when it is running. Cursor’s key and MCP URL stay on the app.

## Install (Home Assistant Container)

There is no **Settings → Apps**. Install the HACS integration, then optionally run Cursor as a second container on the **same host** as Home Assistant.

### HACS integration

1. HACS → Integrations → ⋮ → Custom repositories → `https://github.com/domdus/ha-ai-workspace` → **Integration**.
2. Download **AI Workspace**, restart Home Assistant.
3. **Settings → Devices & services → Add integration → AI Workspace**.
4. **Cloud API Provider** (no extra container): OpenAI or Claude key, plus MCP type / URL / token.

### Cursor Runtime (Docker)

This container is `cursor-sdk` plus a small `/api`. The HACS panel is the UI. It is **not** a second Home Assistant.

```bash
git clone https://github.com/domdus/ha-ai-workspace.git
cd ha-ai-workspace
cp runtime.env.example .env
```

Edit `.env`:

```bash
CURSOR_API_KEY=          # https://cursor.com/dashboard/integrations
CURSOR_MODEL=composer-2.5
# How *this* container reaches HA-MCP (host network = this machine).
MCP_URL=http://127.0.0.1:8123/api/webhook/<ha-mcp-webhook-id>
```

Use the HA-MCP webhook from that integration. Built-in MCP is `/api/mcp` plus `MCP_TOKEN`. Leave `MCP_TOKEN` empty for an HA-MCP webhook.

```bash
docker compose -f docker-compose.runtime.yml up -d --build
```

The compose file uses **host network**. Port **8090** is bound to `127.0.0.1` only. Do not publish it on the LAN.

Then **Configure → Chat Backend → Cursor Runtime app**, Runtime URL `http://127.0.0.1:8090`.

Cursor’s key and model stay in `.env` on that container.

If `docker compose build` cannot reach Debian apt, build the image on another machine, tag it `ai-workspace-runtime:0.3.0`, `docker save` / `docker load` it onto the HA host, then `docker compose -f docker-compose.runtime.yml up -d`.

## Extra MCP servers

Optional `mcp_config` is merged with **MCP URL**:

```json
{
  "mcpServers": {
    "github": { "url": "http://github-mcp:8080/mcp" }
  }
}
```

