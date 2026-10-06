Use Cursor, Claude, or ChatGPT in Home Assistant from your couch.

The agent chat sits in Home Assistant now. No desktop tools needed.

# AI Workspace

A chat in Home Assistant that can look at **your** house, using the Home Assistant tools you already expose over MCP (for example [HA-MCP](https://github.com/homeassistant-ai/ha-mcp)).

The sidebar chat is a HACS integration. The agent is either a **cloud API** (OpenAI or Claude) or the **Cursor SDK** (optional Runtime).

## Get Started

The HACS integration is the preferred install. It works on **Home Assistant OS**, Supervised, Container, and Core.

**Add it to Home Assistant via HACS (the preferred install):**

[![Add AI Workspace to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domdus&repository=ha-ai-workspace&category=integration)

**Quick start:**

1. Click the badge, or in HACS open **Integrations → ⋮ → Custom repositories**, add `https://github.com/domdus/ha-ai-workspace` (category: **Integration**), then **Download**.
2. **Restart Home Assistant.**
3. **Settings → Devices & services → Add integration → AI Workspace.**
4. Pick a backend:
   - **Cloud API Provider** — OpenAI or Claude key, then MCP type / URL / token. No extra container.
   - **Cursor Runtime app** — start the Runtime first (steps below), then MCP type / URL / token on this form. Cursor’s API key stays on the Runtime.
5. Open **AI Workspace** in the sidebar (`/ai-workspace`).

**Manual install (no HACS):** copy `custom_components/ai_workspace/` from this repository into `config/custom_components/`, restart, then add the integration as above.

### Requirements

| You need | Details |
|---|---|
| Home Assistant | OS, Supervised, Container, or Core — including Raspberry Pi |
| [HACS](https://hacs.xyz/) | Preferred way to install the integration |
| An MCP | Built-in **MCP Server**, **[HA-MCP](https://github.com/homeassistant-ai/ha-mcp)**, **HA Vibecode Agent**, or another MCP HTTP URL on the LAN |
| An agent | **Either** an OpenAI or Anthropic API key **or** Cursor plus the Runtime |

### Which install is mine?

| Situation | What to install |
|---|---|
| I have an OpenAI or Claude key | HACS integration only |
| Home Assistant OS / Supervised, I want Cursor | HACS integration **and** the Runtime **app** |
| Home Assistant Container, I want Cursor | HACS integration **and** the Cursor **Docker** sidecar on the same host |

### Optional: Cursor Runtime on Home Assistant OS

Skip this if you chose **Cloud API Provider**.

1. Add this repository to Apps:

   [![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdomdus%2Fha-ai-workspace)

   If that opens the App store without an add-repository dialog, add it manually: **Settings → Apps → Install app → ⋮ → Repositories**, then paste `https://github.com/domdus/ha-ai-workspace`.
2. Install **AI Workspace Runtime**, set the **Cursor API key** ([Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) — not a Home Assistant token), and **Start**. The first start builds the image and can take a few minutes.
3. Add the HACS integration if you have not already. Runtime URL is filled in when the app is running.

Home Assistant 2026.2 renamed “Add-ons” to “Apps”; on older versions this is the Add-on store.

### Optional: Cursor Runtime on Home Assistant Container

There is no **Settings → Apps**. The HACS panel is the UI. This container is the Cursor SDK plus a small `/api` — not a second Home Assistant. Run it on the **same host** as Home Assistant.

```bash
git clone https://github.com/domdus/ha-ai-workspace.git
cd ha-ai-workspace
cp runtime.env.example .env
```

Edit `.env`:

```bash
CURSOR_API_KEY=          # https://cursor.com/dashboard/integrations
CURSOR_MODEL=composer-2.5
# Optional. The HACS integration sends MCP on each chat.
# MCP_URL=http://127.0.0.1:8123/api/webhook/<ha-mcp-webhook-id>
```

```bash
docker compose -f docker-compose.runtime.yml up -d --build
```

Host network. Port **8090** is bound to `127.0.0.1` only — do not publish it on the LAN.

Then in the integration: **Chat Backend → Cursor Runtime app**, Runtime URL `http://127.0.0.1:8090`.

If `docker compose build` cannot reach Debian apt, build the image on another machine, tag it `cursor-sdk`, `docker save` / `docker load` it onto the HA host, then `docker compose -f docker-compose.runtime.yml up -d --no-build --force-recreate`.

## Configure

**Settings → Devices & services → AI Workspace → Configure**

| Option | What it does |
|---|---|
| **Chat Backend** | **Cloud API Provider** or **Cursor Runtime app**. Provider fields open after you pick Cloud API Provider. |
| **Provider** | Cloud API only: OpenAI or Claude, API key, optional model. Cursor: optional model overrides `CURSOR_MODEL` on the Runtime — leave empty to keep the container default. |
| **MCP type** | **Home Assistant MCP Server** (built-in `/api/mcp` — add that integration first), **HA-MCP**, **HA Vibecode Agent (Coolver)**, or **Custom MCP URL** |
| **MCP URL** | Leave empty for the default of that type. HA-MCP needs the connect URL from that integration. Custom needs a full MCP HTTP URL. |
| **MCP token** | Built-in: Home Assistant long-lived access token (or empty to use your current login in this chat). HA-MCP: usually empty. Vibecode: Agent Key. Custom: optional Bearer token. |
| **System prompt** | How the Cloud API model should behave. Empty uses the built-in Home Assistant prompt. |
| **Show floating AI button on every page** | Bottom-right **AI** button. Hidden on Settings. |
| **Show AI Workspace in the sidebar** | Sidebar item. `/ai-workspace` still works if this is off. |

MCP type, URL, and token are on this form for both backends. On Cursor they are sent to the Runtime on each chat. The Cursor API key stays on the Runtime.

**Runtime URL** is advanced. Home Assistant OS auto-detects the app. Only set it (YAML, or first setup if the app was not found) if Cursor runs somewhere else that speaks **this** integration’s chat API — not a generic OpenAI, Ollama, or “any local API” URL. On Container that is often `http://127.0.0.1:8090` (host network) or `http://cursor-sdk:8090`.

### Runtime (Cursor only)

**Home Assistant OS:** **Settings → Apps → AI Workspace Runtime → Configuration**

| Option | What it is |
|---|---|
| **Cursor API key** | User API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) |
| **Model** | Default Cursor model id, for example `composer-2.5`. Empty model on the HACS form uses this. |
| **Extra MCP servers** (`mcp_config`) | Optional JSON for GitHub and other LAN MCP servers (merged with the integration MCP URL) |

**Container:** the same values live in `.env` (`CURSOR_API_KEY`, `CURSOR_MODEL`). `MCP_URL` there is only a fallback if something talks to the container without the integration.

## Extra MCP servers

Optional `mcp_config` on the Runtime is merged with the Home Assistant MCP URL from the HACS integration:

```json
{
  "mcpServers": {
    "github": { "url": "http://github-mcp:8080/mcp" }
  }
}
```

## What it does

- **AI Workspace** page (`/ai-workspace`) with chat history.
- Optional floating **AI** button on other pages.
- **Cloud API** (OpenAI or Claude) in the integration, or **Cursor** in the Runtime.
- Uses your existing MCP. Model traffic is **outbound HTTPS**. MCP stays on the LAN.
