# Changelog

## 1.6.1b14

**Less empty space under the composer.** On phones the chat lost almost a full row below the agent and model pickers. It was not new: the extra space dates back to the first composer. The pickers sat 16 px (Standard) or 24 px (HA components) above the bottom edge, on top of the safe-area space that Home Assistant already keeps free for the Android gesture bar and the iOS home indicator.

- **Standard composer:** 8 px below the picker row instead of 16 px, and 4 px instead of 8 px between the message field and the pickers. The picker buttons look the same, but they now react to taps across 32 px of height.
- **HA components composer:** 8 px below the pickers instead of 24 px.
- Same in the full panel and the floating chat, on phones and desktops. The safe area is still respected, the composer still stays above the keyboard, and queued prompts, attachments and a growing multi-line message keep their layout.
- Only the integration changes. The Runtime app version moves to 1.6.1b14 with the release but has no functional change.

## 1.6.1b13

**Tasks respect "Enable fallback".** A task without an `agent` could switch from one agent to the next (for example OpenAI → Gemini → Cursor) although Fallback was off in the options: with Fallback off, `ai_workspace.run_task` still used every other agent as a fallback, in the order the agents were created.

- **Fallback off (the default, also while the Fallback section was never saved):** a task runs with exactly one agent and never switches. If it fails, the run ends with `status: error` and a warning in the log.
- **Which agent without `agent`:** the Default agent from the options. If that is "Last used" (an automation has no browser that last picked one), the first signed-in Runtime agent in the order Claude, Cursor, Codex; without one, the first agent that can take tasks. No longer simply the oldest agent.
- **Fallback on:** only the saved Fallback list is used, in its order. A task with a named `agent` starts with that agent; if it fails on the provider side, the list continues from the top, like in a chat.
- **Log:** each run starts with `task <name>: agent <agent> (fallback on|off)`.
- **Options:** the Fallback list says that it only applies while Fallback is on, and that an unsaved list is only a suggestion. A new (unsaved) list now suggests the Default agent first, then the Runtime agents (Claude, Cursor, Codex), then the others. Saved lists are unchanged.
- The `agent` field description of the action is updated in all languages; see [docs/tasks.md](https://github.com/domdus/ha-ai-workspace/blob/beta/docs/tasks.md).
- Only the integration changes. The Runtime app version moves to 1.6.1b13 with the release but has no functional change.

## 1.6.1b12

**Rollback button back in the reply row, and clean task results.**

- **Chat:** the history button (restore the chat to this point) sits again in the action row under the newest reply, next to copy and read aloud, with the time on the right. Since 1.6.1b4 it had dropped to its own line below the row. Same in the full panel and the floating chat, with the Standard and the HA components composer. Only when the last turn has no reply text does it fall back to its own row.
- **Tasks: only the final answer.** `ai_workspace.run_task` no longer puts the agent's status line from before its tool calls (for example "Wetterdaten aus Home Assistant einlesen.") in front of the result. This applies to `response`, the push message and the task chat, for every agent (API providers and the Claude, Cursor and Codex runtimes). The task instructions also tell the agent to write no status or preamble sentences.
- **Tasks: push messages as plain text.** Phones do not render Markdown, so the push no longer shows `**` and similar marks: bold, italics, code marks, headings and link syntax are removed, list items start with "• ", line breaks stay, and a long result is cut at a line or word boundary (about 1000 characters, "…"). The task name stays the notification title. The task chat and `response` keep the Markdown.
- **Tasks: fallback in the log.** When an agent fails and the next one takes over, the Home Assistant log now says which agent took over and that the task finished with it. Failed runs are logged as warnings.
- **Usage sensors:** fixed `RuntimeError: Attribute hass is None` ("Task exception was never retrieved") from `sensor.py`. A usage or plan sensor whose setup was aborted (for example by a reload) or that was removed stayed in the refresh list; refreshes now only write sensors that are added to Home Assistant.
- Only the integration changes. The Runtime app version moves to 1.6.1b12 with the release but has no functional change.

## 1.6.1b11

**No more Tasks icon in front of the chat title.** Since 1.6.1b6 the full panel showed the calendar icon that opens the **Tasks** page in the chat header, directly before the title, in every chat (most visible on phones). It is gone from the header.

- The **Tasks** page is still one tap away: the same icon sits at the top of the chat list, next to Activity and Usage. On a phone, open the chat list first.
- Task chats get no header icon either; they look like any other chat.
- The floating chat never had the icon and is unchanged.
- Only the integration changes. The Runtime app version moves to 1.6.1b11 with the release but has no functional change.

## 1.6.1b10

**The Cursor model list matches the Cursor SDK list again.** The built-in Cursor model list (used when the Runtime cannot list the models itself) is synced with the Cursor SDK as of 2026-11-20.

- New: `claude-fable-5-2`, `gemini-4-neon`, `gemini-4-carbon`, `gemini-4-hydrogen` and `deepseek-v41-flash-1017` (DeepSeek is a new provider in the Cursor list).
- Removed: `gemini-3.7-flash` and `gemini-3.6-flash`, which Cursor no longer lists.
- Only the integration changes. The Runtime app version moves to 1.6.1b10 with the release but has no functional change.

## 1.6.1b9

**The message field stays one line until the text needs more.** After sending, the prompt often stayed two lines tall although it was empty. Now it goes back to one line, in the floating chat and the full panel, with the standard field and with **Use HA Components**.

- It still grows for long text that wraps, pasted text with line breaks, and Shift+Enter; the buttons move below the text only then.
- Sending, queueing a message, switching chats, taking back a queued message and dictation all reset the height to fit the text.
- A long placeholder (for example "Next message" while a reply is running, in a narrow chat) stays on one line and no longer makes the empty field two lines tall.
- Queued messages and attachment chips no longer leave the empty field two lines tall.
- Only the integration changes. The Runtime app version moves to 1.6.1b9 with the release but has no functional change.

## 1.6.1b8

**Model prices refreshed from LiteLLM.** The cost display knows a few new models and an updated price tier. Nothing else changes.

- New: `claude-fable-5-2`, `claude-mythos-5-2`, `gemini-4-carbon`, `gemini-4-hydrogen`.
- `gpt-6-cyber` now has separate prices above 272k tokens of context (input, cache read and output), like the other GPT-6 models.
- Only the integration's price table changes. The Runtime app version moves to 1.6.1b8 with the release but has no functional change.

## 1.6.1b7

**The fallback agent list can be reordered by drag.** In **Settings → AI Workspace → Configure → Fallback**, every agent chip in **Agents in order** now has a drag handle. Drag a chip with the mouse or by touch to move it; you no longer have to remove an agent and add it again.

- The saved order is exactly the order shown. Lists saved with 1.6.1b6 keep their order.
- The help text in all 15 languages now says to drag an agent to change the order.
- Uses Home Assistant's own sortable chips (`reorder` on the select selector), so it looks like the other Home Assistant forms. Needs Home Assistant 2025.12 or newer, the same minimum as before.
- Only the integration changes; the Runtime app does not need an update.

## 1.6.1b6

**Agent fallback, agent tasks, and "Use HA Components" only changes the message field.** When one agent's provider fails, the next agent in your list carries on. The new action `ai_workspace.run_task` and a **Tasks** page run prompts on a schedule as real automations. Messages always use the standard look.

**Agent fallback: when one agent's provider fails, the next one in your list carries on.** Optional and off by default; existing setups do not change.

**Settings → AI Workspace → Configure → Fallback** (collapsed)
- **Enable fallback** and an ordered list of your agents (drag the chips to change the order, since 1.6.1b7). The first agent is the preferred one and new chats start with it. While fallback is on, this list replaces the **Default agent**.
- **Back to the preferred agent**: *Off* (the chat stays on the agent that took over), *On new message*, or *After reset or wait time*. It never switches in the middle of a reply.

**When it switches**
- Only for provider-side failures: plan or token limit, HTTP 429, expired or invalid sign-in, timeouts, connection errors, overloaded or failing servers (5xx/529).
- Never when you stop a reply, a tool fails, the model refuses, or the request itself is wrong.

**In the chat**
- A short notice says what happened, for example "Claude am Limit (Reset 18:30). Cursor macht weiter." The reset time comes from the plan limits when known.
- With fallback on, the chat header (full page and floating chat) shows the agent the chat runs on now. Each chat remembers its active agent.

**Mid-task handoff**
- Sessions do not carry over between engines, so the next agent gets the original task, the chat so far and a journal of the tool calls this turn already made, with their results, plus a clear instruction not to repeat device actions, file writes, commits or pushes. Calls that started but never reported back are marked so the next agent checks first.
- The list is walked from the top until one agent succeeds. A reply that keeps running in the background (page closed) goes on the same way.
- Work that already used the Runtime's workspace or shell only goes to Runtime agents (Claude SDK, Cursor, Codex); chat-only cloud agents are skipped. Callers can also ask for this with `"workspace": true`.
- If no agent is left, the task pauses with a message and continues by itself as soon as one is back (checked at the reset time or after 5, 15, 60 minutes), instead of failing. You can stop it as usual.

**Going back up**
- Checked only at the start of a turn, from the top of the list. Limits are never checked before their known reset; other failures wait 5, 15, then 60 minutes. The check is cheap (Runtime status and sign-in, or the provider's model list), never a model prompt. After going back, the chat stays put for 10 minutes so two agents do not take turns failing.
- A chat you moved to another agent yourself stays where you put it.

**Agent tasks: prompts that run on a schedule, as real Home Assistant automations.** A new action **AI Workspace: Run agent task** (`ai_workspace.run_task`) runs a prompt with an agent, and a new **Tasks** page in AI Workspace creates and manages those automations for you.

**The action**
- `prompt` (templates work), `task_name`, `agent` (empty: the Fallback list when on, else the default agent, then the others), `chat` (none, or one continuing task chat per task, titled after the task), `notify` (short result as a push message), `allow_changes` (off by default) and `timeout` (10 minutes by default). It shows in the automation and script editor with its fields in all 15 languages.
- With a response variable it returns `status`, `response`, `agent`, `chat_id`, `duration` and `usage`. Without one it runs in the background.
- Every run starts fresh; only the task chat keeps earlier runs. Write the prompt so it says everything the agent needs.
- **Read-only by default:** with Allow changes off the agent only gets tools that read Home Assistant; service calls and config writes are refused.
- **Loop protection, always:** a task cannot start tasks, trigger automations, or create, edit or delete automations or scripts. Runtime agents get no shell or file tools during a task. The same task never runs twice at once, at most three run together.
- Without a named agent, task runs use the **Fallback** list when Fallback is on (agents waiting out a limit last) and hand over to the next agent on provider failures with a journal of the tool calls already made, like chats do. A failing tool or a refusal never switches. Tasks do not pause; with no agent left the run ends with an error.
- Task runs count on the Usage page, tagged as tasks. A settings reload waits for running tasks like it waits for chat replies.

**The Tasks page** (administrators)
- Name, prompt, schedule (daily, weekly, every N minutes/hours, or advanced in the automation editor), agent, result (task chat, push, or both) and Allow changes.
- Saving writes a normal automation through Home Assistant's automation config API (the automation editor's own) and labels it **AI Workspace**; the page lists exactly those. No scheduler of its own.
- Each task shows on/paused, the last run and its result, and has Run now, Open task chat, Open in automation editor, and Delete.
- Tasks you change in the automation editor keep working; the page shows what it can and keeps the rest.

- Examples (morning briefing, weekly report, evening check): [docs/tasks.md](../docs/tasks.md).

**"Use HA Components" now only changes the message field.** Messages always look the same, with the option on or off.

- With **Use HA Components** on, only the composer changes: Home Assistant's own message field (label "Message") with the agent and model pickers under it, as before. Your messages, the agent's replies, the "Thinking" line, the row with time, copy and read aloud, notices and tool steps always use the standard look, in the floating chat and in the full panel.
- The standard look follows your Home Assistant theme as before. The floating chat button is the same in both modes.
- The option stays off by default and keeps its setting. If you had it on, you now get the standard messages with the HA message field; nothing to change.
- Copy, read aloud, the reply row fading in after a reply, drafts, queued prompts and the chat title work the same with both message fields.

- The **Last used** choice of **Default agent** is now translated (German "Zuletzt verwendet" and all other languages).

**Update**
- Update the integration and the Runtime App to 1.6.1b6.
- Runtime: Claude, Cursor and Codex agents need Runtime 1.6.1b6 or newer to run tasks (its MCP proxy enforces read-only and loop protection). Tool calls also carry a short summary of their arguments and results for the fallback journal; with an older Runtime the fallback still works and the journal only has the tool names. Cloud agents work with Home Assistant alone.

## 1.6.1b5

**Chats get a real title, and the floating chat shows it.** A pasted link or a long first message no longer becomes the chat title, Claude and Cursor on the Runtime now write a short title too, and the floating chat no longer stays on "New chat".

**Title in the header**
- The floating chat and the chat header stayed on "Neuer Chat" / "New chat" even after the chat had a title, until you reloaded. The first title now arrives together with the reply.
- If the header still shows the placeholder when a reply is done, it asks Home Assistant once for the title. A reply you follow from another device or after switching back updates the title too.

**Better first titles**
- The first title used to be your first message cut at 80 characters, so a pasted link became the chat title. A link now becomes a short "site: topic" title, for example a Heise article turns into something like "Heise: DGX Spark Nvidias Desktop KI Computer". The link itself is never the title.
- Other text becomes its first sentence, at most about 6 words or 48 characters, cut at a word and without a dangling "und", "im" or "der" at the end.

**Written titles**
- With **Save tokens** off, Claude and Cursor (on the Runtime and as API agents) then write a short topical title for the new chat, 2 to 6 words in your language, for example "Heise Artikel über Nvidia Spark". On the Runtime it shows while the reply is still being written when it is ready in time. Claude uses one short extra request for it, without tools.
- Codex and Assist / voice chats keep the improved first title.
- A title you renamed yourself is never overwritten. Existing chats keep their titles.

- The Runtime App changed: update it to 1.6.1b5 so Claude and Cursor on the Runtime write titles. The better first titles and the header fix work with Home Assistant alone.

## 1.6.1b4

**Copy and read aloud under every reply, and what you type stays in its chat.** Each finished agent reply gets its own small row with copy, read aloud and the reply time. Text typed but not sent, and prompts queued while a reply runs, now stay with their chat.

**Under each reply**
- **Copy** copies that reply's text and markdown, without tool steps, status lines or the "cut off" note.
- **Read aloud** reads that reply with your text-to-speech voice. Only one reply plays at a time: starting another one stops the first, and while a reply plays its button turns into **Stop**. The button is hidden when no text-to-speech engine is set up.
- The **time** sits on the right ("21:04", "gestern, 21:04", "17.11., 21:04"). The newest reply always shows it; on older replies it shows when you point at or focus the row.
- On a computer the row is faint until you point at or focus the reply. On a phone or tablet it is always fully visible. The buttons work with the keyboard and have screen-reader labels in all languages.
- Your own messages, replies still being written, error messages and replies that only ran tools get no row.
- The row under the chat now only has the chat-wide actions (**Verlauf**). The "copy last reply" button and the time are gone from there because each reply has its own now. The speaker only shows there while a reply is read aloud on its own (automatic read-aloud), so you can pause or stop it.

**Drafts**
- Kept per user in this browser for 7 days (text only, up to 8,000 characters, the 30 newest chats; see [privacy](../docs/privacy.md)). Attached files and pictures stay with the draft while the page is open.
- Sending clears the draft, and deleting a chat clears it too. A chat in the list that has a draft shows *Draft* next to its title.

**Queued prompts stay in their chat**
- Prompts queued while a reply runs belong to that chat. Switching to another chat no longer drops them or puts the first one into the other chat's message field.
- They are still sent in their own chat when the reply finishes, also while you look at another chat or the panel is closed, one after the other. The reply gets its unread dot in the chat list.
- Back in the chat, its queue is shown again (only there) and goes on from there. If the chat is still busy (for example from another device), a new message waits in the queue instead of failing.

- Only the chat changed. The Runtime App can stay on 1.6.1b3.

## 1.6.1b3

**The agent finds the chat you mean.** “Im Bewässerungs-Chat”, “Bewässerungschat”, “bewaesserung” or a small typo all find the chat titled “Bewässerung”, and a newer or pinned chat that only shares a common word (“Börse Tabelle” for “mach eine neue Tabelle”) no longer wins.

**Other chats**
- Title matching ignores case, umlauts (ä/ae), hyphens and endings, understands compounds with -chat, -verlauf and -thread and allows small typos. The whole title in the message beats a word right next to “chat”, which beats a few shared words; rarer words count more. Pin and recency only break a tie. Only the best chat is used, a second one only when it fits just as well.
- “Im anderen / vorigen / letzten Chat” without a title means the chat you used last.
- The excerpt is filled from the newest message back (about 16,000 characters): the newest reply comes whole, with tables and code intact, and anything left out is marked. A short summary of the older messages comes with it.
- Agents can look themselves: new read-only tools `list_chats` and `read_chat`, for Cursor, Claude and Codex on the Runtime and for cloud agents. They only see your own chats.
- The same for every engine and every token mode (the save modes get a smaller excerpt, and clipping a long message never cuts it). Assist agents get it too. The excerpt is kept with your message, so it is still there after a resume, a restart or an agent switch.

**Opening a chat**
- The chat shows placeholder bubbles while it loads (no animation with reduced motion), and after 8 seconds says that it takes longer than usual. After 20 seconds, or when Home Assistant does not answer, you get **Try again** instead of an empty new chat. Only a chat that was really deleted falls back to a new chat.
- Faster start: the chat’s messages are asked for as soon as the panel opens, the theme from your last visit is used right away, agents, mic and usage settings load after the chat, and the last chat you opened paints at once from your browser (see [privacy](../docs/privacy.md)).
- While AI Workspace is still starting, its API answers 503 with Retry-After instead of a server error.

**Unread replies**
- A dot on a chat in the list means an agent reply arrived there while the chat was not open. Opening the chat clears it, on every device. On a phone the **Chats** button shows the dot too. The list updates by itself while a reply runs in the background.

**Under the reply**
- The copy button under the chat now copies only the last agent reply (its text and markdown, without tool steps), not the whole chat. It is greyed out while there is no reply yet.
- The time of the reply shows on the right of that row: “21:04” today, “gestern, 21:04” yesterday, “17.11., 21:04” before that (with the year if it is not this year), in your Home Assistant language, time zone and clock format. Hover it for the full date. A live reply gets its time when it is finished; on a narrow screen the time gets shorter before the buttons move.

- Update the Runtime App to 1.6.1b3 too, so Cursor, Claude and Codex agents on the Runtime are told about `list_chats` and `read_chat`. The rest works with an older Runtime.

## 1.6.1b2

**Sign in with ChatGPT goes on by itself.** On a Codex (runtime) agent the form shows OpenAI's link and the one-time code and then moves on as soon as OpenAI confirms the code. No more submitting to check.

**OpenAI Codex on the Runtime**
- **Sign in with ChatGPT is one step less.** The form shows OpenAI's link and the one-time code and then goes on by itself as soon as OpenAI confirms the code. No more submitting to check. Closing the dialog stops the sign-in on the Runtime.
- If OpenAI refuses the code, the form says what to do: allow device-code sign-in once in ChatGPT under **Settings → Security** (a workspace admin allows it for workspace accounts).
- **An expired or revoked ChatGPT sign-in says so in the chat, in your language**, with the way out: sign in with ChatGPT again on the agent (or replace the OpenAI API key). Before, some of these showed OpenAI's raw message.
- **Plan limits for the ChatGPT plan now really show up.** Codex reports them outside the chat turn, so the Runtime never saw them. It now reads them after each turn (Runtime 1.6.1b2).
- The Codex account step shows its status in all 15 languages (it was English or German only).
- Update the Runtime App to 1.6.1b2 too for the plan limits and the expired sign-in message.

## 1.6.1b1

**Fewer unneeded Home Assistant lookups.** Agents were told to call a Home Assistant tool before answering anything that sounded like the house, so a question about cutting back a plant, frost protection or how much to water ran a lookup, opened with a status sentence and sometimes linked a random entity. Now an agent looks things up only when you ask for live house data (a device, state, history, count, list, weather) or want a change.

- **General questions get a direct answer.** Plant care, gardening, frost protection, watering math from amounts you gave and other general reasoning get no tool call and no status sentence. Live house data still always comes from a tool, never from memory.
- **The status sentence only comes with a real tool call**, and never more than one per request.
- **No made-up entity links.** Only real Home Assistant items a tool returned in this chat are linked. Plants, products and other things without an entity stay plain text.
- **The per-message house note is gone.** Cursor, Claude SDK and Codex turns no longer get "call a Home Assistant tool before you answer" appended to every house-sounding message. The standing instructions say when to look.
- Your own system prompt stays as it is. A Runtime workspace `AGENTS.md` or `.cursor/rules/home-assistant.mdc` that is still an unedited built-in version gets the new text by itself; an edited one is left alone.
- Update the Runtime App to 1.6.1b1 for the new Cursor workspace rules. The rest works with a 1.6.0 Runtime.

## 1.6.0

Everything from 1.6.0b1 to 1.6.0b17, plus OpenAI Codex agents on the Runtime. Nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.6.0`) together with this release.** Much of it is in the runtime. The chat shows a hint when the runtime is older than 1.6.0.

**Claude on the Runtime (experimental)**
- A **Claude (Anthropic)** agent can run Claude Code on the AI Workspace Runtime: **Advanced → Use Claude SDK (runtime) (experimental)**. Off, it stays a cloud agent with an Anthropic API key. Tools, images, Effort, usage and cost work as on Cursor agents.
- **Sign in with Claude plan** on the agent form: open the link, sign in with your Pro or Max account, paste the code. Or paste a Claude Plan token or an Anthropic API key on the agent. If the Runtime already has access, the form offers **Use the Runtime's existing access**.
- ⚠️ **It is not clear whether Anthropic allows a Claude plan here.** Anthropic does not permit third-party apps to offer Claude.ai login or to route requests through plan credentials. It *may* still count as private use on your own hardware with your own account, but Anthropic has not confirmed that. An Anthropic API key is the safe choice. See [Use your Claude or ChatGPT plan](../README.md#use-your-claude-or-chatgpt-plan-experimental).
- The Runtime App's options no longer have Claude fields; old values carry over by themselves. An expired or revoked sign-in says so in the chat, in your language.
- An existing chat can switch between Cursor and Claude in the chat bar.

**OpenAI Codex on the Runtime (experimental)**
- An **OpenAI** agent can run OpenAI Codex on the AI Workspace Runtime: **Advanced → Use Codex (runtime) (experimental)**. Off, it stays a cloud agent with an OpenAI API key. MCP tools, images, Effort, Save tokens, usage and approval cards work as on Cursor and Claude SDK agents. See [Codex agents](../docs/codex-runtime.md).
- **Sign in with ChatGPT** on the agent form: open OpenAI's link, enter the one-time code the form shows, submit. Uses your ChatGPT plan (Plus, Pro, Business); device-code sign-in has to be allowed once in ChatGPT under **Settings → Security**. Or paste an OpenAI API key on the agent. If the Runtime already has access, the form offers **Use the Runtime's existing access**.
- Tools follow the same rules: MCP only for normal users, workspace file edits in admin chats, the shell and web search only with **Allow internet**. Nothing that would need an approval runs.
- **Plan limits** for the ChatGPT plan (5-hour and weekly windows) appear on the Usage page and warn in the chat near the limit.
- Codex agents offer no speech-to-text or text-to-speech; those need an OpenAI API key in Home Assistant.

**Usage and plan limits**
- **Plan limits** on the Usage page: session (5 hours) and week (7 days) in percent with reset times, for the Claude plan and, when they report them, Cursor and Codex. A chat hint when a plan enters its warning zone, and a translated message when it is full. Optional sensors.
- **Coding workers count:** jobs handed to an Agent Worker over MCP are stored under **Worker: Claude Code**, **Worker: OpenAI Codex** or **Worker: Cursor**.
- A cost the provider reports itself is kept instead of a list-price estimate.

**Chat and MCP**
- **MCP tools can ask you in the chat** (elicitation): an approval card with **Allow** / **Deny** for Cursor and Claude SDK turns, also for agent-worker jobs waiting for approval. Only a click answers it.
- **Save tokens** on Runtime agents keeps the agent for a while (Claude until its context reaches about 40,000 tokens, Cursor for 4 turns) instead of starting over every turn, and keeps the agent's **Effort**.
- Long pastes (over 8,000 characters) reach Cursor and Claude SDK agents.
- Saving settings waits for running replies instead of cutting them off, and a reply that was still cut off says so.
- Sending no longer lowers other audio on phones when read-aloud is off.

**Runtime**
- A reset or reinstalled Runtime App is paired again by itself, so Cursor and Claude no longer stay greyed out.
- The Cursor API key is optional on the App; a Claude-only Runtime works.

## 1.6.0b17

**Sending a prompt no longer lowers other audio on your phone.** With auto read-aloud off, every send still played a silent clip to prepare read-aloud. On Android (Home Assistant app) that took audio focus, so a YouTube video or music went quiet before any answer came. Now AI Workspace leaves audio alone unless the reply is read aloud.

- **Auto read-aloud off:** sending touches no audio. Tapping **Read aloud** still works as before.
- **Auto read-aloud on:** unchanged, sending still prepares playback so the reply can be read on phones.
- **After read-aloud ends or is stopped**, the audio is unloaded, so other apps play at full volume again.
- Only the chat changed. The Runtime App can stay on 1.6.0b16.

## 1.6.0b16

**Plan limits for the Claude plan now show up.** Since 1.6.0b12 the Usage page said "No plan data yet" for Claude SDK agents on a Claude plan, however much they chatted, and the chat never warned before the limit. Claude Code does report the plan's use with each turn, but the Claude Agent SDK hands it over as an object the Runtime did not read, so every report was dropped. Now the Runtime reads it.

- **Plan limits** on the Usage page show session (5 hours) and week (7 days) in percent, when each resets, and when they were last seen. The newest values are kept on the Runtime and in Home Assistant.
- **Every reading reaches Home Assistant**, not only the one that crosses the warning zone. Opening the Usage page also fetches the Runtime's latest values.
- **A turn without numbers:** the Runtime reads them from Anthropic's usage endpoint, the one Claude Code's `/usage` uses. It is not a model call and uses no quota, and it runs at most every 10 minutes. `CLAUDE_PLAN_USAGE_READ=off` on the Runtime turns it off. Tokens from `claude setup-token` may not be allowed to read it; then the chat's own numbers count.
- **Only a status, no percent:** shows as "Below the warning threshold" instead of "No plan data yet". A window that has reset since says so instead of an old percentage.
- The chat hint when a plan enters its warning zone works again, because it relied on the same reports.
- Update the Runtime App to 1.6.0b16 too. AI Workspace asks for it.

## 1.6.0b15

**MCP tools can ask you in the chat (elicitation).** The Runtime now tells MCP servers it can ask the user. When a server asks something during a Cursor or Claude SDK turn (`elicitation/create`), for example the agent-worker before it runs a command on another server, the chat shows a card with the message, the exact command and **Allow** / **Deny**. The answer (accept, decline, cancel) goes back to the server. See [docs/mcp.md](../docs/mcp.md#questions-and-approvals-from-mcp-tools).

- **Only a click approves.** The model never sees the request, and chat text or tool output cannot answer it: the Runtime only takes an answer from Home Assistant with the card's own key.
- **Cards stay open** when you close and reopen the chat or the app, and several can wait at once. **Approval wait** (AI Workspace → Configure, default 10 minutes) cancels a card nobody answers.
- **agent-worker jobs in `input_required`** get the same card, and the click approves or denies the job at the worker (`POST /jobs/<id>/approve`).
- Update the Runtime App to 1.6.0b15 too. AI Workspace asks for it.

## 1.6.0b14

**Save tokens on Cursor agents keeps the agent for 4 turns.** With **Save tokens** on, a Cursor agent on the Runtime started over on every turn and forgot its own tool results. Now a warm agent runs 4 turns, then the next turn starts a new one with the recent history from Home Assistant. Cursor reports tokens per turn summed over all its model calls (often several 100,000 for one turn), so the size of its context cannot be measured as on Claude, and turns are counted instead. A chat idle for 2 minutes still gets a new agent, as before.

- **Save tokens never picks up an old stored agent or session.** It only keeps one the Runtime is running or has measured. After a Runtime restart, the first turn starts new, for Claude and Cursor.
- **Changed Remembered notes** now reach a kept Cursor agent too.
- Update the Runtime App to 1.6.0b14 too. AI Workspace asks for it.

## 1.6.0b13

**Save tokens on Claude SDK agents keeps Claude's session.** With **Save tokens** on, a Claude SDK agent started a new Claude session on every turn. Claude forgot its own tool results, and the cached start of the chat had to be sent and written again each time. Now the session continues until a turn's context reaches about 40,000 tokens. The next turn then starts a new session, and Home Assistant hands over the last messages as before. With Save tokens off, nothing changes: the session always continues. Changed **Remembered notes** reach a continued session as before. Cursor agents still start a new agent every turn with Save tokens.

- **Effort stays with Save tokens on Runtime agents.** Save tokens dropped the agent's **Effort** setting. On cloud agents this goes with a reply cap, but the Runtime has none, so Claude Code and Cursor fell back to their own, often higher, default. A **Fast** agent with Save tokens could think more than without it. Cursor and Claude SDK agents now always send their effort.
- **Binding the Runtime no longer depends on the plan limits.** The Runtime's plan limits are only stored when it reports some, and a storage error is logged instead of making Cursor and Claude unavailable.
- Update the Runtime App to 1.6.0b13 too. AI Workspace asks for it.

## 1.6.0b12

**Claude is set up in one place: the agent form.** The Runtime App's **Configuration** no longer has **Claude Plan token**, **Anthropic API key** or **Claude model**. Use **Sign in with Claude plan** on the Claude (Anthropic) agent with **Use Claude SDK (runtime)** on, or paste a token or key on that agent. `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` and `CLAUDE_MODEL` stay for Docker runtimes. See [docs/claude-runtime.md](../docs/claude-runtime.md#runtime-options).

- **Plan limits in the chat and on Usage.** Claude SDK `rate_limit_event` drives a compact plan notice when usage crosses into warning (once per crossing), and a translated rejection with local reset time when the session or week is full. The Usage page has a **Plan limits** block (separate from token cost) with a link to the official Claude usage page. Home Assistant sensors on the Usage device show session %, week % and session reset when plan tracking is on. Cursor and Codex use the same storage when their streams report limits; otherwise their slots stay empty.
- **Nothing to do on update.** A Plan token from the old App options becomes the Runtime's sign-in on the first start, unless someone already signed in (that sign-in stays). It happens once; a later sign-out stays signed out. An old Anthropic API key and Claude model keep working in the background without a field, until the App's Configuration is saved again. The App log names the old fields it found, never their values.
- **The Cursor API key is optional on the App.** A Claude-only App has no required field; Cursor then shows as not set up and Claude works.
- **A fresh sign-in wins.** Order: credential on the agent → **Sign in with Claude plan** → `CLAUDE_CODE_OAUTH_TOKEN` → `ANTHROPIC_API_KEY` (or the old App option key). Before, a Plan token in the App options or the environment won over a sign-in. The Claude account step no longer says that an options token wins; with an older Runtime it says to update it.
- **Expired or revoked sign-in.** When Anthropic refuses the Claude credential (HTTP 401, `authentication_error`, "Invalid API key", an expired or revoked OAuth token), the chat says so in your language: open the agent's settings and sign in with Claude again, or replace the token or key. Other errors keep their own message. The Runtime sends it as error code `claude_auth_failed`.
- **Worker usage:** agent-worker jobs that report status `completed` or legacy `succeeded` count as final, like `succeeded`.
- Update the Runtime App to **1.6.0b12** and the integration together.

## 1.6.0b11

**Switching an existing chat from Cursor to Claude works.** New chats were fine, but in a chat that started on Cursor, picking Claude in the chat bar still ran the turn on Cursor in the Runtime. Without a Cursor key on the Runtime, every Claude message ended with "Cursor API key is not set". The Runtime kept the engine a chat was created with and ignored the switch. Now AI Workspace sends the chosen engine with every turn, and the Runtime moves the chat to it. The new engine starts a fresh agent and gets the chat so far from Home Assistant, as after any agent switch. Switching back works the same way.

- An agent id from the old engine is no longer handed to the new one. Claude only resumes its own sessions.
- Update the Runtime App to 1.6.0b11 too. AI Workspace asks for it.

## 1.6.0b10

**Sign in with Claude works.** After you pasted the code, the form waited and then said that the Runtime got no answer from Anthropic in time. The code reached Claude Code, but Claude Code took the Enter that followed it as part of the pasted text, so the code was never sent. The Runtime now sends the Enter separately. A wrong code is rejected right away.

- **The Runtime already has Claude access?** The Claude account step now offers **Use the Runtime's existing access** first: a Plan token or API key in the App options, or an earlier sign-in. No new sign-in needed.
- **Cursor:** the form says under the key field when the Runtime already has a Cursor key, so you can leave the field empty.

## 1.6.0b9

**Cursor no longer greys out for good after the Runtime App was reset.** A reinstalled or reset Runtime App comes back without its token. AI Workspace still had the old token saved, the Runtime refused it, and Cursor and Claude SDK agents stayed unavailable. Now AI Workspace pairs its own Runtime App again by itself and gives it the saved token back. If that fails, it tries again after 10 minutes at most instead of restarting the App on every check, and the agent says to set the same token on both sides.

**Usage**
- Coding workers count on the Usage page. When a chat agent gives a task to an Agent Worker (or the older Cursor Worker) over MCP, the usage the worker reports for a finished job (`agent_run` / `agent_job`, also `cursor_agent` / `cursor_job`) is stored on its own under **Worker: Claude Code**, **Worker: OpenAI Codex** or **Worker: Cursor**, separate from the chat agent's turn. It works for cloud agents and for Cursor and Claude SDK chats (through the Runtime's MCP proxy; update the Runtime too).
  - Only finished jobs count (succeeded, failed, cancelled). Polling the same job again does not count it twice.
  - The global usage sensors carry a `workers` attribute per engine.
- A cost the provider reports itself (`cost_usd`, for example from Claude Code or the Cursor SDK) is kept instead of being replaced by a list-price estimate. Without a reported cost, the list price is used when the model is known; otherwise tokens are stored and the cost stays unknown.

**Sign in with Claude plan.** Claude (Anthropic) agents with **Use Claude SDK (runtime)** on get a **Claude account** step after the agent form. It shows the runtime's Claude credential and offers **Sign in with Claude plan**: open the link, sign in with your Pro or Max account, paste the code Anthropic shows, done. The runtime keeps the Plan token itself, so every Claude SDK agent on it can use it. This replaces the **Sign in with Claude (experimental)** tick box from 1.6.0b7. Cloud-API agents and Cursor agents are unchanged. See [docs/claude-runtime.md](../docs/claude-runtime.md#sign-in-with-claude-plan).

**Runtime**
- Sign-in API per engine: `GET /api/auth/{engine}`, `POST /api/auth/{engine}/login`, `GET|POST|DELETE /api/auth/{engine}/login/{id}`, `DELETE /api/auth/{engine}` (sign out). Claude uses the bundled Claude Code CLI (`claude setup-token`) in a pseudo-terminal; Cursor reports `not_supported` (API key only). `/api/health` lists engines with a sign-in under `"login"`.
- The Plan token is kept in `/data/auth/claude-oauth-token` (owner-only), never sent to Home Assistant and never logged. The CLI runs without the runtime's own credentials in a temporary folder that is removed afterwards.
- Credential order: agent token from Home Assistant → **Claude Plan token** option → signed-in token → **Anthropic API key** option.
- `/api/claude/login` from 1.6.0b7 still answers older integrations and shares the one sign-in at a time with the new API.
- Without Home Assistant: `docker exec -it ai-workspace-runtime python -m app.claude_login`.

**Integration**
- Agent form: **Claude account** step (Save agent / Sign in with Claude plan / Sign out on the Runtime / Back), the sign-in form with link and code field, and a **Signed in** confirmation with the sign-in date (no secrets). A rejected or expired code gets a fresh link on the same form; closing the dialog cancels a waiting sign-in.
- The token field stays as an optional fallback. Signing in clears an older token on that agent, because it would win over the sign-in. Without any credential, saving waits for a sign-in instead of failing with "required" (runtimes without sign-in still ask for the token).
- Translations for all 15 languages.

**Update the runtime together with the integration** to get the sign-in; older runtimes show an update hint on the Claude account step and keep working with a pasted token.

## 1.6.0b8

**Long pastes work with Cursor and Claude SDK agents.** A message over 8000 characters (for example pasted HTML) failed with "The AI Workspace Runtime answered HTTP 422" and never reached the agent.

- The integration no longer sends more than the runtime accepts, so this works with an older runtime too.
- The runtime shortens its helper fields instead of refusing the message, and takes messages with four full attachments.
- If the runtime still refuses a request, the chat says why (for example that the message is too long) instead of a bare HTTP code.

## 1.6.0b7

**Sign in with Claude (experimental).** A Claude SDK agent can get its Claude Plan token without Claude Code on your computer: tick **Sign in with Claude (experimental)** in the **Claude SDK (runtime)** section and press OK, open the link, sign in, and paste the code Anthropic shows. The runtime runs Anthropic's own `claude setup-token` and the token is saved on the agent. See [Claude SDK agents](../docs/claude-runtime.md#sign-in-with-claude).

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.6.0b7`) for this.** An older runtime says so on the form; pasting a token still works.
- A mistyped code can be corrected; a refused or expired one gets a new link.
- The runtime keeps nothing: the CLI runs in a temporary folder that is deleted afterwards, and the code and token are never logged.

## 1.6.0b6

- **Use Claude SDK (runtime)** on a Claude (Anthropic) agent moved to **Advanced** and is marked **experimental**.
- Its help text now says what happens: press **OK** after changing it, and the form shows the matching fields without saving yet.
- The runtime is unchanged from 1.6.0b2.

## 1.6.0b5

**Saving settings no longer cuts off a running chat reply.**

- A change in **Configure** or on an agent now waits until running chat replies finish (up to 10 minutes) before AI Workspace reloads with it. Before, the reload stopped the reply in the middle, and the chat showed only what had arrived so far.
- A reply that is still cut off (Home Assistant restarts, or **Reload** on the integration) now says so under the reply, in the chat and later in the history, instead of looking finished.
- The runtime is unchanged from 1.6.0b2.

## 1.6.0b4

**One Claude (Anthropic) agent, in the cloud or on the runtime.** The separate **Claude SDK** choice in **Add agent** is gone. Add **Claude (Anthropic)** and turn on **Use Claude SDK (runtime)** for a Claude SDK agent on the AI Workspace Runtime, or leave it off for Anthropic's cloud API. See [Claude SDK agents](../docs/claude-runtime.md).

- Turning the switch on or off shows the matching fields right away: the **Claude SDK (runtime)** section with the runtime address, password, and **Claude Plan token or Anthropic API key**, or the cloud API key. Nothing is saved until you submit those.
- Runtime problems (runtime not found, too old, no credential, key refused) show at the top of the form.
- **Effort** stays on cloud Claude agents, as before.
- New agents are named **Claude** either way; the switch only changes where Claude runs.
- Claude SDK agents from 1.6.0b1 and b2 become Claude (Anthropic) agents with the switch on when the integration loads, with their credential, model, and name. In YAML, `provider: claude` still makes a Claude SDK agent.
- The runtime is unchanged from 1.6.0b2; Cursor agents are unchanged.

1.6.0b3 was withdrawn: it was built without 1.5.4 and the 1.6.0b1/b2 fixes. 1.6.0b4 has all of them.

## 1.6.0b2

**Claude SDK agents work with your Claude plan again.** 1.6.0b1 refused Claude Plan tokens; that was wrong and is undone. See [Claude SDK agents](../docs/claude-runtime.md).

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.6.0b2`) together with this release.** The change is in the runtime too. The chat shows a hint when the runtime is older.
- The credential on a Claude SDK agent takes a **Claude Plan token** (`sk-ant-oat…`, from `claude setup-token`, uses your Claude subscription) or an **Anthropic API key** (`sk-ant-api…`, billed as API credits).
- New App option **Claude Plan token** (`CLAUDE_CODE_OAUTH_TOKEN` on Docker) for every Claude SDK agent without its own credential. When the runtime has both, the Plan token is used.
- The agent's own credential always wins over the runtime's, and only that one reaches Claude Code, so a Plan chat never falls back to API billing or the other way round.
- Saving the agent form checks an API key with Anthropic; a Plan token is checked on the first chat. A refused, expired, or over-limit credential shows one plain message in the chat.

## 1.6.0b1

**Claude SDK agents on the AI Workspace Runtime.** Add an agent of the new kind **Claude SDK** to chat with Claude Code's agent in Home Assistant, on the same runtime as Cursor. It is a separate kind from the cloud agent **Claude (Anthropic)**, which is unchanged. See [Claude SDK agents](../docs/claude-runtime.md).

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.6.0b1`) together with this release.** Claude SDK agents need it; Cursor agents keep working on 1.5.4, with the usual update hint.
- **It needs an Anthropic API key** (`sk-ant-api…`) from the [Claude Console](https://console.anthropic.com/settings/keys), on the agent or once on the runtime. Claude.ai plan tokens (Pro, Max, `claude setup-token`) are refused: Anthropic does not allow apps built on the Agent SDK to sign in with Claude.ai plans.
- Tools follow the Cursor rules: MCP only for normal users and voice satellites, workspace files in admin chats, and web search, page fetch, and the shell only with **Allow internet**. Claude Code settings, `CLAUDE.md`, skills, and hooks on the runtime's disk are never loaded.
- Images in the chat, Effort, and token use and cost work as on Cursor agents. Follow-up messages continue the same Claude session.

**Runtime**
- New `claude-agent-sdk` provider. `GET /api/health` reports `"claude"`.
- New App options **Anthropic API key** and **Claude model** (`ANTHROPIC_API_KEY`, `CLAUDE_MODEL` on Docker).
- The App is now named **AI Workspace Runtime** everywhere. The Compose service and container are called `ai-workspace-runtime`; Home Assistant still finds a container named `cursor-sdk`.

**Integration**
- Agent kind **Claude SDK** in the agent form and in YAML (`provider: claude`, `claude_api_key`). Saving checks the key with Anthropic.
- Runtime messages say "AI Workspace Runtime" instead of "Cursor Runtime".

## 1.5.4

Everything from 1.5.4b1 to 1.5.4b3. Nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.4`) together with this release.** The main fix is in the runtime. The chat shows a hint when the runtime is older than 1.5.4.

**Runtime**
- Cursor chats no longer lose all their tools after a while until the App is restarted. An MCP server that keeps its event stream open (such as a Cursor Worker) held one of the runtime's few proxy threads for every new agent, forever. After about six agents (roughly 20 minutes of chatting) no MCP call got through anymore, for every server.
  - The proxy no longer opens a server's standing event stream (GET). It answers "not offered" (405), which MCP clients expect; requests and answers go over POST as before.
  - An answer sent as an event stream ends as soon as the JSON-RPC response is in, even when the server keeps the stream open. Nothing waits longer than five minutes in total.
  - Calls to MCP servers have their own pool of 32 threads, so a slow server cannot block the others or the runtime.

**Chat**
- When the Cursor Runtime moves, for example from the App to the beta App or to another Docker host, the next chat finds it again. Before, every chat failed with "could not sync this chat to the Cursor Runtime" until the integration was reloaded. When the new App still has to be paired, the chat says so.
- When a chat cannot reach the Runtime, the reason is shown in the header until a message gets through again, instead of as a red answer in the chat. The message is dimmed with a short "Not sent" note and goes back into the prompt; it is not saved, so sending again does not repeat it.
- Errors about one answer (for example a model or tool error) stay in the chat, next to the answer they belong to.

## 1.5.4b3

- When a Cursor chat cannot reach the Runtime (not found, refused token, still pairing, not answering), the reason is shown in the header instead of as a red answer in the chat. It stays there until a message gets through again.
- The message itself is dimmed with a short "Not sent" note and goes back into the prompt, so you can send it again with one tap. Because it never reached the agent, it is not saved in the chat, and sending again does not repeat it.
- Errors about one answer (for example a model or tool error) stay in the chat, next to the answer they belong to.

## 1.5.4b2

- When the Cursor Runtime moves, for example from the App to the beta App or to another Docker host, the next chat finds it again. Before, AI Workspace kept the old address as long as the Cursor agent looked available, and every chat failed with "could not sync this chat to the Cursor Runtime" until the integration was reloaded.
- When the new Runtime App still has to be paired, the chat says so ("Pairing with the AI Workspace Runtime app. Try again in a minute.") instead of asking you to check URL and token.

## 1.5.4b1

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.4b1`) together with this release.** The fix is in the runtime. The chat shows a hint when the runtime is older.

**Runtime**
- Cursor chats no longer lose all their tools after a while until the App is restarted. The cause was an MCP server that keeps its event stream open (such as a Cursor Worker): the runtime's MCP proxy held one of its few threads open for every new agent, forever. After about six agents (roughly 20 minutes of chatting, because a pause of two minutes opens a new agent) no MCP call got through anymore, for every server. The 1.5.2 watchdog did not catch this because the requests did reach the runtime.
  - The proxy no longer opens the standing event stream (GET) of a server. It answers "not offered" (405), which MCP clients expect, and all requests and answers go over POST as before.
  - An answer sent as an event stream ends as soon as the JSON-RPC response is in, even when the server keeps the stream open. Nothing waits longer than five minutes in total.
  - Calls to MCP servers have their own pool of 32 threads, so a slow server cannot block the others or the runtime.

## 1.5.3

Fixes HA-MCP connections that were found automatically but did not work ([#2](https://github.com/domdus/ha-ai-workspace/issues/2)). Nothing needs to be changed in your setup; the runtime from 1.5.2 keeps working.

**HA-MCP inside Home Assistant**
- Finding HA-MCP follows its own settings. With "Remote access via webhook" turned off, AI Workspace uses HA-MCP's direct address instead of the webhook. Before, it picked the webhook anyway, and every chat failed with "MCP response was empty".
- An empty answer no longer counts as a working MCP server. Home Assistant gives one for a webhook that is not switched on, so a saved connection that points there now moves to HA-MCP's direct address after Home Assistant starts.
- "Sign in with Home Assistant" works: AI Workspace prefers the direct address and signs in on the webhook as the chatting user. HA-MCP's legacy OAuth mode is never picked, because AI Workspace has no client id and secret for it.
- HA-MCP's own server port is used when it was changed from 9584.
- When HA-MCP still fails, the log line "MCP connection … skipped" says what to change in HA-MCP, for example "turn on Remote access via webhook" for an empty answer, or which authentication mode to pick for HTTP 401.

## 1.5.2

Everything from 1.5.2b1 to 1.5.2b3. Nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.2`) together with this release.** The runtime heals a stuck Cursor bridge and shortens long answers differently. The chat shows a hint when the runtime is older than 1.5.2.

**Runtime**
- When the Cursor bridge stops connecting to MCP servers, the runtime heals itself: a new agent that does not reach its MCP servers within 20 seconds gets a fresh bridge, and the message is sent once more ("Reconnecting tools..."). Before, every chat said the connection to Home Assistant was broken until the App was restarted. At most one restart a minute, and never while another chat is still running.
- After a reinstall, pairing restarts the App only once.
- The App's configuration no longer shows "Shorten MCP results" and "Change History". They were only fallbacks; the integration sends both settings with every chat. The integration removes the old values from the App's options by itself.

**Long Home Assistant answers**
- A JSON answer that is too long first shortens its longest texts, each marked as incomplete and named by its source (such as a notification or entity id), instead of cutting off the end of the whole answer. One huge notification no longer pushes repairs, updates and everything after it out of HA-MCP's system overview, and the agent gets valid JSON and can tell you which integration or device makes answers so large.
- When an answer still has to be cut at the end, the note tells the agent not to repeat the same call, but to ask for less or use a more specific tool.

**Agents and models**
- Every agent has a model list you can fill yourself: paste names separated by commas, semicolons or new lines. It replaces the provider's list in the agent form and in the chat's model picker, and sits in a folded "Model list" section below the model field.
- OpenAI-compatible and OpenRouter agents: saving checks the model with one tiny request and shows the gateway's own message when the key may not use that model. When the model was left at the default and the server lists its models, the form comes back with that list in the model dropdown.

**Chat**
- Hints that do not mean something is broken (such as an outdated runtime) moved from the banner to an orange icon at the start of the sidebar toolbar. The banner is for errors again.
- A chat deleted on another device says so when you come back to it or send in it, keeps its messages on screen, puts an unsent message back in the prompt, and the next message starts a new chat.
- The prompt stays one line while the text fits; longer prompts use the full width with the buttons below on the right. In HA Components it is HA's own multi-line field (up to 8 lines; Enter sends, Shift+Enter adds a line), and pasted images have their remove button again.
- The chat search uses the prompt's font size, and collapsing the sidebar has its own icon.

**Settings**
- Emptying Memory notes in Configure → System prompt removes all notes. Before, the old notes came back on save.
- The description of "Shorten long Home Assistant answers" says what it does, in every language.

## 1.5.2b3

- Runtime App: the "Shorten MCP results" and "Change History" fields are gone from the App's configuration. They were only fallbacks: the integration sends both settings with every chat, so they never decided anything and only confused. Set both in AI Workspace → Configure. The Docker runtime ignores the matching environment variables for the same reason. The integration removes the old values from the App's options by itself.

## 1.5.2b2

- Shorten long Home Assistant answers: a JSON answer that is too long now first shortens its longest texts, each marked as incomplete, instead of cutting off the end of the whole answer. One huge notification (a vacuum integration's was 139,000 characters) no longer pushes repairs, updates and everything after it out of HA-MCP's system overview, and the agent gets valid JSON. On a real home the overview went from 306,000 to 36,000 characters with every section kept. The same applies to API agents.
- A shortened value says where it came from (for example a notification's id and title, or an entity id), so the agent can tell you which integration or device makes answers so large.
- When an answer still has to be cut at the end, the note tells the agent not to repeat the same call, but to ask for less or use a more specific tool. Before, agents called the same overview again and reported it as failed.
- Configure: the description of "Shorten long Home Assistant answers" now says what it does: compact entity lists, shorten very long texts, cut at 100,000 characters.

## 1.5.2b1

- Runtime: when the Cursor bridge stops connecting to MCP servers, the runtime heals itself. A new agent with MCP servers connects to them as soon as its run starts; when nothing reaches the runtime's MCP proxy within 20 seconds, the run is cancelled, a fresh bridge starts, and the message is sent once more ("Reconnecting tools..."). Before, every chat answered that the connection to Home Assistant was broken until the App was restarted. A new agent that finishes sooner without reaching its MCP servers gets a fresh bridge for the next message. At most one restart a minute, and never while another chat is still running.
- Runtime App: after a reinstall, pairing restarts the App once. A reload of the integration during pairing (for example when the HA-MCP check saves a new address) no longer pairs a second time.
- Agents: every agent has a model list you can fill yourself. Paste names separated by commas, semicolons or new lines (or a JSON list, or a copied /models answer); it replaces the provider's list in the agent form and in the chat's model picker. It sits in a folded "Model list" section right below the model field.
- OpenAI-compatible and OpenRouter agents: saving checks the model with one tiny request. When the gateway does not allow the model for the key, the form shows the gateway's own message. When the model was left at the default and the server lists its models, the form comes back with that list in the model dropdown.
- Chat: hints that do not mean something is broken (such as an outdated Runtime) moved from the banner above the chat to an orange icon at the start of the sidebar toolbar; click it to read the hint. The banner is for errors again. The compact Assist overlay keeps the banner.
- Chat (Standard): a longer prompt uses the full width of the box, with the buttons below it on the right, instead of wrapping early beside the buttons. Short prompts stay one line.
- Chat: the chat search uses the same font size as the prompt, and collapsing the sidebar has its own icon.
- Chat: a chat deleted on another device no longer answers "Chat not found." to every new message. Coming back to the open chat, or sending in it, now says it was deleted, keeps its messages on screen, puts an unsent message back in the prompt, and the next message starts a new chat.
- HA Components: the prompt is a multi-line text field (HA's own) that grows up to 8 lines. It stays one line with the buttons beside the text; once the text needs more room, the buttons move below it on the right. Enter sends, Shift+Enter adds a line.
- HA Components: pasted or attached images have a remove button again (it was cut off), and the previews have rounded corners.
- Configure → System prompt: emptying Memory notes now removes all notes. Before, the emptied field brought the old notes back on save.

## 1.5.1

Everything from 1.5.1b1 to 1.5.1b4. A patch release with fixes; nothing needs to be changed in your setup.

- **Update the runtime (App or Docker image `ghcr.io/domdus/ha-ai-workspace-runtime:1.5.1`) together with this release.** The runtime code is the same as 1.5.0, but the App's settings changed: a fresh install can be saved again. The chat warns when the runtime is older than 1.5.1.

**Change History**
- Helpers and dashboards are rolled back through Home Assistant's own websocket commands, signed in as you, the same calls the helper and dashboard editors make. Home Assistant checks your permissions, validates the item, and stores it. AI Workspace no longer reaches into Home Assistant's internal storage.
- The snapshot of a helper before a change is read the same way, with the chatting user's own login.
- Rollback is for administrators only, for every kind of change.

**Runtime App and MCP**
- The Runtime App is found when it was installed or started after Home Assistant. Since Home Assistant 2026.11 the add-on details are only loaded at startup, so a newly installed App stayed invisible until the next restart. The same applies to an HA-MCP App.
- Home Assistant tools work from the Runtime App when their saved address is 127.0.0.1. Inside the App, 127.0.0.1 is the App itself, so every call was refused. Addresses on Home Assistant's own port (built-in MCP, HA-MCP webhook) and HA-MCP running inside Home Assistant (port 9584) now go to http://homeassistant.
- An HA-MCP connection that points at Home Assistant's built-in MCP server (/api/mcp) or at an address that does not answer moves to a working HA-MCP by itself after Home Assistant has started. The new address is saved and named in the log, without its secret path. Custom and built-in connections are never changed.

**App settings**
- The empty default for the Home Assistant URL was rejected by the Supervisor ("expected a URL"); the field is now optional and the App uses http://homeassistant:8123 when it is empty.
- Shorten MCP results and Change History are no longer preset in the App; the runtime keeps them on by default and the integration's own setting still wins.
- Every option has a name and description, in English and German.

**Other**
- The check whether Home Assistant runs in a container no longer touches the disk from the event loop.

## 1.5.1b4

- The runtime has no changes in this release. A 1.5.0 runtime keeps working without an update notice.
- HA-MCP: a connection of the kind HA-MCP that points at Home Assistant's built-in MCP server (/api/mcp) or at an address that does not answer moves to a working HA-MCP by itself. The check runs once Home Assistant has started, so HA-MCP inside Home Assistant (HA-MCP Server) is up by then; it tries again after 30 seconds and 2 minutes. The new address is saved to the connection and named in the log, without its secret path. Custom and built-in connections are never changed, and nothing changes when no working HA-MCP is found.
- HA-MCP: an HA-MCP App installed after Home Assistant started is found too (same Home Assistant 2026.11 change as in 1.5.1b3).
- Cursor: Home Assistant tools work from the Runtime App when their saved address is 127.0.0.1. Inside the App, 127.0.0.1 is the App itself, so every call was refused and the agent said the connection to Home Assistant was not usable. Addresses on Home Assistant's own port (built-in MCP, HA-MCP webhook) and HA-MCP running inside Home Assistant (port 9584) now go to http://homeassistant. A runtime on the same host network keeps 127.0.0.1.

## 1.5.1b3

- The runtime has no changes in this release. A 1.5.0 runtime keeps working without an update notice.
- Cursor: the Runtime App is found when it was installed or started after Home Assistant. Since Home Assistant 2026.11 the add-on details are only loaded at startup, so a newly installed App stayed invisible until the next restart.

## 1.5.1b2

- The runtime code has no changes in this release; only the App's settings page changed. A 1.5.0 runtime keeps working without an update notice.
- App settings: a fresh install can be saved again. The empty default for the Home Assistant URL was rejected by the Supervisor ("expected a URL"); the field is now optional and the App uses http://homeassistant:8123 when it is empty.
- App settings: Shorten MCP results and Change History are no longer preset in the App. Both stay available under "Show unused optional configuration options". The runtime keeps them on by default, the same as the Docker image, and the integration's own setting still wins.
- App settings: every option has a name and description now, in English and German.

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
