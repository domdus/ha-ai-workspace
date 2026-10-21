<div align="center">

# AI Workspace
 <em>Build your Home Assistant from the couch.</em>

![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.12+-41BDF5.svg)![Release](https://img.shields.io/github/v/release/domdus/ha-ai-workspace)![License](https://img.shields.io/github/license/domdus/ha-ai-workspace)  
![GHCR](https://img.shields.io/badge/GHCR-runtime-teal)![MCP](https://img.shields.io/badge/MCP-client-purple)![Assist](https://img.shields.io/badge/Assist-ready-green)

</div>

Talk to an AI inside Home Assistant. Ask it to list your lights, write an automation, or fix a dashboard. It reaches the house through the MCP server you connect — that is what lets it see and change things, not a copy of your YAML on disk.

You stay in Home Assistant. No Claude Desktop, no Cursor app, no VS Code. AI Agents such as Cursor, OpenAI, Claude, Gemini, DeepSeek, Qwen, Grok, or any OpenAI-compatible model all work in the same chat.

<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai_workspace.gif" alt="AI Workspace chat demo" width="300">
</p>

What it can do depends on that MCP server. In the chat you get:

- Answers that appear as they are written
- Pictures and text files you drop in
- Names that link straight into Home Assistant (devices, automations, dashboards)
- Chats you can pin, and a **Change History** of every write, with **Rollback** to the snapshot from before the change. Automations, scripts, and scenes also land as YAML under `config/ai_workspace/changes/` if Home Assistant will not start ([how to restore by hand](docs/mcp.md#if-home-assistant-will-not-start))
- Tokens and estimated cost per agent, model, and chat (optional sensors for your own dashboards)
- More than one agent and more than one MCP connection
- An optional floating button on other pages
- Optional talk and listen (HTTPS for the microphone)
- The same agents in Assist, already wired for conversation, listening, and speaking

![AI Workspace in the Home Assistant sidebar](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace.png)

An optional button on the other pages opens the same chat.

  
<p align="center">
  <img src="https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai_workspace_floating.gif" alt="Floating button" width="820">
</p>

Each agent can also show up in Home Assistant's Assist dialog. AI Workspace creates that pipeline for you, so you can talk to **Cursor AI** (or another agent) from the microphone as well.

OpenAI, OpenRouter, and OpenAI-compatible agents can listen and speak with the same key you already pasted (on by default). Gemini can too, with Google's own voices — existing Gemini agents stay quiet until you turn that on. New Assist pipelines pick those voices up; you can still change them under **Settings → Voice assistants**. Cursor, Claude, Azure, and Ollama have no voice of their own, so they use something like Piper.

Coral, Echo, and the other OpenAI-style voices speak **German, French, and many other languages**. They follow the language of the reply.

![Cursor in Home Assistant Assist](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace-assists.png)

The **Usage** page shows tokens and estimated cost per agent, model, and day, so you can see which model is worth it for your home. Prices come from the public price list of [LiteLLM](https://github.com/BerriAI/litellm). AI Workspace uses a small copy of that list, refreshed every week. More in [Cost and tokens](docs/cost.md).

![AI Workspace Usage page](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace_usage.png)

## Requirements

- Home Assistant **2025.12** or newer
- A **provider API key** from that provider's API console (⚠️ not a ChatGPT or Claude.ai plan; usually paid API credits), a local **Ollama** server, or a **Cursor API key** (Cursor SDK Runtime)

You also need an MCP server:

- [Home Assistant MCP Server](https://www.home-assistant.io/integrations/mcp_server/) (built into Home Assistant)
- [HA-MCP](https://github.com/homeassistant-ai/ha-mcp) (highly recommended)
- [HA Vibecode Agent](https://github.com/Coolver/home-assistant-vibecode-agent)
- Any other or **custom MCP URL** if you already run something else

---



## Cloud AI (quick start)

Add an agent for **OpenAI**, **Claude**, **Gemini**, **DeepSeek**, **Qwen**, **Grok**, **OpenRouter**, **Azure OpenAI**, **local Ollama**, or **OpenAI-compatible** (LM Studio and others). The model has to be able to call tools, or it cannot see your house. If that provider is already set up in Home Assistant, the form can copy its key.

You type in **AI Workspace**. The reply comes from that provider. **MCP** is how the model reaches Home Assistant.

⚠️ A ChatGPT or Claude.ai subscription does not include this. OpenAI and Claude need API credits on [platform.openai.com](https://platform.openai.com) and [console.anthropic.com](https://console.anthropic.com). Gemini has a free API tier with limits. OpenRouter is its own credit balance (it then pays the model behind it). Ollama stays on your hardware and does not bill a cloud API.

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



### 3. Try it

Open **AI Workspace** (`/ai-workspace`) and ask things like:

- List my automations
- Why is the hallway light on?
- Create an automation that turns on the lights when there is motion
- Add a card on Overview for the outdoor temperature

---



## Cursor AI (advanced)

Want Cursor's own agent in that same chat, without opening the Cursor app? It can work through a longer task and pick up the thread next time. There is still no editor: you only chat in AI Workspace.

If you only want Claude or GPT, skip this and use [Cloud AI](#cloud-ai-quick-start) above. The extra runtime is for Cursor's own models (**Composer**, **Grok**) and a Cursor API key.

**Notice**
> You can get Cursor models with one [OpenRouter](https://openrouter.ai) key. No Cursor SDK runtime to install this way. Add that under [Cloud AI](#cloud-ai-quick-start).


Cursor's own **Composer** and Tab completion are not on OpenRouter. If the Cursor desktop app uses OpenRouter, that is a Cursor setting, not AI Workspace. See [OpenRouter's Cursor notes](https://openrouter.ai/docs/cookbook/coding-agents/cursor-integration).


Install AI Workspace from HACS first ([step 1](#1-install-ai-workspace-from-hacs)).

### Option A: Home Assistant OS / Supervised (App)

The Cursor SDK runs as an app on the same machine as Home Assistant.

![Home Assistant OS with Cursor SDK and Cursor Cloud AI](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/os-architecture.jpg)

Add this repository to Apps and install **AI Workspace Runtime**:

![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)

Paste the Cursor API key on the app and **Start** it. Leave the Runtime URL on the integration empty; it is detected once the app runs. The integration also creates the shared [runtime token](#runtime-token) and writes it to the app for you.

Home Assistant 2026.2 renamed "Add-ons" to "Apps".

### Option B: Home Assistant Container (Docker)

If Home Assistant is a Docker container (no Supervisor), Cursor needs one extra container beside it. Same idea as the app: Home Assistant talks to that runtime, and the runtime talks to Cursor and to MCP.

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



### Add the integration (Options A and B)

After the runtime is running: **Settings → Devices & services → Add integration → AI Workspace.**

- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first agent. Choose **Cursor**.
- **Cursor Runtime URL:** leave empty unless the form does not show **Runtime found**. It is filled only when this Home Assistant can reach the Runtime (`http://127.0.0.1:8090` or the app). Do not paste a Docker hostname unless Home Assistant can reach that container.
- **Model:** pick one from the list or type a model name, for example `composer-2.5`, `grok-4.7`, `gpt-5`, or `claude-sonnet-5-5`. Leave it empty to use `CURSOR_MODEL` from the runtime.
- Paste the Cursor API key, unless the runtime already has one.
- Open **AI Workspace** (`/ai-workspace`).



## Local AI (Ollama)

Same as Cloud AI, but the model runs in your house (**Ollama** or LM Studio). Nothing is sent to a cloud API. The model still has to be able to call tools.

On a small machine, set **Reduce token usage** to **Extreme** in AI Workspace settings. The chat then stays short and does not send tools: it can answer questions, but it cannot check or change the house. **Medium** still sends tools, with a shorter prompt. See [Reduce token usage](docs/cost.md#reduce-token-usage).

Install as in [Cloud AI](#cloud-ai-quick-start). Pick **Ollama** and point the API Base URL at your Ollama server.

![Home Assistant and Ollama](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ollama-architecture.jpg)

## More in the docs

The [docs](docs/README.md) go further once you are up and running:

- [Settings](docs/settings.md) — every option, what it does, and why it matters
- [Cost and tokens](docs/cost.md) — Usage page, where prices come from, token modes, and prompt cache
- [Cursor runtime in Docker](docs/cursor-runtime.md) — bridge network, files on disk, and git
- [Privacy](docs/privacy.md) — what leaves the house, who can chat, Assist satellites
- [MCP and Change History](docs/mcp.md) — connections, large tool results, the change log, and restoring YAML by hand if Home Assistant will not start
- [Troubleshooting](docs/troubleshooting.md) — common errors and how to remove AI Workspace

## Community

- **[GitHub Discussions](https://github.com/domdus/ha-ai-workspace/discussions):** ask questions and share ideas
- **[Issue Tracker](https://github.com/domdus/ha-ai-workspace/issues):** report bugs, request features, or suggest tool behavior improvements

## Contributing

Open an issue or send a pull request from a fork. The chat is `custom_components/ai_workspace/`. The Cursor runtime is `ai_workspace/`.

