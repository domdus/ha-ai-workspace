# Changelog

## 1.5.1b1

- The runtime has no changes in this release. A 1.5.0 runtime keeps working without an update notice; the 1.5.1b1 image only carries the new version number.
- Change History: helpers and dashboards are rolled back through Home Assistant's own websocket commands, signed in as you, the same calls the helper and dashboard editors make. Home Assistant checks your permissions, validates the item, and stores it. Before, AI Workspace reached into Home Assistant's internal storage for these.
- Change History: the snapshot of a helper before a change is read the same way, with the chatting user's own login. Without one there is no snapshot, and the row offers Undo with agent.
- Change History: Rollback is for administrators only, for every kind of change. Before, a non-admin user could roll back helper, dashboard, and entity changes from their own chats.
- Startup: the check whether Home Assistant runs in a container no longer touches the disk from the event loop.

## 1.5.0

Everything from 1.5.0b1 to 1.5.0b34 (including 1.4.3b1 and 1.4.3b2). A minor release, because it adds features; nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0`) together with this release.** It carries the updated agent prompt, the Change History key, and the git push fix. The chat warns when the runtime is older than 1.5.0.

**Chat**
- Replies show what the agent is doing with a small moving glyph and one status line (thinking, reading the house, building, working). The agent may write one short sentence about what it is about to do before its tools; tool groups no longer stay in progress after a turn ends.
- Reloading the page while an agent answers picks the reply up again, with the tool steps and text so far.
- Queue: prompts sent while the agent answers stack as chips (up to ten) and go out in order. **Stop** stops everything, including the queue; queued prompts stay with their chat, and the first one goes back into an empty input field. A full queue or more than four attachments shows a notice.
- Read-aloud starts with the first paragraph and keeps reading as the reply arrives, in clips of at most 560 characters, so long replies are read to the end. Pausing keeps it paused; it stops when the floating chat closes, you leave AI Workspace, or you open Usage.
- The chat list and the open chat load together, the list comes from a per-user cache on later visits, and long chats paint their last messages first.
- When the connection drops before a reply arrives, the reply says so in your language.

**Agents**
- Cloud agents load tools on demand instead of sending all of HA-MCP's tools (about 38,000 tokens) with every request. Chat history follows a token budget, and each reply keeps a one-line note per tool call so the next turn does not look things up again.
- Agents know when things were said and the house's time zone, so history from "08:00" means local time, and they read a saved automation, script, scene, or dashboard again before describing it.
- Writing with HA-MCP's strict best-practice mode needs the guide only once; AI Workspace passes the key on to later writes.
- **Remembered notes** (Configure, off by default): the assistant reads your notes and adds to them when you say "remember …". It only stores what you said in the chat, each change is in Change History, and notes survive a restart.
- A simpler agent form: **Advanced** holds **Save tokens**; every agent with tools looks at Home Assistant first.
- Claude agents: **Keep the cache for an hour** under **Advanced** (off by default).
- Ollama: the form checks the address and the model name, and a model without tools or with a small context window answers chat only.
- Grok (xAI) agents can add a Text-to-speech engine with the agent's xAI key (the key needs Voice enabled). 26 voices, speed 1× to 1.5×. Off on Grok agents you already had, on for new ones.

**Change History**
- Rollback of automations, scripts, and scenes goes through Home Assistant's own config API. Each row has one way back: **Rollback** to the saved copy, or **Undo with agent** for things the agent created. New items are listed by name, for example "Created automation Water the balcony when dry".
- An open automation or script editor shows the agent's new version right away; unsaved edits stay.

**Usage**
- Each request of a turn is priced on its own, so long-request rates only apply where they should. Stopped or failed turns still count what already finished. Model prices refreshed from LiteLLM, plus Grok TTS at $4.20 per million characters.

**Runtime and security**
- The runtime's calls back into Home Assistant need a key Home Assistant issues for each Cursor chat turn.
- Cursor runtime with `GIT_REPO` can push as well as pull, and still starts when cloning fails.
- The chat warns when the runtime is older than the integration expects.

**README**
- New GIFs and screenshots: several real tasks in one chat, the floating chat on any page, Change History, Usage, and settings.

## 1.5.0b34

- The runtime has no changes in this release. A 1.5.0b29 runtime keeps working without an update notice; the 1.5.0b34 image only carries the new version number.
- Grok (xAI) agents can add a Text-to-speech engine. It uses the agent's xAI key with xAI's `/v1/tts` (the key needs Voice enabled; a Cursor key cannot do this). 26 voices, default Eve, speed 1× to 1.5×, no model to pick. The Home Assistant language maps to xAI's codes, anything else is sent as auto.
- Grok TTS is off on Grok agents you already added and on for new ones, like Gemini. Turn it on in the agent form.
- Usage: Grok TTS is priced at $4.20 per million characters (xAI's beta price).

## 1.5.0b33

- The runtime has no changes in this release. A 1.5.0b29 runtime keeps working without an update notice; the 1.5.0b33 image only carries the new version number.
- Chat: pausing the read-aloud keeps it paused. Since 1.5.0b31 a timer dropped a paused last clip a few seconds after it would have ended, so the speaker button could not resume it.
- Chat: a clip whose length the browser cannot read is no longer cut off after 45 seconds. The queue only moves on when a clip ends, never starts, or stops making progress while it plays.

## 1.5.0b32

- The runtime has no changes in this release. A 1.5.0b29 runtime keeps working without an update notice; the 1.5.0b32 image only carries the new version number.
- Chat: TTS measures clip size as a character count. 1.5.0b31 passed the spoken string, which made `"Hello" <= 560` fail and every clip collapse to one letter.

## 1.5.0b31

- The runtime has no changes in this release. A 1.5.0b29 runtime keeps working without an update notice; the 1.5.0b31 image only carries the new version number.
- Chat: TTS splits leftover text into clips of at most 560 characters, so a long reply keeps reading after the first paragraph instead of timing out as one request. OpenAI and Piper both get this.
- Chat: a failed clip is tried once; if playback never signals that it ended, the queue still continues. Piper speaks one clip at a time; AI voices may still prepare the next one.

## 1.5.0b30

- The runtime has no changes in this release. A 1.5.0b29 runtime keeps working without an update notice; the 1.5.0b30 image only carries the new version number.
- Change History: a new automation, script, or scene is listed as “Created automation Water the balcony when dry” instead of “Updated automation automation”. When the name cannot be found, it says “Changed an automation”.
- README: new chat and floating-button GIFs (turn on a light, ask why the vacuum skipped, build an automation, add a weather card to the view you are on) and new screenshots.

## 1.5.0b29

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b29`) together with this release.** It carries the updated agent prompt. The chat warns when the runtime is older than 1.5.0b29.
- Chat: the status sentence before tools is optional again. The agent may write one short sentence about what it is about to do, but a quick question can go straight to the tools. If it writes one, it is still a natural sentence, not a generic filler. Voice requests still skip it.

## 1.5.0b28

- The runtime has no changes in this release. A 1.5.0b26 runtime keeps working without an update notice; the 1.5.0b28 image only carries the new version number.
- Chat: **Stop** stops everything, including the queue. Before, Stop sent the next queued prompt right away. The first queued prompt goes back into the input field if that is empty, so it is not lost.
- Chat: queued prompts stay with their chat. Switching chats or starting a new chat no longer sends the remaining queued prompts in the other chat; the first one goes back into an empty input field.
- Chat: a full queue (10 prompts) or more than 4 attachments now shows a short notice instead of doing nothing.
- Sidebar: the cached chat list is kept per user, so on a shared device the next user no longer briefly sees the previous user's chat titles.

## 1.5.0b27

- The runtime has no changes in this release. A 1.5.0b26 runtime keeps working without an update notice; the 1.5.0b27 image only carries the new version number.
- Chat: TTS speaks the leftover answer after the last status paragraph and tools, instead of stopping there. Text after thinking or tools starts at once, not after 280 characters.
- Chat: a prompt that leaves the queue on its own does not cut off the reading that is already playing.

## 1.5.0b26

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b26`) together with this release.** It carries the updated agent prompt. The chat warns when the runtime is older than 1.5.0b26.
- Chat: the first status sentence before tools is a complete sentence in your language that names what the agent is about to do, not a generic filler. Mentions of Home Assistant are allowed. The old “one moment” / “do not say you are checking” rules are gone.

## 1.5.0b25

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b25 image only carries the new version number.
- Chat: several photos copy their bytes before the picker is cleared, and only as many files as still fit (up to four) are read.
- Chat: stopping, sending the next turn, or switching chats keeps the queued stack. Closing the panel drops it. If the composer is empty, the first queued prompt moves into the field.
- Chat: TTS still speaks the first paragraph at once. Later short paragraphs are bundled into the next clip. An empty speak queue stops the loop.
- Chat: in HA Components, queued prompts are `ha-input-chip` with Home Assistant fill.

## 1.5.0b24

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b24 image only carries the new version number.
- Chat: queued prompts stack as chips (up to ten) and send in order when the reply finishes.
- Chat: picking several photos at once copies the bytes immediately so the prompt does not go empty. Up to four attachments, including one after another.
- Chat: each queued chip has its own fill on the composer so it no longer matches the box.

## 1.5.0b23

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b23 image only carries the new version number.
- Chat: thinking and working use four turning dots (`: :`); reading the house uses a turning `+`.

## 1.5.0b22

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b22 image only carries the new version number.
- Chat: HA Components no longer draws status glyphs. Thinking and tools show the status text only. The standard UI still uses `+`, the dots, the lines, and `-`.
- Chat: the header gets `--ha-box-shadow-s` only after you scroll down, like the Home Assistant top bar.

## 1.5.0b21

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b21 image only carries the new version number.
- Chat: TTS stops when the floating chat is closed, when you leave AI Workspace, or when you open Usage. Minimizing the companion app still reads to the end.
- Chat: a queued prompt chip uses the same corner radius as the composer box.

## 1.5.0b20

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b20 image only carries the new version number.
- Chat: the thinking status glyph is a turning `+`, like the work glyph, instead of `-`. The dash stays the wait glyph.
- Configure: Cost and tokens starts collapsed, like House and Prompt.

## 1.5.0b19

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b19 image only carries the new version number.
- Chat: TTS speaks each finished paragraph as soon as it is there (a blank line, or a pause for tools or thinking), in order after the previous clip. A later short paragraph no longer waits until the whole reply is done.

## 1.5.0b18

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b18 image only carries the new version number.
- Chat: the thinking status glyph is a turning `-`, like the wait glyph, instead of `¤`.
- Chat: the sidebar list and the open chat load at the same time. A later visit shows the list from cache at once; the ⋯ menus are built only when opened; a long chat paints the last messages first.
- Chat: listing chats no longer scans every first message.
- Chat: a queued prompt chip has even spacing and a 36px close button in line with attach and send.
- Chat: when a queued prompt is sent, text already typed in the composer stays. A second send while something is queued no longer replaces the queue.

## 1.5.0b17

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b17 image only carries the new version number.
- Chat: the thinking status glyph is a `¤` that turns with the clock, like `+` and `-`, instead of a counterclockwise `÷`.

## 1.5.0b16

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b16 image only carries the new version number.
- Chat: the thinking status glyph is a `÷` that turns against the clock, instead of a coin-flip O. The dash (`-`) stays the wait glyph.

## 1.5.0b15

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b15 image only carries the new version number.
- Chat: tool groups such as “Calling 14 tools” no longer stay in progress with the shimmer after the turn has finished, also when the phone reconnected to a turn that was already running.
- Chat: text the agent writes after a thinking pause starts a new paragraph instead of being glued to the sentence before it (“…hängt.Die …”).

## 1.5.0b14

- The runtime has no changes in this release. A 1.5.0b13 runtime keeps working without an update notice; the 1.5.0b14 image only carries the new version number.
- Claude agents: new **Keep the cache for an hour** box under **Advanced** (off by default). The system prompt and tools stay cached for an hour instead of 5 minutes, so a message after a short break reads the cache (0.1× input) instead of writing it again. A cache write then costs 2× input instead of 1.25×. If Anthropic refuses it, the agent falls back to the 5-minute cache.
- Usage: each request of a turn is priced on its own. Models that charge more for long requests (for example Gemini Pro above 200,000 input tokens, GPT-5.4 above 272,000) get that rate only for the requests that are that long. Claude 1-hour cache writes are priced at their own rate.
- Usage: a turn you stop, or one that fails partway, now still counts the requests that already finished. Before, the whole turn was missing from the Usage page.
- Usage: Claude replies that stream no longer risk counting the input twice.
- Model prices refreshed from LiteLLM, now including long-request and 1-hour cache prices.

## 1.5.0b13

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b13`) together with this release.** It carries a shorter agent prompt. From now on the chat warns when the runtime is older than the last release that changed it, also within the same minor version (here: older than 1.5.0b13).
- Change History: each row has one way back. **Rollback** restores the saved copy from before the change. Rows without a copy, such as something the agent created, show **Undo with agent** instead (formerly Ask to restore), which asks the chat to undo it with its tools. If Rollback fails, the error offers Undo with agent.
- Remembered notes: to remove a note, the assistant names that one line. A short word no longer removes every line that contains it.
- Remembered notes: each change the assistant makes is in Change History and can be undone with Rollback.
- Remembered notes: the “remember this” and “stop doing that” cues match whole words only. Device commands such as “Lass das Licht an”, “Hör auf zu saugen”, or “Arrête la musique” no longer push the agent to write a note. “Remember to …” and “Vergiss nicht …” now count.
- Remembered notes: the assistant only stores what you said in the chat, never instructions from tool results, web pages, entity names, or files.
- Remembered notes: YAML `notes_text` sets the notes only when you change that value. Notes the assistant added survive a restart.
- Remembered notes: saving Configure without touching the notes field keeps a note the assistant wrote while the form was open. Two writes at the same moment no longer overwrite each other.
- Remembered notes: a Cursor agent that is already running is told the new notes on its next message.
- Prompts: the “do not say you are checking Home Assistant” rule is said once per prompt part instead of being repeated.

## 1.5.0b12

- Chat: the write status glyph (`=`) no longer spins with the generic SVG rotation; only the lines move top to bottom for one second (fix for b11).

## 1.5.0b11

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b11`) together with this release.** It carries the updated agent prompt (neutral status line before tools).
- Chat: before the first tool call, the agent may write one short neutral status line in your language (for example “one moment”), without naming Home Assistant, weather, or tools. Still at most one line per turn; nothing between later tool calls. No “looking at Home Assistant” announcements.
- Chat: the write status glyph (`=`) runs top to bottom for one second again (no sideways phase). Reduced motion still shows a static glyph.
- Chat: more space between answer text and the status line when both are visible (similar to the gap above tool summaries).

## 1.5.0b10

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b10`) together with this release.** It only carries the new version number. The chat banner still warns only on a minor mismatch (for example 1.4 vs 1.5).
- Chat: the write status glyph (`=`) runs for 1 second top to bottom, then 1 second left to right, then repeats. Reduced motion still shows a static glyph.

## 1.5.0b9

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.0b9`) together with this release.** The chat banner now warns only when the runtime is at least one minor version behind (for example 1.4 vs 1.5), not for a beta on the same minor such as 1.5.0b8 vs 1.5.0b9. The warning is translated in the 15 chat languages.
- Configure: optional **Remembered notes** (switch off by default, plus a text field). The assistant does not write in the system prompt. When the switch is on, it reads the English bullets and can add to them if you say “remember this” (any chat language) or complain about a habit. When it is off, chat neither reads nor writes them. Maximum 2000 characters; a new line that does not fit is refused. YAML `notes: false` is the same switch.
- Chat: agents no longer announce that they are looking at Home Assistant. A status sentence is only for real work (a change or a write). House facts still come from tools.

## 1.5.0b8

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Chat: while tools run, the status glyph still shows read, write, or work, but the status text no longer jumps between Reading, Building, and Working on every tool step. Agent status sentences and the Working or Thinking fallback stay as they are.
- Chat: each tool chip shows only the tool name again. Busy and done stay visible through shimmer and styling, not through Calling or Finished text on the chip.

## 1.5.0b7

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Chat: reloading the page while an agent is still answering picks the reply up again. The tool steps and text so far appear at once, and the rest follows live with its status, instead of a "Thinking" bubble until the whole answer is done. Home Assistant keeps the events of a running reply in memory until it ends, and the reloaded page follows them through a new endpoint (`/api/ai_workspace/sessions/{id}/live`). If that is not possible, the chat checks every 2 seconds as before, now for up to an hour instead of 8 minutes.
- Chat: while a tool runs, its label also replaces "Thinking", so the glyph and the label always match.

## 1.5.0b6

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Chat: the status line under a reply has a small moving glyph in front of it: + while the agent works, a turning O while it thinks, four turning dots with "Reading" while a tool reads the house, stacking lines with "Building" while a tool changes it, and a turning dash while it waits. A tool's glyph stays at least 0.7 seconds, so quick tool calls do not flicker. With reduced motion turned on, the glyph stands still.
- Chat: the status no longer disappears between steps. Once the reply had any text, the status stayed empty while the agent went back to its tools. Now "Working" comes back as soon as a tool starts or finishes, and 1.2 seconds after the text pauses.
- Chat: status labels always start with a capital letter, also the ones that come from Cursor.

## 1.5.0b5

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Agents know when things were said. Each earlier message in a chat now carries the local date and time it was sent, and the new message carries the current time. An agent no longer treats "it is raining" from five days ago as the weather now, and no longer calls a change since then its own mistake. Summaries of left-out turns keep the day.
- Agents know the house's time zone. Home Assistant's history tools read a time without a UTC offset as UTC, so "history from 08:00" started at 09:00 in Central Europe and missed what happened in between. The prompt now names the time zone and offset, and cloud agents' tool calls get the offset added when the agent leaves it out.
- Before an agent says what a saved automation, script, scene, or dashboard contains, it reads it again instead of relying on what the chat said earlier.
- Cursor agents get the time zone rules when the runtime starts a new Cursor agent for a chat.

## 1.5.0b4

- **Update the runtime (App or Docker image) together with this release.** The fix below is in the runtime.
- Cursor runtime with `GIT_REPO`: the agent can now push, not only pull. The runtime sets up `GIT_TOKEN` (or `GIT_SSH_KEY`) for push on every start, also for a repo cloned before this update. The token is not written into the repo's git settings. A fine-grained GitHub token needs Contents: Read and write, and the Cursor agent needs Allow internet to run git.
- Cursor runtime: if cloning `GIT_REPO` fails, the runtime logs the error and still starts, instead of stopping.

## 1.5.0b3

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number.
- Ollama agent form: under the address, a note says whether Ollama answers there, with its version and how many models are installed, like the "Runtime found" note on the Cursor form.
- The notes AI Workspace writes itself now appear in all 15 languages: the Ollama and Cursor address notes on the agent form, and the chat-only note in a reply. Before, they were English, or English and German.

## 1.5.0b2

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Agents: a simpler form. **Reduce token usage** and **Look at Home Assistant first** are gone; a folded **Advanced** section holds one box, **Save tokens** (what Medium was). Existing agents keep their behavior: Light now counts as Off, because on-demand tools and the history budget made Off cheaper than Light used to be. Medium shows as Save tokens. Extreme agents stay chat only while Save tokens stays on.
- Agents: every agent with tools now looks at Home Assistant first on a question about your home. That choice was cleared once on update, so agents where it was off have it on again. `check_house: false` in YAML still turns it off for one agent.
- Ollama: AI Workspace asks Ollama whether the model can use tools and how large its context window is. A model without tool support, or one Ollama runs with a window under 8,192 tokens, answers chat only, and the first answer in the chat says why and what to change (a model with tools, or `OLLAMA_CONTEXT_LENGTH` of 16384 or more). Models with a window under 32,000 tokens start with only the core tools. Local models get up to 10 minutes per answer instead of 2.
- Ollama: the agent form refuses a model name Ollama does not have, such as `qwen2.5` when only `qwen2.5:1.5b` is installed, and lists the installed models.
- Chat only now remembers the last few messages instead of none.
- Chat: when the connection drops before a reply arrives, the reply now says so instead of a red "Thinking", and the "did not answer in time" error appears in your language.
- Chat: while the chat list loads, placeholder rows show instead of an empty panel.

## 1.5.0b1

Includes everything from 1.4.3b1 and 1.4.3b2 below. A minor release, because it adds features; nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image) together with this release.** Change History for Cursor agents needs the new runtime; with an older one, the chat warns that the runtime is out of date and Cursor changes are not recorded until you update. Cloud agents are not affected.
- Security: the Runtime's calls back into Home Assistant (Change History snapshots and MCP result notes) now need a key Home Assistant issues for each Cursor chat turn. Before, without a Runtime token, any program on the Home Assistant host could call them, and they trusted the user id in the request. The user and chat now come from Home Assistant's own record of whom the key was issued to.
- Change History: rollback of automations, scripts, and scenes now goes through Home Assistant's own config API, the same call the editors make. Home Assistant checks the item, writes its file, and reloads it; AI Workspace no longer rewrites `automations.yaml`, `scripts.yaml`, or `scenes.yaml` itself. Because that API is for administrators, only administrators can roll these back now. The snapshot file for manual recovery is still written.
- Automations and scripts: when an agent saves the automation or script you have open in the editor, the editor shows the new version right away instead of after a page reload. If you have unsaved changes in the editor, they stay and the new version is not loaded over them.

## 1.4.3b2

- **Update the runtime (App or Docker image) together with this release.** It only carries the new version number, so the chat does not warn that the runtime is out of date.
- Cloud agents: tools load on demand. Instead of all of HA-MCP's tools (about 38,000 tokens in every request), an agent starts with search, state, and device control, the tool groups your message is about, and the groups the chat already used. It sees the names of all other tools and loads a group when it needs it, which the chat does not show as a tool step. A typical request now carries 5,000–10,000 tokens of tools. Tools from MCP servers that do not group their tools are always sent. `tools_on_demand: false` in YAML sends every tool again.
- Agents: chat history follows a token budget instead of a fixed message count: a share of the model's context window per token level (Off up to 24,000 tokens, Light 8,000, Medium 2,000). Replies are no longer cut at 2,000 characters. When a chat outgrows the budget, the oldest turns are left out six at a time behind a short summary, so the prompt cache keeps hitting on long chats. `context_window: <tokens>` in YAML overrides the window for small local models.
- Agents: each reply now keeps a one-line note per tool call with what it returned, for example the automation ids from a search. The next turn sees those notes, so the agent no longer looks up the same things again. Replies saved before this update have no notes.
- Cursor agents: a new Cursor agent gets the earlier turns from the same history builder as cloud agents. Line breaks and tables now stay, so YAML and code from earlier in the chat arrive intact instead of joined into one line.
- Prompt: every rule is stated once (small talk, MCP only, links, guide reading), the rule to call tools silently is gone because it contradicted the one status sentence, and cloud agents no longer get the Cursor rules about workspace files. The system prompt is about 20% shorter. Small talk and "look at the house before answering" now also apply when you use your own system prompt.

## 1.4.3b1

- **Update the runtime (App or Docker image) together with this release.** The key relay below also lives in the runtime, and Cursor agents use that copy.
- Agents: writing with HA-MCP's strict best-practice mode is much less work. Once an agent has read the guide, AI Workspace passes its key on to the agent's later writes, also when the agent copied it wrong or the key rotated within the hour, and tells HA-MCP not to attach the 20–50k character guide to every write again (HA-MCP's own guide asks for this). Agents read the guide once per chat instead of before each write. The key only ever comes from a guide the agent read in the last hour, so HA-MCP's read check still holds.
- Cursor agents: when the runtime is older than the integration, the chat shows a warning with both versions. An outdated runtime was the cause of guides arriving cut off ("[omitted … characters]"), which blocked writes and sent agents into long retry loops. The runtime now reports its version.

## 1.4.2

Everything from 1.4.2b1 to 1.4.2b3, plus readable errors:

- **Update the runtime (App or Docker image) together with this release.** The automation block below also lives in the runtime, and Cursor agents use that copy.
- Errors: every agent error now shows as one readable message instead of a response body or trace, for example the provider's "This model is currently experiencing high demand" instead of the JSON around it, and a provider timeout reads "The provider did not answer in time". This also applies to errors in chats saved before the update.
- Cloud agents: every tool now reaches the model with all its parameters, types, allowed values, and required fields, on every provider. Before, tools were cut to 16 parameters and many lost their types, so a model could send the wrong shape or not see a parameter at all. Cursor agents already had the full definitions.
- Cloud agents: the automation, dashboard, helper, scene, and script write tools keep their full descriptions at every token level. Other tools stay at 180 characters, and **Medium** shortens them to 100. Each request carries more tool text than before, about 38,000 tokens instead of 23,000 with HA-MCP on Off and Light, and 34,000 on Medium. Gemini gets the same parameters and types in the simpler form it accepts.
- Cloud agents: one status sentence, then the answer. Text a model writes between later tool calls is no longer shown; the model still keeps it.
- Agents: AI Workspace refuses to write an automation, script, or scene that looks like a placeholder, such as `DASHBOARD_WRITE_GUARD_ONLY`, or a guard, probe, or test item that only writes to the log. Nothing is written; the agent is told to carry on with your request or tell you what blocked it. Real automations with such words in their name still work.
- Agents: new rules to only report errors and results a tool actually returned, not to call a change done before the write confirms it, to say so instead of guessing where something came from, and that a dashboard change never needs an automation.
- Chat: names in replies link less eagerly. Only names of two or more words link, never inside quotes, and only on first mention.
- Dashboards: a change saved to the default dashboard while you are on another page, such as AI Workspace, now shows when you go back, without restarting the app.
- Model prices updated from LiteLLM.

## 1.4.2b3

- **Update the runtime (App or Docker image) together with this release.** The automation block below also lives in the runtime, and Cursor agents use that copy.
- Agents: AI Workspace now refuses to write an automation, script, or scene that looks like a placeholder, such as one named `DASHBOARD_WRITE_GUARD_ONLY` or `__dash_write_bps_ack_only__`, or a guard, probe, or test item that only writes to the log. Nothing is written; the agent is told to carry on with your request or tell you what blocked it. Real automations with such words in their name still work.
- Cloud agents: one status sentence, then the answer. Text a model writes between later tool calls is no longer shown; the model still keeps it. A long answer still streams as it arrives.
- Agents: new rules to only report errors and results a tool actually returned, not to call a change done before the write confirms it, to say so instead of guessing where something came from, and that a dashboard change never needs an automation.
- Chat: names in replies link less eagerly. Only names of two or more words link, never inside quotes, and only on first mention, so words like "Home" or a quoted section title stay plain. Entity ids and links the agent writes are unchanged.

## 1.4.2b2

- Dashboards: a change saved to the default dashboard while you are on another page, such as AI Workspace, now shows when you go back. Before, it stayed hidden until the app or browser page was restarted.

## 1.4.2b1

- Cloud agents: every tool now reaches the model with all its parameters, types, allowed values, and required fields, on every provider. Before, tools were cut to 16 parameters and many lost their types, so a model could send the wrong shape or not see a parameter at all. This should help dashboard patches that failed on GPT-5. Cursor agents already had the full definitions.
- Cloud agents: the automation, dashboard, helper, scene, and script write tools keep their full descriptions at every token level. Other tools stay at 180 characters, and **Medium** shortens them to 100. Each request carries more tool text than before, about 38,000 tokens instead of 23,000 with HA-MCP on Off and Light, and 34,000 on Medium.
- Gemini gets the same parameters and types in the simpler form it accepts.
- Model prices updated from LiteLLM.

## 1.4.1

Everything from 1.4.1b1 to 1.4.1b3, plus two floating chat fixes:

- **Update the runtime (App or Docker image) together with this release.** The shortening fix and the new status sentence also live in the runtime, and Cursor agents use that copy.
- **Shorten long Home Assistant answers** now only touches long entity listings. Dashboards, automations, guides and keys always reach the agent whole, so dashboard edits no longer fail on a missing best-practice key and a shortened config can no longer be written back. Answers over 100,000 characters are still cut, with a note telling the agent not to write them back.
- Agents: when a request needs tools, cloud and Cursor agents open with one short sentence saying what they are checking, then work. This also applies with a custom system prompt. It is skipped on the Medium and Extreme token levels and for voice requests through Assist.
- Agents: new rule against making placeholder, test, or helper automations, scripts, scenes, or entities to pass the BestPracticeKey or get around a tool error. If a write stays blocked, the agent stops and says so.
- Chat: text before and after tool calls is separated by a blank line, also after reloading the chat.
- Chat list: a **search** icon filters pinned and other chats by title or first prompt. It shows once you have more than 2 chats. The search box sits over **New Chat** and hides on Enter or when you click elsewhere; the filter stays on and the icon stays highlighted. Esc or the icon clears it.
- Floating chat: **Open full workspace** has more room below the header.
- Opening AI Workspace no longer shows the chat list sliding away on mobile.
- Mobile: **Back** closes the floating chat.
- Mobile: in a new chat the welcome text and prompt stay together above the keyboard instead of the prompt jumping to the top.
- Mobile: in an ongoing chat the prompt sits directly on the keyboard, with no gap above it on phones with a gesture bar.
- Floating button: stays above the gesture bar, no longer slips off the screen in the automation editor, and moves clear of the editor's Save button when it appears.

## 1.4.1b3

- Agents: when a request needs tools, cloud and Cursor agents open with one short sentence saying what they are checking, then work. This also applies with a custom system prompt. It is skipped on the Medium and Extreme token levels and for voice requests through Assist.
- Chat: text before and after tool calls is separated by a blank line, also after reloading the chat.

## 1.4.1b2

- Agents: new rule against making placeholder, test, or helper automations, scripts, scenes, or entities to pass the BestPracticeKey or get around a tool error. If a write stays blocked, the agent stops and says so.
- Mobile: in a new chat the welcome text and prompt stay together above the keyboard instead of the prompt jumping to the top.
- Mobile: in an ongoing chat the prompt sits directly on the keyboard, with no gap above it on phones with a gesture bar.
- Floating button: stays above the gesture bar, no longer slips off the screen in the automation editor, and moves clear of the editor's Save button when it appears.

## 1.4.1b1

- **Update the runtime (App or Docker image) together with this release.** The shortening fix below also lives in the runtime, and Cursor agents use that copy.
- **Shorten long Home Assistant answers** now only touches long entity listings. Dashboards, automations, guides and keys always reach the agent whole, so dashboard edits no longer fail on a missing best-practice key and a shortened config can no longer be written back. Answers over 100,000 characters are still cut, with a note telling the agent not to write them back.
- Chat list: a **search** icon filters pinned and other chats by title or first prompt. It shows once you have more than 2 chats. The search box sits over **New Chat** and hides on Enter or when you click elsewhere; the filter stays on and the icon stays highlighted. Esc or the icon clears it.
- Mobile: **Back** closes the floating chat.

## 1.4.0

- **Update the runtime (App or Docker image) together with this release.** An older runtime ignores Allow internet and the token levels on Cursor agents.
- Agents: the **Model** list comes from the provider with your key, and Cursor's from your Cursor account through the runtime. When the provider does not answer, a bundled list of known models is shown. Any model id can still be typed.
- Chat: every agent in the picker shows its model, not only Cursor. Each chat remembers its agent and model, so an old chat reopens with what it was using.
- Configure: **Default agent** for new chats (**Last used** keeps the old behavior). **Show model switcher** (off by default) adds a model picker next to the agent picker, so one chat can use another model of the same agent.
- Agents: **Allow internet**, off by default. Cloud agents get `web_search` and `web_fetch` in admin chats; fetch never reaches addresses on your local network. Cursor agents keep web search, page fetch, and shell only when it is on. **Existing Cursor agents lose web search, page fetch, and shell until you turn it on.**
- **Reduce token usage** and **Look at Home Assistant first** (was *Always check the house first*) moved from Configure to each agent, Cursor included. Your current values are copied onto every cloud agent on update. Look at Home Assistant first is its own switch now; only Extreme, which has no tools, ignores it. On Medium and Extreme a Cursor agent starts fresh each turn with only the last messages handed over, and Extreme gives Cursor no tools.
- Cursor: picking `composer-2` uses Composer 2 instead of switching to 2.5.
- Text-to-speech keeps `1.` on numbered lists and ends each item with a period, so engines that say "first" can.
- Mobile: typing in the prompt no longer scrolls the chat toward the bottom, key by key.
- README and docs: new screenshots, a new chat GIF, and the settings above.

## 1.4.0b1

- **Update the runtime (App or Docker image) together with this release.** An older runtime ignores Allow internet and the token levels on Cursor agents.
- Agents: the **Model** list comes from the provider with your key, and Cursor's from your Cursor account through the runtime. When the provider does not answer, a bundled list of known models is shown. Any model id can still be typed.
- Chat: every agent in the picker shows its model, not only Cursor. Each chat remembers its agent and model, so an old chat reopens with what it was using.
- Configure: **Default agent** for new chats (**Last used** keeps the old behavior). **Show model switcher** (off by default) adds a model picker next to the agent picker, so one chat can use another model of the same agent.
- Agents: **Allow internet**, off by default. Cloud agents get `web_search` and `web_fetch` in admin chats; fetch never reaches addresses on your local network. Cursor agents keep web search, page fetch, and shell only when it is on. **Existing Cursor agents lose web search, page fetch, and shell until you turn it on.**
- **Reduce token usage** and **Look at Home Assistant first** (was *Always check the house first*) moved from Configure to each agent, Cursor included. Your current values are copied onto every cloud agent on update. Look at Home Assistant first is its own switch now; only Extreme, which has no tools, ignores it. On Medium and Extreme a Cursor agent starts fresh each turn with only the last messages handed over, and Extreme gives Cursor no tools.
- Cursor: picking `composer-2` uses Composer 2 instead of switching to 2.5.
- Text-to-speech keeps `1.` on numbered lists and ends each item with a period, so engines that say "first" can.
- Mobile: typing in the prompt no longer scrolls the chat toward the bottom, key by key.
- README and docs: new screenshots and GIFs, and the settings above.

## 1.3.5

Everything from 1.3.5b1 to 1.3.5b4:

- Chat: while the agent is working, Send becomes **Stop**. Stop ends the current turn so you can send right away. Typing a follow-up turns Stop back into Send so that prompt can queue; a queued prompt shows an X.
- Change History: **Rollback for** (default 7 days) hides Rollback and Ask to restore on older rows; the log stays. Configure or `change_history_ttl_days` (1–90). Docs cover restoring an automation, script, or scene from `config/ai_workspace/changes/` if Home Assistant will not start.
- Android: the prompt stays at the bottom of the chat column and slides with the keyboard instead of resizing the message list on every viewport tick.
- Chat list: desktop titles use the full row with the ⋮ menu on hover. Mobile uses the chats icon in the header and a close X in the overlay list. An empty banner no longer adds header height.
- Usage: centered page title without a close X, filters stay on one row longer, and **1 Turn** instead of **1 Turns**.

## 1.3.5b4

- Mobile: the header uses the chats icon again. In the overlay list, dock-left becomes a close X. Desktop still docks the rail. An empty banner no longer adds header height.
- Usage: the page title is a centered heading. There is no close X; leave with the chat list or Escape. The date range wraps before the Agent / Model / Chat filters, so those three stay on one row longer.

## 1.3.5b3

- Desktop chat list: titles use the full row. The ⋮ menu sits on top of the text on hover instead of reserving a blank column. Touch keeps the button in the layout.
- Android: the prompt stays at the bottom of the chat column and slides with the keyboard (`transform`) instead of resizing the message list on every viewport tick.
- Mobile chat list uses the same **dock-left** icon as desktop. That app-bar control hides while the chat list is open. An empty banner no longer adds header height.

## 1.3.5b2

- Chat: typing a follow-up while the agent is working turns Stop back into Send so that prompt can queue. Clearing or sending it (empty input) shows Stop again.
- Usage: the chat header and Usage cards say **1 Turn**, not **1 Turns**. Column headers stay plural.
- Change History: **Rollback for** (default 7 days) hides Rollback and Ask to restore on older rows. The log stays. Configure or `change_history_ttl_days` (1–90). Docs cover restoring an automation, script, or scene from `config/ai_workspace/changes/` if Home Assistant will not start.

## 1.3.5b1

- Chat: while the agent is working, Send becomes Stop (standard template and ha-components). A queued prompt shows an X in those views and in the floating chat. Stop ends the current turn so you can send immediately; a message already in the queue is sent next.

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
