# Changelog

## 1.1.4

- Overlay drawer stacks above the Home Assistant app header; compact chat sidebar z-index fixed
- Lovelace/dashboard MCP-only rules in the system prompt (no workspace filesystem for config edits)
- **Natural speech for text to speech** (default on) strips Markdown, links, and arrows before TTS
- Android companion: typing while scrolled up in chat no longer forces scroll to bottom
- Home Assistant keeps the chat transcript; the Cursor Runtime no longer duplicates turns in SQLite when `history_in_ha` is set, and warm resumes skip re-applying an empty handoff when the agent is still alive
- Cursor handoff notes are larger and clearer so reopened chats do not look blank to the agent; HA logs when a handoff would be empty despite stored turns
- The chat UI waits until the session is loaded before sending, and a runtime 404 resyncs the agent instead of silently starting a new chat
- Overlay and sidebar panel scroll correctly on open and when navigating to `/ai-workspace`; user bubbles match the selected chat row styling

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
- **Shorten large MCP tool results** and **Change History** are shared options (default on) for cloud agents and Cursor; sizing is logged as `mcp proxy last tool result`, not shown in the chat header
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
