# MCP and Change History

What the agent can do depends on the MCP server you connect. AI Workspace can use more than one connection at a time. Disable a connection’s device to drop its tools without deleting it.

See [How it is organized](settings.md#how-it-is-organized) for connections vs agents.

## How tools reach Home Assistant

Cloud agents (OpenAI, Claude, and the others) call MCP from inside Home Assistant.

Cursor is different: the model runs in the Cursor runtime next to Home Assistant, and tools go through that runtime. You do not point Cursor at your MCP URL yourself; AI Workspace does that when you chat.

## Shorten long Home Assistant answers

On by default, for cloud agents and Cursor.

A whole-home entity list or a big search is a lot of JSON. Sending all of it to the model burns tokens and can make replies slower. With this on, large results are shortened **before the model reads them**:

- A huge entity list becomes ids grouped by area. The model can ask again for one area or one entity.
- A still-long list keeps each entity’s state and drops bulky attributes.
- One entity, one room, or one automation still arrives whole.
- The model always receives valid JSON. Nothing is cut off in the middle of an object.

Turn it off if you want every attribute of a large list in one shot and you accept the extra tokens.

## Change History

On by default, for cloud agents and Cursor.

This is a **log** of configuration writes the agent actually made (the last 30). Open it from the sidebar. **Rollback** puts back the snapshot Change History took before that write — that works without HA-MCP. When HA-MCP is connected, **Ask to restore** stays available too, so the chat can use HA-MCP edit backups (domain `dashboard`, backup from before the change, not the newest file). If there is no snapshot, Ask to restore still asks the chat to undo with the tools it actually has.

**Rollback for** (default 7 days, Configure or `change_history_ttl_days`) hides Rollback and Ask to restore on older rows. The log stays. An old dashboard snapshot would otherwise overwrite later cards and entities. Use 1 for about a day.

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
