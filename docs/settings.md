# Settings

**Settings → Devices & services → AI Workspace → Configure** for shared chat options. Add or edit **connections** and **agents** with the buttons on the AI Workspace integration page.

## How it is organized

AI Workspace is one integration with three kinds of rows:

- **Connection:** one row per MCP server. The first one is created during setup; **Add connection** adds more.
- **Agent:** one row per Cursor, OpenAI, Claude, Gemini, OpenRouter, Ollama, Azure, or other provider. **Add agent** adds more.
- **Usage:** cost and token sensors on a device named **AI Workspace**. Created only if [Add Home Assistant usage sensors](cost.md#home-assistant-sensors) is on.

Each row has its own device. Disable a device to switch off one MCP connection or one agent without deleting it.

If two connections share a tool name, AI Workspace adds a short prefix so the model can tell them apart. OpenAI also limits tool names to 64 characters; longer names are shortened automatically.

Turning off **All LLM APIs** or unloading **MCP Server** in Home Assistant hides the built-in MCP tools even if the connection row is still there. That is not the same as disabling the AI Workspace device. See [MCP and Change History](mcp.md).

## System prompt

This is the standing instruction for the assistant. Use it for how you name rooms, which automations to leave alone, how short answers should be, or any other house rule.

What you write here replaces the built-in prompt. Leave the field empty to keep the built-in text, which covers helping with this Home Assistant and asking before it changes the house. The same text is used for cloud APIs and the Cursor runtime.

Tappable links to automations, entities, helpers, and devices are always added. You do not need to mention those in the prompt.

## AI Workspace settings

**Configure** on the AI Workspace entry. The form has the same groups as below. These settings apply to every agent.

### Chat

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Show AI Workspace in the sidebar** | Sidebar item. `/ai-workspace` still works when this is off. | Keep the sidebar tidy; admins can still open the full page. |
| **Show floating AI button** | Bottom-right robot icon on other Home Assistant pages. It slides up when another corner button is already there. | Open the same chat without leaving the page you are on. |
| **Show dictate button** | Microphone in the message box. On by default. | Hide it if you never dictate. |
| **Allow normal users** | Off by default. Non-admins get the floating chat only, with the same Home Assistant access as their own login. | [Privacy](privacy.md). Only turn this on if you trust everyone with a login. |
| **Use HA Components** | Off by default. Builds the chat from Home Assistant’s own UI parts. | Can look better with some themes. |
| **Cross chat** | Off by default. A question can use a short excerpt from another chat whose title shares words with it. That other chat is not changed. | Helps when you already discussed a room or automation in a different chat. |
| **Chats to keep** | Newest unpinned chats per person (default 30). Pinned chats are always kept. | Stops the history list growing forever. |

### Voice

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Speech to text** | Browser speech, or a Home Assistant engine such as Whisper. The microphone needs https:// or localhost. | Dictate instead of typing. Browsers block the microphone on a plain http:// address. |
| **Text to speech** | Piper, Google Translate, or a voice from an OpenAI-style agent. The speaker button works on http:// too. Off leaves replies as text. | Hear replies. OpenAI-style voices follow the language of the reply (German, French, and others). |
| **Speak replies automatically** | Off by default. When a voice is selected, each reply is read as it arrives. | Hands-free. Off still leaves the speaker button. |
| **Natural speech for text to speech** | On by default. Removes formatting such as lists, links, and symbols before reading. | Sounds like a person talking instead of reading out punctuation. |

### Cost and tokens

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Reduce token usage** | Off, Light, Medium, or Extreme for every Cloud, Ollama, and Azure agent. Not on Cursor. | [How much each message sends](cost.md#reduce-token-usage), and what you give up for a lower bill. |
| **Always check the house first** | On by default. Not on Cursor. With **Light** it always checks; **Medium** and **Extreme** ignore this toggle. | [Why this is on](#always-check-the-house-first). One extra tool round on questions that do not need the house. |
| **Track usage and costs** | On by default. Records tokens and estimated cost. Sidebar **Usage** opens `/ai-workspace/usage`. | [See what you spend](cost.md). Off stops new records; history stays. Deleting a chat does not remove its usage. |
| **Show cost in chat header** | On by default. Tokens and cost under the chat title. | Cost at a glance. Off hides only that line. |
| **Add Home Assistant usage sensors** | Off by default. Creates cost, token, and turn sensors. | [For your own dashboards and automations](cost.md#home-assistant-sensors). The Usage page does not need them. |

### Home Assistant answers

Collapsed by default. The defaults suit most homes.

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Config catalog** | Off by default. A local index of how automations, entities, and areas are connected. | [Why this is off by default](#config-catalog). |
| **Shorten long Home Assistant answers** | On by default. Very long lists are summarized before they go to the model. | [Saves tokens](mcp.md#shorten-long-home-assistant-answers) and keeps replies quick. |
| **Change History** | On by default. Records every configuration change the assistant made. | [See what changed](mcp.md#change-history). Automations, scripts, and scenes also get a YAML copy for [when Home Assistant will not start](mcp.md#if-home-assistant-will-not-start). |
| **Rollback for** | Days Rollback and Ask to restore stay available (default 7, 1–90). | After that the row stays in the log. Restoring an old snapshot can overwrite later work. |

### System prompt

Collapsed by default. See [System prompt](#system-prompt). Empty uses the built-in text.

## Connection settings

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Connection type / Server address / Access key** | Asked when you add AI Workspace, and again on **Add connection**. Leave the address empty to use the detected one. Built-in MCP Server: an empty key uses the login of the person chatting. HA-MCP: usually empty. Vibecode: agent key. | This is how the model reaches Home Assistant. See [MCP](mcp.md). |

## Agent settings

On each agent (**Add agent**, or the edit button on an agent row).

| Option | What it does | Why it matters |
| --- | --- | --- |
| **Copy key from** | Uses a key already stored by OpenRouter, OpenAI, Claude, Gemini, Ollama, or Azure in Home Assistant. That other integration stays as it is. | You do not paste the same key twice. |
| **API key** | Paste a key, or open **Get an API key** under the field for that provider’s console. Leave blank when editing to keep the saved key. | You do not have to hunt for the signup page. |
| **Effort** | Default, Fast, High, or High fast, when the model supports it. If it does not, the request still goes through. | High thinks longer: better on hard questions, but slower and more tokens. Fast is cheaper and quicker. |
| **Cursor runtime address / Runtime password** | Only on Cursor agents. Leave the address empty when the form shows **Runtime found**. | Pairs Home Assistant with the Cursor runtime. See [Runtime token](../README.md#runtime-token). |
| **Add to Assist** | On adds a Voice assistants pipeline for this agent. Off removes it again and keeps the agent in AI Workspace only. | Use the same model from Home Assistant’s Assist dialog. |
| **Add Speech-to-text / Text-to-speech** | OpenAI, OpenRouter, OpenAI-compatible, and Gemini. OpenAI-style is on by default. Gemini uses native generateContent (not Whisper / `/audio/*`) and stays off on agents you already added. Uses this agent’s key. Off removes that engine. | Listen and speak with the same key. Cursor, Claude, Azure, and Ollama have no speech API of their own. |

## Always check the house first

A model that is not told otherwise answers from what it guesses. For a house that means invented automations, wrong counts, or “the light is off” while it is on — said with confidence. Asking “use a tool” in the prompt is not enough on its own.

With **Always check the house first**, the model must call a Home Assistant tool before it answers, so lists, counts, and states come from your instance. After that first call it decides freely.

It is on by default because a wrong answer about the house costs more than one extra tool call. Greetings, thanks, and messages with images or files are never forced. Cursor agents are not affected.

Turn it off if you mostly ask general questions, or if your models already check the house on their own. **Medium** and **Extreme** token modes also skip this, because those modes are trying to spend less.

## Config catalog

MCP tools answer “what is on?” well, but not “what is wired to what?”. To find every automation that switches the kitchen light, the model would otherwise load automations one by one. That is many tool calls and tokens.

The **Config catalog** keeps a local index of entities, areas, automations, and dashboards: each automation’s triggers, what it acts on, and what it depends on. One lookup answers “what uses the kitchen light?” or “what starts the balcony irrigation?”.

- It updates when entities, areas, or automations change, and every 15 minutes.
- It holds no live state, history, or traces. Lists, counts, and on/off still come from MCP.
- Only admins get it.
- It adds one extra tool and a few lines of prompt to every message, so it is **off by default**. Turn it on if you often ask how automations are connected.

## YAML configuration

The integration is still configured in the UI. If you add an `ai_workspace:` block to `configuration.yaml`, those keys are applied on **Home Assistant start**.

- Keys you omit keep whatever is already saved (or the UI default on first import).
- If you include `connections:` or `agents:`, that list **replaces** the current rows of that kind. Leave those keys out to keep managing connections and agents in the UI.
- Put API keys in `secrets.yaml` and use `!secret`.
- YAML changes need a restart. The UI still works after that; YAML wins again on the next start.

Quote `low_token: "off"` (YAML `off` would be read as false). Full copy-paste example: [configuration.example.yaml](configuration.example.yaml).
