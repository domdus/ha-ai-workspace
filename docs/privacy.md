# Privacy

## What leaves the house

Your messages, attachments, the system prompt, the page you are on, and every MCP tool result go to the AI provider you picked (or to Cursor through the runtime). Only Ollama or another local server keeps everything at home.

## What stays local

Chat history is stored in `config/ai_workspace/ai-workspace.sqlite`. Change History keeps a log of the last 30 recorded configuration writes there. Usage rows (tokens and estimated cost, not message text) live in the same database.

Change History keeps a before-image of each recorded write and can restore it with **Rollback**, with or without HA-MCP. **Ask to restore** still appears when HA-MCP is connected (or when that snapshot is missing), so the chat can use HA-MCP backups or dashboard tools.

API keys live in Home Assistant’s config entries, like any other integration.

## Who can use it

Only admins by default. The sidebar panel is always admin-only.

**Allow normal users** (off by default): people who are not admins get the floating chat. They only get the built-in **Home Assistant MCP Server**, using their own login, and never the admin’s MCP connections or the config catalog. What they can see and do is then whatever Home Assistant exposes to them through Assist. A Cursor agent in their chat can only use MCP tools: no shell, no files in the runtime workspace, no web search. The Usage page shows them their own usage only.

**Only turn this on if you trust everyone with a login to chat with an AI that can act on the house.**

## Voice satellites

Assist from a satellite has no signed-in person, so it uses the tools the admin configured. The built-in MCP Server needs a login, so set a long-lived access token in that connection’s **MCP token** when satellites should reach it. HA-MCP and Vibecode bring their own credentials.

Anyone near a satellite can talk to it, so a Cursor agent answering a satellite gets MCP tools only, the same as for normal users. Shell and file tools are for signed-in admins.

## Runtime

Keep port 8090 and your MCP servers off the internet. The Cursor runtime only accepts HTTP MCP servers from the integration, and it rejects every request without the runtime token unless it listens on loopback. Without a token it also only answers requests addressed to `127.0.0.1` or `localhost`, so a web page cannot reach it through a DNS trick. Home Assistant accepts the runtime’s callbacks (Change History, MCP notes) without a token only from the same machine.

Chat replies never load images or other media from other sites. A remote image could send chat text to that site, so it is shown as a link instead.
