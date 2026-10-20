<div align="center">

# AI Workspace
 <em>Build your Home Assistant from the couch.</em>
![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.12+-41BDF5.svg)![Release](https://img.shields.io/github/v/release/domdus/ha-ai-workspace)![License](https://img.shields.io/github/license/domdus/ha-ai-workspace)  
![GHCR](https://img.shields.io/badge/GHCR-runtime-teal)![MCP](https://img.shields.io/badge/MCP-client-purple)![Assist](https://img.shields.io/badge/Assist-ready-green)

</div>

This HACS integration is an agent UI inside Home Assistant. It connects to an AI and uses the MCP server of your choice.
You work right in Home Assistant instead of Claude Desktop, the Cursor IDE, VS Code, or any other app. Use Cursor, OpenAI, Claude, Gemini, DeepSeek, Qwen, Grok, or any OpenAI-compatible provider.

<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai_workspace.gif" alt="AI Workspace chat demo" width="300">
</p>

What the agent can do depends entirely on the MCP server you connect.

- Polished agent chat with streamed replies
- Attachments in chat (text files, images)
- Deep links to devices, entities, automations, and more
- Chat history with pins
- Change History: a list of every change the assistant made to your setup, with **Rollback** from the snapshot taken before the write
- Usage and costs: tokens and estimated cost per agent, model, and chat, with optional Home Assistant sensors for your own dashboards
- Several agents in one chat
- More than one MCP connection
- Optional floating button
- Optional dictation (speech to text, needs HTTPS) and spoken replies (text to speech)
- Assist pipelines that are ready to use — conversation, listening, and speaking already wired

![AI Workspace in the Home Assistant sidebar](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace.png)

An optional button on the other pages opens the same chat.

  
<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai_workspace_floating.gif" alt="Floating button" width="820">
</p>

Each agent can also be added as an Assist pipeline. The integration creates the pipeline for you, so you can use **Cursor AI** (or another AI) from Home Assistant's built-in Assist dialog as well.

OpenAI, OpenRouter, and OpenAI-compatible agents can also listen and speak with the same API key (**Speech-to-text** and **Text-to-speech**, on by default). Gemini can too, with native Google speech (existing Gemini agents stay off until you turn each on). New Assist pipelines from AI Workspace get those voices automatically. You can still change them under **Settings → Voice assistants**. Cursor, Claude, Azure, and Ollama have no voice of their own and use a Home Assistant engine such as Piper.

The OpenAI-style voices (Coral, Echo, …) speak **German, French, and many other languages**. They follow the language of the reply.

![Cursor in Home Assistant Assist](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace-assists.png)

The **Usage** page shows tokens and estimated cost per agent, model, and day, so you can see which model is worth it for your home. Prices come from the public price list of [LiteLLM](https://github.com/BerriAI/litellm). AI Workspace uses a small copy of that list, refreshed every week. More in [Cost and tokens](docs/cost.md).

![AI Workspace Usage page](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace_usage.png)

## Requirements

- Home Assistant **2025.12** or newer
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

Until it is in the default HACS store, add it as a custom repository: **HACS → Integrations → ⋮ → Custom repositories** → `https://github.com/domdus/ha-ai-workspace` (category **Integration**) → **Download** → **Restart Home Assistant**.

**Manual install (no HACS):** copy `custom_components/ai_workspace/` from this repository into your Home Assistant `config/custom_components/` directory, restart, and add the integration as below.

### 2. Add the integration

**Settings → Devices & services → Add integration → AI Workspace.**

- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first **agent**.
- Pick the provider. Paste the key, use **Get an API key** under the field, or choose **Copy key from** when OpenRouter, OpenAI, Claude, Gemini, Ollama, or Azure is already set up. The key is checked before it is saved.
- Add more agents later with **Add agent** on the AI Workspace entry. The chat shows an agent picker when more than one is set up.

You can also put the same settings in `configuration.yaml`. See [YAML configuration](docs/settings.md#yaml-configuration).



### 3. Start using it

Open **AI Workspace** (`/ai-workspace`) and ask: `List my automations.`

---



## Cursor AI (Advanced)

Use **Cursor AI** in Home Assistant through the Cursor SDK, without the Cursor desktop app. The agent uses your MCP tools, works through tasks with several steps, and picks up where it left off in each chat. There is no editor: you chat in AI Workspace.

Install AI Workspace from HACS first ([step 1](#1-install-ai-workspace-from-hacs)).

### Option A: Use via OpenRouter

Start here. You get many of the same models people use in Cursor (Claude, GPT, Gemini, Grok, and others) with one OpenRouter key. There is no Cursor SDK runtime to install.

Add an **OpenRouter** agent as in [Cloud AI](#cloud-ai-api-provider-quick). Pick **OpenRouter**, paste the key (or **Copy key from** if Home Assistant already has OpenRouter), and choose a model.

Cursor's own models (**Composer**, Tab completion) are not on OpenRouter. If you use Cursor's desktop app with OpenRouter, that is a Cursor setting, not AI Workspace. See [OpenRouter's Cursor notes](https://openrouter.ai/docs/cookbook/coding-agents/cursor-integration).

Options B and C run the Cursor SDK yourself, when you want Composer or a Cursor API key in Home Assistant.

### Option B: Home Assistant OS / Supervised (App)

The Cursor SDK runs as an app on the same machine as Home Assistant.

![Home Assistant OS with Cursor SDK and Cursor Cloud AI](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/os-architecture.jpg)

Add this repository to Apps and install **AI Workspace Runtime**:

![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)

Paste the Cursor API key on the app and **Start** it. Leave the Runtime URL on the integration empty; it is detected once the app runs. The integration also creates the shared [runtime token](#runtime-token) and writes it to the app for you.

Home Assistant 2026.2 renamed "Add-ons" to "Apps".

### Option C: Home Assistant Container (Docker)

If Home Assistant runs in Docker without the Supervisor, it needs one extra container next to it. The wiring is the same as in Option B: **AI Workspace** talks to the **Cursor SDK**, and the SDK talks to **Cursor** and to **MCP**.

![Home Assistant container, Cursor SDK, Cursor Cloud AI](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/docker-architecture.jpg)

Paste your Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) into [docker-compose.runtime.yml](docker-compose.runtime.yml):

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

**Host network** (`network_mode: host`, as above) matches a typical Home Assistant Container. The runtime reaches MCP at `127.0.0.1` on this machine, and `HOST: 127.0.0.1` keeps port **8090** off your network. The runtime token is optional here.

Running Docker's default bridge network instead, giving the agent a folder of files, or letting it work in a git repository: see [Cursor runtime in Docker](docs/cursor-runtime.md).

### Runtime token

The integration and the runtime share a token, and every chat request carries it.

- **App (Home Assistant OS):** nothing to do. The integration generates the token, stores it on the app, and restarts the app once.
- **Docker:** generate one, for example with `openssl rand -hex 32`. Put it in `RUNTIME_TOKEN` on the container and in **Cursor agent → Runtime token**.



### Add the integration (Options B and C)

After the runtime is running: **Settings → Devices & services → Add integration → AI Workspace.**

- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first agent. Choose **Cursor**.
- **Cursor Runtime URL:** leave empty unless the form does not show **Runtime found**. It is filled only when this Home Assistant can reach the Runtime (`http://127.0.0.1:8090` or the app). Do not paste a Docker hostname unless Home Assistant can reach that container.
- **Model:** pick one from the list or type a model name, for example `composer-2.5`, `grok-4.7`, `gpt-5`, or `claude-sonnet-5-5`. Leave it empty to use `CURSOR_MODEL` from the runtime.
- Paste the Cursor API key, unless the runtime already has one.
- Open **AI Workspace** (`/ai-workspace`).



## Local AI (Ollama)

This works like Cloud AI, with **Ollama** (or LM Studio) on your own hardware. The chat never leaves the house. The model must support tool calls. On a small machine set **Reduce token usage** to **Extreme** in AI Workspace settings: the chat then sends a short prompt and no tools, so it can answer questions, but it cannot check or change the house. **Medium** still sends tools with a short prompt. See [Reduce token usage](docs/cost.md#reduce-token-usage).

Install as in [Cloud AI](#cloud-ai-api-provider-quick). Pick **Ollama** and point the API Base URL at your Ollama server.

![Home Assistant and Ollama](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ollama-architecture.jpg)

## More in the docs

The [docs](docs/README.md) go further once you are up and running:

- [Settings](docs/settings.md) — every option, what it does, and why it matters
- [Cost and tokens](docs/cost.md) — Usage page, where prices come from, token modes, and prompt cache
- [Cursor runtime in Docker](docs/cursor-runtime.md) — bridge network, files on disk, and git
- [Privacy](docs/privacy.md) — what leaves the house, who can chat, Assist satellites
- [MCP and Change History](docs/mcp.md) — connections, large tool results, and the change log
- [Troubleshooting](docs/troubleshooting.md) — common errors and how to remove AI Workspace

## Community

- **[GitHub Discussions](https://github.com/domdus/ha-ai-workspace/discussions):** ask questions and share ideas
- **[Issue Tracker](https://github.com/domdus/ha-ai-workspace/issues):** report bugs, request features, or suggest tool behavior improvements

