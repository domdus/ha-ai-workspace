# Changelog

## 1.3.4

- Cursor and cloud agents share the same skill reminder: if a listed write tool has `BestPracticeKey`, load that MCP’s skill guide (`ha_get_skill_guide` on HA-MCP) and pass the key. If the field or tool is missing, skip it and do not ask the user. Cursor already had the tool; it was missing the extra sentence cloud chats get because their tool descriptions are shortened.
- Cursor follow-ups no longer re-send that standing workspace prompt (skill reminder, Lovelace rules, link instructions). A new or cold agent still gets the full prompt with the transcript handoff. Home Assistant still includes the text on the wire so an older runtime keeps today’s behavior.
- README: a ChatGPT or Claude.ai plan is not an API key. Cloud agents need that provider's API credits. Contributing lists the fork, branch, and pull request steps.

## 1.3.3

- Gemini text-to-speech has the same **Speed** control as OpenAI. The Gemini API has no numeric rate, so 1×–4× is sent as `speech_metadata.style` (pace).
- Floating chat: the header icon and title line up with the conversation title.
- Change History **Rollback** copies the Lovelace config before the write. Home Assistant mutates the live dashboard dict on save, so a stored snapshot could silently become the after-image and look like a no-op. Failed rollbacks now show the server error instead of only a button tooltip.
- Change History restores the same Lovelace board HA-MCP edits. A storage dashboard with url_path `lovelace` (sidebar Overview) was previously written to the hidden default board, so Rollback could say Restored while the view you were on did not change.
- Cursor banner: if Home Assistant starts before the Docker runtime, the “start the runtime” notice clears once the runtime answers, instead of sticking while chat already works.

## 1.3.2

- Gemini text-to-speech and speech-to-text send the AI Studio key as `x-goog-api-key` only. A Bearer header on `generateContent` made Google return HTTP 401.
- Change History **Rollback** uses our snapshot without HA-MCP. When HA-MCP is connected, **Ask to restore** stays on the same row so edit backups still work. A snapshot that already matches the live dashboard says so instead of looking like nothing happened.
- Floating chat: left-align the header icon and title with the messages, and line up **Open full workspace** with the same gutter.
- HACS installs from the GitHub tag archive again. The extra release zip is gone.

## 1.3.1

- Change History **Rollback** restores the snapshot taken before the write. HA-MCP backups stay available; this does not depend on `ha_manage_backup`.
- HACS 1.3.0 installed the integration one folder too deep (`custom_components/ai_workspace/ai_workspace/`), so Home Assistant could not find it. The release zip now has `manifest.json` at its root.

## 1.3.0

First stable 1.3. Includes the 1.3.0b1–b12 betas (usage and cost, Change History, Cursor runtime, Gemini speech, and the security work in b9).

- Change History records Lovelace card add, duplicate, move, and delete again. Named writes are kept even when Home Assistant is slow to fire `lovelace_updated`, dashboard snapshots reload from storage, and Cursor Runtime callbacks reach Core: `127.0.0.1` on host-network Docker, `homeassistant` on a bridge or HA OS add-on. A turn-level safety net still writes a row if prepare/commit never lands.
- The floating chat drawer uses Home Assistant’s app bar in the standard template too
- Prompt cache stays on by default and is no longer on Configure; `prompt_cache: false` in YAML still turns it off
- Agent forms include a **Get an API key** link to that provider’s console
- HTTP 503 from a model provider is retried a few times, like 429
- HACS downloads a release zip (`ai_workspace.zip`) and the repo has brand icons for the store listing
- Gemini agents can add Home Assistant speech-to-text and text-to-speech engines (native generateContent; TTS default voice Kore). Existing Gemini agents stay off until you turn each on
- The speak control stays hidden until an assistant reply exists, instead of appearing while the agent is still working
- A cloud turn that calls tools and then returns no text now says so, instead of leaving an empty assistant bubble
- Claude Usage totals now count cache read and write tokens (Anthropic reports those separately). Empty cloud turns still record the cost of the tools they ran
- The Usage page top cards are workspace totals. Filter by an existing chat instead of a “This chat” card; deleted chats stay in the unfiltered totals

## 1.3.0b12

- **Always check the house first** is a shared AI Workspace setting under Cost and tokens, not a per-agent toggle. Cursor is unchanged. If every cloud agent already had it off, that stays off.
- Deleting a chat (or pruning old chats) keeps its usage and cost on the Usage page; those turns were already billed.

## 1.3.0b11

- A provider that does not answer in time now says so (“The provider did not answer in time”) instead of “The agent failed.”
- An AI Workspace entry from an old test build gets a clear log message to delete and re-add it, instead of Home Assistant’s generic migration error
- Troubleshooting explains that `config/ai_workspace/` (chats, Change History, usage, workspace) stays after removing the integration

## 1.3.0b10

- The chat keeps showing **Working…** while the agent runs tools or is still busy after its first words, and clears it when the reply ends

## 1.3.0b9

- Setup and Configure load again on Home Assistant 2025.12 to 2026.8. The voice row needed a library that only ships from 2026.9
- When no MCP server is found, the first setup form says to add Home Assistant’s **Model Context Protocol Server** integration (or HA-MCP) instead of asking to leave the address empty
- The config catalog rebuilds once after a burst of registry changes (startup, bulk renames) instead of once per change
- Change History looks up chat titles off Home Assistant’s event loop

Security hardening:

- Cursor agents in chats from normal users and voice satellites only get MCP tools (no shell, files, or web). Signed-in admins keep the full toolset. The restriction is sent again on every resume, and an SDK that cannot apply it refuses to start the agent instead of falling back to all tools. The title helper no longer retries with tools
- Chat replies, user messages, and error texts no longer load off-site images, video, or audio. Reference-style images, `srcset`, `poster`, quoted `>` in attributes, and single-quoted titles are covered, and rendered replies are checked again in the page
- Home Assistant accepts the runtime’s callbacks (Change History, MCP notes) without a runtime token only from the same machine, and keeps at most 100 pending Change History entries
- Runtime without a token (loopback only) answers only `127.0.0.1` / `localhost` host names, which blocks DNS rebinding. `/docs` and `/openapi.json` are off, the MCP proxy secret is hidden in the access log, and chat attachments have size limits
- Usage page: normal users see only their own usage. The config catalog MCP endpoint is admin-only. Broken JSON gets a 400 instead of a server error
- Assist users that no longer exist are not treated as admins
- `GIT_TOKEN` is passed to `git clone` as an HTTP header in the environment, not in the clone URL, so it does not show up in the process list
- Deep links to automations, scripts, scenes, entities, and devices escape their ids
- Stopping or sending while the browser still asks for the microphone no longer leaves the mic recording

## 1.3.0b8

- Usage page filters use Home Assistant’s own dropdowns and date range picker (with a plain fallback), and the main buttons use the accent style
- Cost estimates use a filtered copy of [LiteLLM](https://github.com/BerriAI/litellm)’s price list (310 models). A weekly workflow opens a pull request when prices change. Several older hand-kept prices were off (for example DeepSeek output and `gpt-6-astra`)
- `gpt-4o-mini-tts` speech is priced by audio length (about $0.015 a minute) instead of text input only, which was about 25× too low
- OpenRouter Claude names such as `anthropic/claude-sonnet-4.5` find Anthropic’s price
- AI Workspace settings are grouped into **Chat**, **Cost and tokens**, and **Home Assistant answers** (collapsed), with plainer help texts
- Missing **Track usage and costs** labels in the settings form and the Usage page texts are now translated in every language
- Docker extras for the Cursor runtime (bridge network, files on disk, git) moved to `docs/cursor-runtime.md`; README shows the Usage page

## 1.3.0b7

- Cursor runtime (Docker): optional `GIT_REPO` clones a project into the agent’s workspace on first start (SSH key or token stays on the container). `AGENTS.md` and the Home Assistant rule are only seeded when missing
- Change History records Lovelace dashboard edits, including new dashboards
- Queued follow-up message has its cancel button again while the agent is busy
- **Add Home Assistant usage sensors** is a separate option (off by default). Track usage still records to the Usage page; HA entities are created only if you opt in, and turning it off removes them
- Optional `configuration.yaml` for AI Workspace (UI still works). Keys you omit keep the saved value; `connections:` / `agents:` replace those rows. Example: `docs/configuration.example.yaml`
- `/ai-workspace/usage` scrolls again, and the page filters by agent, model, and date range
- Collapsed sidebar stacks History and Usage with the other rail icons
- README is the intro, features, and install; settings, cost, privacy, MCP, and troubleshooting live under `docs/`

## 1.3.0b6

- GPT-5 / o-series no longer get the Medium/Extreme reply cap (`max_completion_tokens` 1024/256), which spent the budget on hidden reasoning and returned no text
- Cloud “Working” status uses the same translation as Cursor (German **Arbeitet**, and the other UI languages)
- Streaming paints every frame again; incomplete markdown tables are still held

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
