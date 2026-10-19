# Privacy

## What leaves the house

Your messages, attachments, the system prompt, the page you are on, and every MCP tool result go to the AI provider you picked (or to Cursor through the runtime). Only Ollama or another local server keeps everything at home.

## What stays local

Chat history is stored in `config/ai_workspace/ai-workspace.sqlite`. Change History keeps a log of the last 30 recorded configuration writes there. Usage rows (tokens and estimated cost, not message text) live in the same database.

Undo for HA-MCP writes belongs to HA-MCP’s own edit backups. **Ask to restore** in Change History asks the current chat to list and restore them.

API keys live in Home Assistant’s config entries, like any other integration.

## Who can use it

Only admins by default. The sidebar panel is always admin-only.

**Allow normal users** (off by default): people who are not admins get the floating chat. They only get the built-in **Home Assistant MCP Server**, using their own login, and never the admin’s MCP connections or the config catalog. What they can see and do is then whatever Home Assistant exposes to them through Assist.

**Only turn this on if you trust everyone with a login to chat with an AI that can act on the house.**

## Voice satellites

Assist from a satellite has no signed-in person, so it uses the tools the admin configured. The built-in MCP Server needs a login, so set a long-lived access token in that connection’s **MCP token** when satellites should reach it. HA-MCP and Vibecode bring their own credentials.

## Runtime

Keep port 8090 and your MCP servers off the internet. The Cursor runtime only accepts HTTP MCP servers from the integration, and it rejects every request without the runtime token unless it listens on loopback.
