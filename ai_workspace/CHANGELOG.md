# Changelog

## 1.0.4

- Stop overlay session import from crashing Home Assistant with a SQLite error
- Cursor named-model failures no longer tell you to recreate the Runtime container; set Model to auto in the integration if the API key only allows Auto

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
