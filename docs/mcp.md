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

This is a **log** of configuration writes the agent actually made (the last 30). Open it from the sidebar. **Rollback** puts back the snapshot Change History took before that write. If there is no snapshot and HA-MCP is connected, **Ask to restore** tells the current chat to undo the change with whatever backup or config tools it actually has.

Turn **Change History** off if you do not want snapshots. The agent can still use Home Assistant; only the log stops.

## Built-in MCP Server vs the connection row

The built-in Home Assistant MCP Server needs **All LLM APIs** and the **MCP Server** integration loaded. Turning those off hides its tools even if the AI Workspace connection row is still there. That is not the same as disabling the AI Workspace device.
