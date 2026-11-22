# MCP and Change History

![Change History](history.png)

What the agent can do depends on the MCP server you connect. AI Workspace can use more than one connection at a time. Disable a connection’s device to drop its tools without deleting it.

See [How it is organized](settings.md#how-it-is-organized) for connections vs agents.

## How tools reach Home Assistant

Cloud agents (OpenAI, Claude, and the others) call MCP from inside Home Assistant.

Cursor is different: the model runs in the AI Workspace Runtime next to Home Assistant, and tools go through that runtime. You do not point Cursor at your MCP URL yourself; AI Workspace does that when you chat.

## HA-MCP inside Home Assistant

When the HA-MCP integration runs inside Home Assistant, AI Workspace finds it by itself and follows its settings (HA-MCP Server → Configure):

| HA-MCP setting | Address AI Workspace uses |
| --- | --- |
| Remote access via webhook **on**, authentication **Secret webhook URL** | The webhook, then HA-MCP's direct address |
| Remote access via webhook **off** (local only) | HA-MCP's direct address (port 9584 by default) |
| Authentication **Sign in with Home Assistant** | The direct address first. On the webhook, AI Workspace signs in as the chatting user, and HA-MCP only lets in administrators. |
| Authentication **OAuth (legacy)** | Only the direct address. AI Workspace cannot use the legacy client id and secret. |

A saved HA-MCP connection that no longer answers moves to a working address after Home Assistant starts. If HA-MCP still fails, the log line "MCP connection … skipped" says what to change in HA-MCP.

## Shorten long Home Assistant answers

On by default, for cloud agents and Cursor.

A whole-home entity list or a big search is a lot of JSON. Sending all of it to the model burns tokens and can make replies slower. With this on, large **entity listings** are condensed **before the model reads them**:

- A huge listing becomes entity ids grouped by area. The model can ask again for one area or one entity.
- A shorter listing keeps each entity’s state and drops bulky attributes.

Everything else reaches the model exactly as Home Assistant or the MCP server sent it: guides, dashboards, automations, scripts, and single entities. That matters because the model may write those values back, and HA-MCP puts the key it needs for dashboard writes in its guide.

A result over 100,000 characters first has its longest texts shortened, for example one huge notification inside HA-MCP's system overview. Every other part stays, the JSON stays valid, and each shortened text says where it came from (such as the notification or entity id), so the agent can tell you which integration or device makes answers that large. Only when that is not enough is the result cut at the end, with a note that it is incomplete, must not be written back, and should be asked for in smaller parts.

The setting lives in AI Workspace → Configure. The integration sends it to the AI Workspace Runtime with every chat, so the Runtime App and the Docker image have no setting of their own for it.

Turn this off if you want every attribute of a large listing in one shot and you accept the extra tokens.

## Questions and approvals from MCP tools

Some MCP servers ask you something in the middle of a tool call. An example is the agent-worker, which asks before it runs a command on another server. MCP calls this **elicitation**. Runtime agents (Cursor and Claude SDK) support it: the AI Workspace Runtime tells every MCP server it connects to that it can ask the user (`capabilities.elicitation`, form mode).

- An `elicitation/create` request never reaches the model. It shows up in the chat as a card with the server's message, the exact command and target for worker approvals, and **Allow** / **Deny**. Closing the card (×) answers *cancel*.
- **Only your click answers it.** Chat text, the model's output and tool calls cannot. The Runtime drops any answer that does not come from Home Assistant with the card's own key.
- **Language:** the card's buttons and headings follow your Home Assistant language. The server's own text (the question, field titles) comes from the server: every MCP request carries `Accept-Language` with Home Assistant's language (for example `de, en;q=0.5`), from cloud agents and from the Runtime's MCP proxy alike, so a server can answer in that language.
- Open cards stay when you close and reopen the chat or the app. Several can be open at once.
- A card waits for **Approval wait** (AI Workspace → Configure, default 10 minutes, 1 to 60). Then the server gets *cancel*. Stopping the turn cancels its open questions too.
- **Fallback for agent-worker jobs:** when a job result says `input_required` (or `needs_approval`) with an approval that has no open MCP request, the same card appears. Allow or Deny goes straight to the worker (`POST /jobs/<id>/approve` with `{"approve": true|false}`). Closing that card only hides it; the job keeps waiting until the worker's own timeout.

Cloud agents call MCP from inside Home Assistant and do not offer elicitation yet. Servers then fall back to their own way, for example the worker's `agent_approve` tool.

## Long tool calls: progress, timeout, stop

This follows the MCP specification (2025-11-25) for every MCP connection, for cloud agents (Home Assistant calls the server) and Runtime agents (the Runtime's MCP proxy calls it for Cursor, Claude and Codex).

- **Progress:** every `tools/call` carries `_meta.progressToken`. Each `notifications/progress` the server sends shows live as the tool step's status in the chat (its `message`, else the share done).
- **Tool call timeout:** per connection (Settings → AI Workspace → the connection → Reconfigure), 120 seconds by default, 10 to 3600. It counts from the last progress notification, so a call that keeps reporting progress can run longer. When it runs out, the server gets `notifications/cancelled` and the agent gets an error.
- **Stop:** stopping the reply sends `notifications/cancelled` for every call still open.
- **Conversation id:** `tools/call` carries the chat's id in `_meta` as `io.github.domdus/conversation_id`, so a server (for example the agent-worker) can link its jobs to the chat.
- An elicitation question during a long call still reaches the chat (Runtime agents); the time you take to answer does not count against the timeout.
- Engine limits: Codex and Claude Code do not see progress through the proxy, so the Runtime gives them a limit just above the longest timeout (3660 s: Codex `tool_timeout_sec`, Claude Code `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, unless you set it yourself) and the proxy enforces each connection's own. Cursor has no setting for it.

## Change History

On by default, for cloud agents and Cursor.

This is a **log** of configuration writes the agent actually made (the last 30). Open it from the sidebar. Each row has one way back. **Rollback** puts back the snapshot Change History took before that write — that works without HA-MCP and without the agent. A row with no snapshot, such as something the agent created, shows **Undo with agent** instead: it sends the change details to the chat, and the agent undoes it with the tools it actually has (for example deletes what it created, or uses an HA-MCP backup from before the change). If Rollback fails, the error offers Undo with agent too. Rollback and Undo with agent are for administrators. Rollback goes through Home Assistant's own APIs signed in as you, the same calls the automation, helper, and dashboard editors make, so Home Assistant checks and stores the item itself.

**Rollback for** (default 7 days, Configure or `change_history_ttl_days`) hides Rollback and Undo with agent on older rows. The log stays. An old dashboard snapshot would otherwise overwrite later cards and entities. Use 1 for about a day.

### If Home Assistant will not start

A bad automation, script, or scene can stop Home Assistant from booting, so the sidebar **Rollback** is gone. Change History also writes a YAML copy for those three kinds:

`config/ai_workspace/changes/{id}.yaml`

The file starts with a comment: when it was taken, which chat, and which Home Assistant file to merge into (`automations.yaml`, `scripts.yaml`, or `scenes.yaml`).

1. Stop Home Assistant.
2. Open `config/ai_workspace/changes/` (the `config` folder next to `configuration.yaml`).
3. Pick the snapshot that matches the change (newest files are usually last). Read the comment at the top.
4. In that Home Assistant YAML file, replace the item with the **same id**. Automations and scenes are a list of documents; scripts are a map keyed by id. Do not paste the comment lines into the live file.
5. Start Home Assistant. If it still will not start, the YAML is invalid: check quotes and indentation, or restore from a Home Assistant backup.

Dashboards, helpers, and entity-registry edits are in `config/ai_workspace/ai-workspace.sqlite`, not in `changes/`. Those rarely block startup. Use **Rollback** in the UI once Home Assistant is up, or restore a Home Assistant backup.

The folder keeps files for the last 30 recorded writes. Hiding Rollback after a few days does not delete them. Several YAML writes in one agent reply share one `{id}.yaml`; the file is the last of those writes.

Turn **Change History** off if you do not want snapshots. The agent can still use Home Assistant; only the log stops.

## Built-in MCP Server vs the connection row

The built-in Home Assistant MCP Server needs **All LLM APIs** and the **MCP Server** integration loaded. Turning those off hides its tools even if the AI Workspace connection row is still there. That is not the same as disabling the AI Workspace device.
