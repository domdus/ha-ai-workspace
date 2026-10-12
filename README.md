<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/ai_workspace/logo.png" alt="AI Workspace" width="420">
</p>

<p align="center"><em>Build your Home Assistant from the couch.</em></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai_workspace.gif" alt="AI Workspace chat demo" width="300">
</p>

<h1 align="center">AI Workspace</h1>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home%20Assistant-2026.1+-41BDF5.svg" alt="Home Assistant"></a>
  <a href="https://github.com/domdus/ha-ai-workspace/releases"><img src="https://img.shields.io/github/v/release/domdus/ha-ai-workspace" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/domdus/ha-ai-workspace.svg" alt="License"></a>
  <br>
  <a href="https://github.com/domdus/ha-ai-workspace/commits/main"><img src="https://img.shields.io/github/commit-activity/m/domdus/ha-ai-workspace.svg" alt="Activity"></a>
  <a href="https://github.com/domdus/ha-ai-workspace/actions/workflows/runtime-image.yml"><img src="https://img.shields.io/github/actions/workflow/status/domdus/ha-ai-workspace/runtime-image.yml?branch=main&label=Runtime%20image" alt="Runtime image"></a>
  <a href="https://github.com/domdus/ha-ai-workspace/pkgs/container/ha-ai-workspace-runtime"><img src="https://img.shields.io/badge/GHCR-runtime-teal" alt="GHCR"></a>
  <img src="https://img.shields.io/badge/MCP-client-purple" alt="MCP">
  <img src="https://img.shields.io/badge/Assist-ready-green" alt="Assist">
</p>

This HACS integration is an agent UI inside Home Assistant. It connects to an AI and uses the MCP server of your choice.
You work right in Home Assistant instead of Claude Desktop, the Cursor IDE, VS Code, or any other app. Use Cursor, OpenAI, Claude, Gemini, DeepSeek, Qwen, Grok, or any OpenAI-compatible provider.

What the agent can do depends entirely on the MCP server you connect.

- Polished agent chat with streamed replies
- Attachments in chat (text files, images)
- Deep links to devices, entities, automations, and more
- Chat history with pins
- Several agents in one chat
- More than one MCP connection
- Optional floating button on every page
- Optional dictation (speech to text, needs HTTPS) and spoken replies (text to speech)

<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace.png" alt="AI Workspace in the Home Assistant sidebar" width="820">
</p>

Each agent can also be added as an Assist pipeline. The integration creates the pipeline for you, so you can use **Cursor AI** (or another AI) from Home Assistant's built-in Assist dialog as well.

<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace-assists.png" alt="Cursor in Home Assistant Assist" width="820">
</p>

## Requirements

- Home Assistant **2026.1** or newer
- A **provider API key** (cloud AI), a local **Ollama** server, or a **Cursor API key** (Cursor SDK Runtime)

You also need an MCP server:

- [Home Assistant MCP Server](https://www.home-assistant.io/integrations/mcp_server/) (built into Home Assistant)
- [HA-MCP](https://github.com/homeassistant-ai/ha-mcp) (recommended)
- [HA Vibecode Agent](https://github.com/Coolver/home-assistant-vibecode-agent)
- A **custom MCP URL** if you already run something else

---

## Cloud AI API Provider (Quick)

This is the fastest path. Add an agent for **OpenAI**, **Claude**, **Gemini**, **DeepSeek**, **Qwen**, **Grok**, **OpenRouter**, **Azure OpenAI**, **local Ollama**, or **OpenAI-compatible** (LM Studio and others). The model must support tool calls, or it cannot use MCP. If that provider is already set up in Home Assistant, the agent form can copy its key.

You chat in **AI Workspace**. It calls the provider's API. **MCP** is how that model reaches Home Assistant.

![AI Workspace, MCP, Home Assistant, AI Cloud API](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/cloud-architecture.jpg)

### 1. Install AI Workspace from HACS

[![Add AI Workspace to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domdus&repository=ha-ai-workspace&category=integration)

Or **HACS → Integrations → ⋮ → Custom repositories** → `https://github.com/domdus/ha-ai-workspace` (category **Integration**) → **Download** → **Restart Home Assistant**.

**Manual install (no HACS):** copy `custom_components/ai_workspace/` from this repository into your Home Assistant `config/custom_components/` directory, restart, and add the integration as below.

### 2. Add the integration

**Settings → Devices & services → Add integration → AI Workspace.**

- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first **agent**.
- Pick the provider. Paste the key, or choose **Copy key from** when OpenRouter, OpenAI, Claude, Gemini, Ollama, or Azure is already set up. The key is checked before it is saved.
- Add more agents later with **Add agent** on the AI Workspace entry. The chat shows an agent picker when more than one is set up.

### 3. Start using it

Open **AI Workspace** (`/ai-workspace`) and ask: `List my automations.`

---

## Cursor AI (Advanced)

This integration works with **Cursor AI** through the Cursor SDK, without the desktop IDE: MCP tools, multi-step work, and agents that can be resumed. It runs headless, with no editor and no Composer UI.

Install AI Workspace from HACS first ([step 1](#1-install-ai-workspace-from-hacs)). Then install the **Cursor SDK Runtime** once, for the Home Assistant you run.

### Option A: Home Assistant OS / Supervised (App)

The Cursor SDK runs as an app on the same machine as Home Assistant.

![Home Assistant OS with Cursor SDK and Cursor Cloud AI](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/os-architecture.jpg)

Add this repository to Apps and install **AI Workspace Runtime**:

[![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdomdus%2Fha-ai-workspace)

Paste the Cursor API key on the app and **Start** it. Leave the Runtime URL on the integration empty; it is detected once the app runs. The integration also creates the shared [runtime token](#runtime-token) and writes it to the app for you.

Home Assistant 2026.2 renamed "Add-ons" to "Apps".

### Option B: Home Assistant Container (Docker)

If Home Assistant runs in Docker without the Supervisor, it needs one extra container next to it. The wiring is the same as in Option A: **AI Workspace** talks to the **Cursor SDK**, and the SDK talks to **Cursor** and to **MCP**.

![Home Assistant container, Cursor SDK, Cursor Cloud AI](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/docker-architecture.jpg)

Paste your Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) into [`docker-compose.runtime.yml`](docker-compose.runtime.yml):

```yaml
name: ai-workspace-runtime

services:
  cursor-sdk:
    container_name: cursor-sdk
    image: ghcr.io/domdus/ha-ai-workspace-runtime:latest
    build: ./ai_workspace
    network_mode: host
    environment:
      CURSOR_API_KEY: "paste-your-cursor-api-key"
      CURSOR_MODEL: composer-2.5
      RUNTIME_TOKEN: ""
      AUTH_MODE: ingress
      DATA_DIR: /data
      HOST: "127.0.0.1"
      PORT: "8090"
    volumes:
      - ai-workspace-data:/data
    restart: unless-stopped

volumes:
  ai-workspace-data:
```

```bash
docker compose -f docker-compose.runtime.yml up -d
```

That pulls the image from [GHCR](https://github.com/domdus/ha-ai-workspace/pkgs/container/ha-ai-workspace-runtime) (`linux/amd64` and `linux/arm64`). To build from this repository instead (`ai_workspace/Dockerfile`):

```bash
docker compose -f docker-compose.runtime.yml up -d --build
```

**Host network** (`network_mode: host`, as above) is the same as a typical Home Assistant Container. MCP at `127.0.0.1` on this machine works, and `HOST: 127.0.0.1` keeps port **8090** off the LAN. The runtime token is optional here.

**Bridge network** is Docker's default when you leave out `network_mode: host`. Inside the container, `127.0.0.1` is the container itself, not Home Assistant, so loopback MCP URLs are rewritten to the Docker host. Remove `network_mode` and use:

```yaml
    ports:
      - "127.0.0.1:8090:8090"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      HOST: "0.0.0.0"
      RUNTIME_TOKEN: "a-long-random-value"
      REWRITE_LOOPBACK_HOST: host.docker.internal
```

`127.0.0.1:8090:8090` still keeps port **8090** off the LAN. If Home Assistant is another container on the same bridge, set the Runtime URL to `http://cursor-sdk:8090`. A runtime that listens on anything other than loopback refuses chats until `RUNTIME_TOKEN` is set.

### Runtime token

The integration and the runtime share a token, and every chat request carries it.

- **App (Home Assistant OS):** nothing to do. The integration generates the token, stores it on the app, and restarts the app once.
- **Docker:** generate one, for example with `openssl rand -hex 32`. Put it in `RUNTIME_TOKEN` on the container and in **AI Workspace → Configure → Runtime token**.

### Add the integration

After the runtime is running: **Settings → Devices & services → Add integration → AI Workspace.**

- **Runtime URL:** leave empty (it should find `http://127.0.0.1:8090` or the app).
- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first agent. Choose **Cursor**.
- **Model:** for example `composer-2.5`, `grok-4`, `gpt-4.1`, or `claude-sonnet-4-5`. Leave it empty to use `CURSOR_MODEL` from the runtime.
- Paste the Cursor API key, unless the runtime already has one.
- Open **AI Workspace** (`/ai-workspace`).

## Local AI (Ollama)

This works like Cloud AI, with **Ollama** (or LM Studio) on your own hardware. The chat never leaves the house. The model must support tool calls. Turn on **Low token** on that agent when the machine is small: the chat then sends a short prompt and no tools, so it can answer questions, but it cannot check or change the house.

Install as in [Cloud AI](#cloud-ai-api-provider-quick). Pick **Ollama** and point the API Base URL at your Ollama server.

![Home Assistant and Ollama](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ollama-architecture.jpg)

## How it is organized

AI Workspace is one integration entry with two kinds of rows:

- **Connection:** one row per MCP server. The first one is created during setup; **Add connection** adds more.
- **Agent:** one row per Cursor, OpenAI, Claude, Gemini, OpenRouter, Ollama, Azure, or other provider. **Add agent** adds more.

Each row has its own device. Disable a device to switch off one MCP connection or one agent without deleting it.

## System Prompt

**Settings → Devices & services → AI Workspace → Configure**

This is the standing instruction for the assistant. Use it for your own needs: how you name rooms, which automations to leave alone, how short answers should be, or any other rule. What you write here replaces the built-in prompt. Leave the field empty to keep the built-in text, which covers helping with this Home Assistant and asking before it changes the house. The same text is used for cloud APIs and the Cursor Runtime.

It does not control Home Assistant edit links. Those rules are added to every message, so automations, entities, helpers, and devices stay tappable.

## Options

| Option | What it does |
|---|---|
| **Copy key from** | Uses the key already stored by OpenRouter, OpenAI, Claude, Gemini, Ollama, or Azure in Home Assistant. That integration stays as it is |
| **Effort** | Default, Fast, High, or High fast when the model supports it. A provider that rejects it is retried without |
| **Low token** | Not on Cursor. Sends a short prompt and no tools |
| **MCP type** | Asked once, when you add AI Workspace: built-in MCP Server, HA-MCP, HA Vibecode Agent, or a custom URL. It becomes the first connection |
| **MCP URL** | Empty uses auto-detect. Paste the HA-MCP webhook or a custom URL only if needed |
| **MCP token** | Built-in MCP Server: empty uses the login of the person chatting. HA-MCP: usually empty. Vibecode: Agent Key |
| **Runtime URL** / **Runtime token** | Where the Cursor SDK Runtime listens, and the shared token. See [Runtime token](#runtime-token) |
| **System prompt** | See [System Prompt](#system-prompt). Empty uses the built-in prompt |
| **Show floating AI button on every page** | Bottom-right robot icon. Hidden on Settings pages |
| **Speech to text** | Browser speech, or a Home Assistant engine such as Whisper. The microphone needs https:// or localhost; browsers block it on a plain http:// LAN address |
| **Text to speech** | Piper or another Home Assistant voice. The speaker button plays a reply, also on plain http://. Off leaves replies as text |
| **Speak replies automatically** | Off by default. When a voice is selected, each reply is read aloud as it arrives |
| **Show dictate button** | Microphone in the prompt field. On by default |
| **Show AI Workspace in the sidebar** | Sidebar item. `/ai-workspace` still works when this is off |
| **Allow normal users** | Off by default. See [Privacy and security](#privacy-and-security) |
| **Chats to keep** | Newest unpinned chats per person (default 30). Pinned chats are always kept |
| **Cross chat** | Off by default. When on, a question can use another chat whose title shares words with it. Only a short excerpt is used, and that chat is not changed |
| **Config catalog** | Off by default. Indexes the wiring of named items (triggers, related ids). Lists, counts, and on/off still come from live MCP. No live state, history, or traces |
| **Also use in Assist** | On each agent. Off (the default) keeps the agent in AI Workspace only. On adds a Voice assistants pipeline for it |

## Optimization: Large listings

When an MCP tool sends back the whole house, the result is shortened before the model reads it. Entities are grouped by area as ids only, and the model can ask again for one area or one entity to load states and attributes. A shorter list keeps each entity's state and drops the bulky attributes. One entity, one room, or one automation still arrives whole. What the model receives is always valid JSON; nothing is cut off in the middle of an object. This is automatic for cloud APIs and the Cursor Runtime.

## Privacy and security

- **What leaves the house:** your messages, attachments, the system prompt, the page you are on, and every MCP tool result go to the AI provider you picked (or to Cursor through the runtime). Only Ollama or another local server keeps everything at home.
- **What stays local:** chat history is stored in `config/ai_workspace/ai-workspace.sqlite`. API keys live in Home Assistant's config entries, like any other integration.
- **Who can use it:** only admins by default. The sidebar panel is always admin-only.
- **Allow normal users:** when this is on, people who are not admins get the floating chat. They only get the built-in **Home Assistant MCP Server**, using their own login, and never the admin's MCP connections or the config catalog. What they can see and do is then whatever Home Assistant exposes to them through Assist. **Only turn this on if you trust everyone with a login to chat with an AI that can act on the house.**
- **Voice satellites:** Assist from a satellite has no signed-in person, so it uses the tools the admin configured. The built-in MCP Server needs a login, so set a long-lived access token in that connection's **MCP token** when satellites should reach it. HA-MCP and Vibecode bring their own credentials.
- **Runtime:** keep port 8090 and your MCP servers off the internet. The runtime only accepts HTTP MCP servers from the integration and rejects every request without the runtime token, unless it listens on loopback.

## Cost

Every message sends the system prompt and the tool list of every connected MCP server. HA-MCP alone offers about 80 tools, which is several thousand tokens before you type anything, and tool results add more. Long chats resend the history each turn. Pick a small model for everyday questions, use **Low token** for chat without tools, or start a new chat when the topic changes. Cursor usage is billed through your Cursor plan.

## Troubleshooting

- **"Runtime token is missing or wrong."** The token on the integration and on the runtime differ. On Docker, copy `RUNTIME_TOKEN` into **Configure → Runtime token**. On the app, the integration pairs by itself as long as its own Runtime token field was never filled in; if you typed one there, use the same value as the app's **Runtime token** option.
- **The agent invents answers instead of checking.** Cloud AI and Ollama agents ask the model to call a tool first for every message that is not a greeting or thanks. Some models (often small local ones) ignore that request. Use a model with reliable tool calling (for example GPT-4.1 mini, Claude Sonnet, Gemini 2.5, or Composer) and check that the MCP connection's device is enabled.
- **Built-in MCP Server tools are missing in Assist.** That server needs a login, and a voice satellite has none. Set a long-lived token on the connection (see [Privacy and security](#privacy-and-security)).
- **The microphone is greyed out.** Open Home Assistant over https:// (Nabu Casa or a reverse proxy) or on localhost.
- **More detail:** add this to `configuration.yaml` and restart, then check **Settings → System → Logs**:

  ```yaml
  logger:
    logs:
      custom_components.ai_workspace: debug
  ```

## Remove it

1. **Settings → Devices & services → AI Workspace → ⋮ → Delete.** That removes all connections, agents, and their Assist pipelines.
2. **HACS → AI Workspace → Remove**, then restart.
3. Runtime: remove the **app**, or run `docker compose down` in the runtime compose folder (`docker rm -f cursor-sdk` if an old container remains).
4. Optional: delete `config/ai_workspace/` to remove the chat history.

## Community

- **[GitHub Discussions](https://github.com/domdus/ha-ai-workspace/discussions):** ask questions and share ideas
- **[Issue Tracker](https://github.com/domdus/ha-ai-workspace/issues):** report bugs, request features, or suggest tool behavior improvements

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
