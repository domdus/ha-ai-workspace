# Changelog

## 1.0.6

- Overlay shortcut is the robot icon only
- MCP type lists the servers this Home Assistant can reach, and still allows a custom MCP URL

## 1.0.5

- Pass composer-2.5 as Cursor `ModelSelection` with Fast on (same default as the IDE picker and `model="composer-2.5"`)
- Retry once when Cursor returns an empty run; do not suggest model ids that are not in the catalog
- Cursor Runtime chats include the HA UI link rules on every message so automation names stay tappable
- Assistant replies link automations, entities, helpers, and devices to their Home Assistant edit pages even when the model lists plain names

## 1.0.4

- Stop overlay session import from crashing Home Assistant with a SQLite error
- Cursor named-model failures report the SDK model id; check Runtime logs for `cursor model=`
- README: integration Model is JSON `model` → Cursor `AgentOptions.model`, same as `CURSOR_MODEL`

## 1.0.3

- Keep a single New Chat control in the overlay header, next to close

## 1.0.2

- Overlay sidebar starts a new chat when the remembered session is gone, instead of "Chat not found"
- New Chat control in the overlay drawer
- Overlay chat includes the current dashboard path, name, and visible entities

## 1.0.1

- Register the sidebar panel before loading chat JS so a hard refresh of `/ai-workspace` is not a blank page

## 1.0.0

- HACS integration and Cursor Runtime sidecar for Home Assistant Container and OS
- Cloud API (OpenAI / Claude) or Cursor SDK chat, with MCP to the house
- Robot badge branding, pinned chats, and a copy-paste Runtime compose file

## 0.3.0

- Public Supervisor add-on for the local Cursor agent
- MCP URL option for LAN ha-mcp
- Health check on `/api/health`
