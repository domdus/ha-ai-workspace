# Changelog

## 1.3.0b5

- OpenAI GPT-5 / o-series sends `max_completion_tokens` (retries the other field if a provider 400s)
- Chat history **…** menu sits inside the selected/hover row

## 1.3.0b4

- Chat header usage line no longer prefixes “This chat:”
- Workspace sensors sit under a **Usage** subentry as device **AI Workspace** (no leftover “devices not belonging to a subentry” group)
- **Reduce token usage** is back on the shared AI Workspace form, not on each agent
- **Prompt cache** is a shared AI Workspace setting (applied when the model supports it; Cursor and Ollama ignore it), not per agent
- **Usage** is a full page at `/ai-workspace/usage`: 30-day cost/token charts, and model comparison (tokens per turn, cost per turn, highest spend, most used, cheapest turn)
- **Show cost in chat header** is a shared option (on by default); off hides the header line without stopping tracking or the Usage page

## 1.3.0b3

- **Token usage** on Cloud / Ollama / Azure agents is a dropdown: Off, Light, Medium, Extreme (old “chat-only” / `low_token: true` is Extreme)
- Light keeps tools and history and always checks the house; Medium keeps tools with a short prompt; Extreme is chat-only and can save about 80–95% of tokens on a house-check turn
- **Prompt cache** (on by default, not Cursor): Claude `cache_control` and an OpenAI `prompt_cache_key` so the repeated tool list is billed cheaper on later rounds; turn off to compare. A provider that rejects it is retried without
- Agent usage sensors sit on the agent subentry again (with conversation / STT / TTS), so Devices & services nests them under Claude, Cursor, OpenAI, … instead of “devices not belonging to a subentry”. Workspace totals stay on the **AI Workspace usage** device
- Android: prompt bar no longer rubber-bands above the keyboard once the chat has a few messages (it was resizing the whole panel every visual-viewport tick)
- Streaming follow-scroll is smoother (paints ~50ms / on newlines, slower catch-up). Tables wait for a complete header before showing, then keep fixed columns so they do not grow and shrink mid-row

## 1.3.0b2

- Track OpenAI-style **text-to-speech** when it is used (Assist, overlay speaker, auto-read): character list prices for `gpt-4o-mini-tts`, `tts-1`, and `tts-1-hd`
- Usage page shows **Speech today**; Home Assistant gets Speech cost today/total on the workspace and each agent

## 1.3.0b1

- Optional **Track usage and costs** (on by default): records tokens and USD after each Cursor or cloud turn
- Usage page in the chat (sidebar button next to Change History) lists today / month / all-time and each agent
- Each chat shows a usage line; Cursor uses billed cents from the SDK when available, cloud agents use list prices (cache and reasoning included when the provider sends them)
- Home Assistant sensors on **AI Workspace usage** plus each agent: cost, tokens, turns, last model — for your own Lovelace dashboards
- Event `ai_workspace_usage` fires after every recorded turn

## 1.2.1

- HA Components: agent picker sits in the composer column so it lines up with the prompt on desktop new chat
- HA Components mobile: composer gutter is no longer doubled (outer bar + inner box padding)
- HA Components: send/attach/mic work on the visible composer (delegated clicks; fallback duplicate buttons no longer steal listeners)
- HA Components: single-line `ha-input` prompt again (Assist-style end slot); textarea fallback only until the widget defines

## 1.2.0

- **Use HA Components** composer matches Assist: `ha-input` with attach/mic/send in the end slot, not a custom textarea row
- Chat HTML paints immediately; HA widget chunks load in the background instead of a blank panel for several seconds
- HA Components composer and agent picker keep an opaque page background so chat text does not show through on scroll
- Switching **Use HA Components** applies without reopening the panel (theme remount)
- Wide markdown/tables stay inside bubbles; agent picker and composer align with the message column on mobile
- New chat shows the welcome headline again; sticky prompt, picker, and empty-state use the same max width as Standard
- Overlay drawer and sidebar panel mount chat inside `ha-top-app-bar-fixed` so the body is not 0px tall; Change History links no longer pick up message-row icon styles
- HA Components shows a Standard-style textarea until `ha-input` defines; session titles stay visible on plain session rows
- Agents listing automations/scripts should use a few domain/registry MCP calls, not one config get per row

## 1.1.4

- Overlay drawer stacks above the Home Assistant app header; compact chat sidebar z-index fixed
- Lovelace/dashboard MCP-only rules in the system prompt (no workspace filesystem for config edits)
- **Natural speech for text to speech** (default on) strips Markdown, links, and arrows before TTS
- Android companion: typing while scrolled up in chat no longer forces scroll to bottom
- Change History groups config writes from one agent turn into one **logical commit**; **Ask to restore** lists every target in the batch for HA-MCP edit backups
- Home Assistant keeps the chat transcript; the Cursor Runtime no longer duplicates turns in SQLite when `history_in_ha` is set, and warm resumes skip re-applying an empty handoff when the agent is still alive
- Cursor handoff notes are larger and clearer so reopened chats do not look blank to the agent; HA logs when a handoff would be empty despite stored turns
- The chat UI waits until the session is loaded before sending, and a runtime 404 resyncs the agent instead of silently starting a new chat
- Overlay and sidebar panel scroll correctly on open and when navigating to `/ai-workspace`; user bubbles match the selected chat row styling
- **Use HA Components** (off by default): chat, overlay, and panel can use native Home Assistant widgets and Assist-style messages so themes apply more cleanly; Standard template unchanged
- HA Components composer uses `ha-card`, `ha-textarea`, and Assist-style send control; thin scrollbars on chat and session lists
- Speak/pause control stays available during the first auto-read reply; pause stops in-flight TTS
- Thin scrollbars apply on desktop only; Standard mobile prompt avoids a visible in-field scrollbar until text hits the height cap

## 1.1.3

- Change History is a log of recorded agent writes; rollback is off because snapshots sit beside MCP tools, not on the write path like HA-MCP edit backups
- When HA-MCP is connected, Change History shows **Ask to restore**: it prompts the current chat to list HA-MCP edit backups and restore the match, instead of listing backup files ourselves
- Change History snapshots Lovelace from `lovelace_updated` and entity registry updates, and loads dashboards with `async_load` instead of cached `_data`
- Automation, script, and scene edits snapshot the live config (not only `.yaml`), and `automation_reloaded` / `script_reloaded` / `scene_reloaded` record the change when the file is still flushing
- MCP tool names sent to OpenAI are unique and at most 64 characters, with a stable hash when a name is shortened
- Disable an MCP connection's device to drop its tools; a failed list_tools on one row does not block the others
- Built-in `/api/mcp` tools are omitted when the Home Assistant MCP Server integration is not loaded
- Change History treats HA-MCP's empty/`null` dashboard `url_path` as the default board, and watches `python_transform` writes so card moves are recorded
- Cursor Runtime records Change History through the MCP proxy: commit waits for `lovelace_updated`, runtime defaults `hass_url` on HA OS, and prepare/commit failures log clearly
- **MCP proxy** is the Runtime name for routing Cursor MCP, Change History, and large-result sizing; `/api/mcp-fit/` still works as an alias
- **Shorten large MCP tool results** and **Change History** are shared options (default on) for cloud agents and Cursor
- Overlay Text-to-speech keeps the engine you pick (including Google Translate or Off); it no longer jumps to OpenAI
- Existing Assist pipelines keep their STT/TTS; new pipelines still get our engines on first create. A removed engine becomes none instead of stealing another pipeline's voice
- OpenAI TTS 429 `credit_balance_exhausted` is a provider quota issue, not this naming fix
- Cursor Runtime URL and token live on the Cursor agent form; the URL is filled only when `/api/health` answers, not from a compose hostname guess
- Change History icon under the reply stays when you reopen the chat if that chat has any recorded writes
- MCP proxy no longer forwards Cursor's Authorization to upstream MCP, so built-in `/api/mcp` keeps the Home Assistant Bearer and does not spam HTTP ban warnings

## 1.1.0

- A failed Cursor run is dropped, so the next message starts a fresh agent
- Greetings such as "Hey Cursor?" are sent without tools
- Configuration writes are snapshotted before they run, so Change History can roll them back

## 1.0.0

First public release.

- Cursor SDK runtime for AI Workspace on Home Assistant OS (app) and Home Assistant Container (Docker)
- Prebuilt image for amd64 and arm64
- Shared runtime token. On Home Assistant OS the integration creates it and writes it to the app. Docker sets `RUNTIME_TOKEN`. A runtime that listens beyond loopback refuses chats without a token.
- MCP servers sent by the integration must be HTTP. stdio servers and environment overrides from requests are refused.
- Users who are not admins only get the built-in Home Assistant MCP Server with their own login
- Agents are kept open between messages, so follow-ups keep their context; a lost agent resumes from the saved chat
- Large MCP results are shortened to valid JSON before the model reads them
- Requires Home Assistant 2025.12 or newer
