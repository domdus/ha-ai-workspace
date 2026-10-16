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
- Change History of recorded agent configuration writes (a log, not an undo). When HA-MCP is connected, **Ask to restore** tells the current chat to list HA-MCP’s edit backups
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

OpenAI, OpenRouter, and OpenAI-compatible agents can add **Speech-to-text** and **Text-to-speech** from the same API key (on by default). New AI Workspace Assist pipelines get those engines so they can listen and speak. Later STT/TTS on a pipeline stay as you set them in Voice assistants, including Google Translate or none. The overlay Text-to-speech dropdown is the same: it keeps the engine you pick. Cursor has no speech API of its own. Claude, Gemini, and local Ollama stay on a Home Assistant TTS engine such as Piper unless you assign one.

The OpenAI-style voices (Coral, Echo, …) speak **German, French, and many other languages**. There is no extra German voice to install: they follow the language of the reply.

![Cursor in Home Assistant Assist](https://raw.githubusercontent.com/domdus/ha-ai-workspace/main/docs/ai-workspace-assists.png)

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

![Add AI Workspace to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)

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

Install AI Workspace from HACS first ([step 1](#1-install-ai-workspace-from-hacs)).

### Option A: Use via OpenRouter

Start here. You get many of the same models people use in Cursor (Claude, GPT, Gemini, Grok, and others) with one OpenRouter key. There is no Cursor SDK runtime to install.

Add an **OpenRouter** agent as in [Cloud AI](#cloud-ai-api-provider-quick). Pick **OpenRouter**, paste the key (or **Copy key from** if Home Assistant already has OpenRouter), and choose a model.

Cursor's own models (**Composer**, Tab completion) are not on OpenRouter. Cursor also does not list OpenRouter as a first-class BYOK provider; the desktop IDE can still talk to OpenRouter through an OpenAI base-URL override (`https://openrouter.ai/api/v1/cursor`). That is a Cursor workaround, not this integration. See [OpenRouter's Cursor notes](https://openrouter.ai/docs/cookbook/coding-agents/cursor-integration).

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

Paste your Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) into `[docker-compose.runtime.yml](docker-compose.runtime.yml)`:

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
- **Docker:** generate one, for example with `openssl rand -hex 32`. Put it in `RUNTIME_TOKEN` on the container and in **Cursor agent → Runtime token**.



### Add the integration (Options B and C)

After the runtime is running: **Settings → Devices & services → Add integration → AI Workspace.**

- **MCP type:** one from [Requirements](#requirements). Leave the MCP URL empty if it shows as detected.
- Save. Home Assistant then asks for the first agent. Choose **Cursor**.
- **Cursor Runtime URL:** leave empty unless the form does not show **Runtime found**. It is filled only when this Home Assistant can reach the Runtime (`http://127.0.0.1:8090` or the app). Do not paste a compose hostname that never answered.
- **Model:** pick one from the list or type an id, for example `composer-2.5`, `grok-4.7`, `gpt-5`, or `claude-sonnet-5-5`. Leave it empty to use `CURSOR_MODEL` from the runtime.
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

Each row has its own device. Disable a device to switch off one MCP connection or one agent without deleting it. Two connections that share a tool name get a short prefix (`ha__…`, `hamcp__…`); names sent to OpenAI stay at most 64 characters. Turning off **All LLM APIs** or unloading **MCP Server** hides the built-in `/api/mcp` tools even if the connection row is still there — that is not the same as disabling the AI Workspace device.

## System Prompt

**Settings → Devices & services → AI Workspace → Configure**

This is the standing instruction for the assistant. Use it for your own needs: how you name rooms, which automations to leave alone, how short answers should be, or any other rule. What you write here replaces the built-in prompt. Leave the field empty to keep the built-in text, which covers helping with this Home Assistant and asking before it changes the house. The same text is used for cloud APIs and the Cursor Runtime.

It does not control Home Assistant edit links. Those rules are added to every message, so automations, entities, helpers, and devices stay tappable.

## Options


| Option                                     | What it does                                                                                                                                                                        |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Copy key from**                          | Uses the key already stored by OpenRouter, OpenAI, Claude, Gemini, Ollama, or Azure in Home Assistant. That integration stays as it is                                              |
| **Effort**                                 | Default, Fast, High, or High fast when the model supports it. A provider that rejects it is retried without                                                                         |
| **Low token**                              | Not on Cursor. Sends a short prompt and no tools                                                                                                                                    |
| **Always check the house first**           | Not on Cursor. On by default. The model must call a tool before it answers, so lists, counts, and states come from Home Assistant. See [why](#why-the-agent-checks-the-house-first) |
| **MCP type**                               | Asked once, when you add AI Workspace: built-in MCP Server, HA-MCP, HA Vibecode Agent, or a custom URL. It becomes the first connection                                             |
| **MCP URL**                                | Empty uses auto-detect. Paste the HA-MCP webhook or a custom URL only if needed                                                                                                     |
| **MCP token**                              | Built-in MCP Server: empty uses the login of the person chatting. HA-MCP: usually empty. Vibecode: Agent Key                                                                        |
| **Cursor Runtime URL** / **Runtime token** | On the **Cursor** agent form, not AI Workspace Configure. Filled only when `/api/health` answers. See [Runtime token](#runtime-token)                                                |
| **System prompt**                          | See [System Prompt](#system-prompt). Empty uses the built-in prompt                                                                                                                 |
| **Show floating AI button**                | Turns the button on or off. Bottom-right robot icon. It slides up only when another corner button is on the page                                                                    |
| **Speech to text**                         | Browser speech, or a Home Assistant engine such as Whisper. The microphone needs https:// or localhost; browsers block it on a plain http:// LAN address                            |
| **Text to speech**                         | Piper, Google Translate, or an AI Workspace voice from an OpenAI-style agent. The speaker button plays a reply, also on plain http://. Off leaves replies as text                   |
| **Speak replies automatically**            | Off by default. When a voice is selected, each reply is read aloud as it arrives                                                                                                    |
| **Show dictate button**                    | Microphone in the prompt field. On by default                                                                                                                                       |
| **Show AI Workspace in the sidebar**       | Sidebar item. `/ai-workspace` still works when this is off                                                                                                                          |
| **Allow normal users**                     | Off by default. See [Privacy and security](#privacy-and-security)                                                                                                                   |
| **Chats to keep**                          | Newest unpinned chats per person (default 30). Pinned chats are always kept                                                                                                         |
| **Cross chat**                             | Off by default. When on, a question can use another chat whose title shares words with it. Only a short excerpt is used, and that chat is not changed                               |
| **Config catalog**                         | Off by default. A local index of how automations are wired, so "what uses the kitchen light?" takes one lookup. See [why](#why-use-the-config-catalog)                              |
| **Shorten large MCP tool results**         | On by default. Same setting for cloud agents and Cursor. See [MCP proxy](#mcp-proxy)                                                                                                |
| **Change History**                         | On by default. Records agent configuration writes for cloud agents and Cursor. Off skips snapshots; the MCP proxy still routes tools. See [MCP proxy](#mcp-proxy)                   |
| **Add to Assist**                          | On each agent. Off (the default) keeps the agent in AI Workspace only. On adds a Voice assistants pipeline for it. Off again removes that pipeline                                 |
| **Add Speech-to-text**                     | On OpenAI, OpenRouter, and OpenAI-compatible agents. On by default. Creates a Speech-to-text engine from this agent's key and assigns it to every AI Workspace Assist pipeline. Off removes that engine |
| **Speech-to-text model**                   | Shown with Speech-to-text. Empty uses the provider default (`gpt-4o-mini-transcribe` on OpenAI, Whisper on OpenRouter / compatible). You can pick another or type an id                 |
| **Add Text-to-speech**                     | On OpenAI, OpenRouter, and OpenAI-compatible agents. On by default. Creates a Text-to-speech engine from this agent's key (`gpt-4o-mini-tts`, voice Coral) and assigns it to Assist. Off removes that engine |
| **Text-to-speech model / Voice / Speed**   | Shown with Text-to-speech. Empty uses `gpt-4o-mini-tts` and Coral at 1×. Speed is 1×–4× (OpenAI). Submit writes this voice onto Assist pipelines AI Workspace created. Same voices speak German, French, and other languages — they follow the reply |




## Why the agent checks the house first

A model that is not told otherwise answers from what it guesses. For a house that means invented automations, wrong counts, or "the light is off" while it is on, said with confidence. Asking for a tool call in the prompt is not enough: in testing, GPT-4.1 listed automations that do not exist. With **Always check the house first**, the model must call a tool before it answers, so lists, counts, and states come from Home Assistant. After that first call it decides freely.

It is on by default because a wrong answer about the house costs more than one tool call. Greetings, thanks, and messages with images or files are never forced, and Cursor agents are not affected. Turn it off for an agent you mostly use for general questions, or for a model that already checks reliably on its own.

## Why use the config catalog

MCP tools answer "what is on?" well, but not "what is wired to what?". To find every automation that switches the kitchen light, the model would load the automations one by one, which takes many tool calls and tokens. The **Config catalog** keeps a local index of entities, areas, automations, and dashboards, with each automation's triggers, what it acts on, and what it depends on. One `search_catalog` call answers "what uses `light.kitchen`?" or "what starts the balcony irrigation?".

- It updates when entities, areas, or automations change, and every 15 minutes.
- It holds no live state, history, or traces. Lists, counts, and on/off still come from MCP.
- Only admins get it.
- It adds one tool and a few lines of prompt to every message, so it is off by default. Turn it on if you often ask how automations are connected.



## MCP proxy

Cursor does not call MCP from Home Assistant. HTTP MCP (HA-MCP and others) is rewritten to the **MCP proxy** in the Cursor Runtime (`/api/mcp-proxy/…`). Cloud API agents do not use that route; they call MCP inside the integration. The same three jobs still apply to both:

1. **Routing** — Cursor reaches HA-MCP through the Runtime instead of the upstream URL. That is also how the Runtime can attach a chat session to each tool call.
2. **Change History** — before and after each `tools/call`, the proxy (Cursor) or `on_tool` (cloud) snapshots config and commits a row when something actually changed. **Change History** on the integration (default on) turns this off without removing routing.
3. **Result sizing** — large MCP JSON is shortened **before the model reads it**, with the same code on both paths. Entities are grouped by area as ids only, and the model can ask again for one area or one entity. A shorter list keeps each entity's state and drops bulky attributes. One entity, one room, or one automation still arrives whole. The model always receives valid JSON; nothing is cut off in the middle of an object.

**Shorten large MCP tool results** and **Change History** are on by default. Turn either off on the AI Workspace integration; both flags are passed to the Runtime on each Cursor chat. Home Assistant logs result sizing as `mcp proxy last tool result` (`unchanged` / `area-map` / `truncated`).

## Privacy and security

- **What leaves the house:** your messages, attachments, the system prompt, the page you are on, and every MCP tool result go to the AI provider you picked (or to Cursor through the runtime). Only Ollama or another local server keeps everything at home.
- **What stays local:** chat history is stored in `config/ai_workspace/ai-workspace.sqlite`. Change History keeps a log of the last 30 recorded agent configuration writes there. Undo for HA-MCP writes belongs to HA-MCP's own edit backups; **Ask to restore** in that log asks the current chat to list and restore them. API keys live in Home Assistant's config entries, like any other integration.
- **Who can use it:** only admins by default. The sidebar panel is always admin-only.
- **Allow normal users:** when this is on, people who are not admins get the floating chat. They only get the built-in **Home Assistant MCP Server**, using their own login, and never the admin's MCP connections or the config catalog. What they can see and do is then whatever Home Assistant exposes to them through Assist. **Only turn this on if you trust everyone with a login to chat with an AI that can act on the house.**
- **Voice satellites:** Assist from a satellite has no signed-in person, so it uses the tools the admin configured. The built-in MCP Server needs a login, so set a long-lived access token in that connection's **MCP token** when satellites should reach it. HA-MCP and Vibecode bring their own credentials.
- **Runtime:** keep port 8090 and your MCP servers off the internet. The runtime only accepts HTTP MCP servers from the integration and rejects every request without the runtime token, unless it listens on loopback.



## Cost

Cloud AI and Ollama agents send the system prompt and the tool list of every enabled MCP connection with each message. HA-MCP offers about 80 tools. Even with their descriptions shortened, that is several thousand tokens before you type anything. Each tool call adds its result and one more request, which sends the prompt and the tool list again. A greeting or thanks is sent without tools.

- **History:** the last 12 messages of the chat are sent again, each cut to 2,000 characters. Tool results from earlier messages are not.
- **[Always check the house first](#why-the-agent-checks-the-house-first):** a question that needs no house data, like a poem or a YAML explanation, still costs one tool call and one more request.
- **To spend less:** pick a small model for everyday questions, use **Low token** for chat without tools, disable the device of an MCP connection you do not need, and start a new chat when the topic changes.



## Troubleshooting

- **"Runtime token is missing or wrong."** The token on the Cursor agent and on the runtime differ. On Docker, copy `RUNTIME_TOKEN` into **Cursor agent → Runtime token**. On the app, the integration pairs by itself as long as its own Runtime token field was never filled in; if you typed one there, use the same value as the app's **Runtime token** option.
- **"Set RUNTIME_TOKEN on the runtime and the same token on AI Workspace."** The runtime has no token and listens beyond loopback. Without `HOST: "127.0.0.1"` it listens on all addresses. Either set `HOST: "127.0.0.1"` (host network), or set `RUNTIME_TOKEN` and put the same value in **Cursor agent → Runtime token**.
- **The agent invents answers instead of checking.** Check that **Always check the house first** is on for that agent. It makes the model call a tool first for every message that is not a greeting or thanks. Some providers and small local models do not honor a forced tool call. Use a model with reliable tool calling (for example GPT-4.1 mini, Claude Sonnet, Gemini 2.5, or Composer) and check that the MCP connection's device is enabled.
- **Built-in MCP Server tools are missing in Assist.** That server needs a login, and a voice satellite has none. Set a long-lived token on the connection (see [Privacy and security](#privacy-and-security)).
- **OpenAI rejects `function.name`.** Names over 64 characters are shortened with a stable hash. Two MCP connections that share a tool get a short prefix. Disable a connection's device to drop its tools. Turning off **All LLM APIs** is not the same as disabling that device; the built-in `/api/mcp` tools are omitted only while **MCP Server** is unloaded.
- **OpenAI TTS 429 `credit_balance_exhausted`.** The OpenAI account is out of credit. That is separate from MCP tool names.
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
3. Runtime: remove the **app**, or run `docker compose down -v` in the runtime compose folder. `-v` also deletes the `ai-workspace-data` volume with the Cursor state; leave it out to keep that. Use `docker rm -f cursor-sdk` if an old container remains.
4. Optional: delete `config/ai_workspace/` to remove the chat history.



## Community

- **[GitHub Discussions](https://github.com/domdus/ha-ai-workspace/discussions):** ask questions and share ideas
- **[Issue Tracker](https://github.com/domdus/ha-ai-workspace/issues):** report bugs, request features, or suggest tool behavior improvements

