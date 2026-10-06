# AI Workspace Runtime

This app runs the **Cursor agent in your house**. Home Assistant OS cannot install `cursor-sdk` itself (musllinux). The app is Debian, so the official glibc wheel works. It talks to your existing LAN MCP servers (ha-mcp, and others you paste).

The chat UI is the **AI Workspace** HACS integration, not this app page.

## Install (Home Assistant OS)

1. **Settings → Apps → Install app → ⋮ → Repositories**. Add this GitHub repository.
2. Install **AI Workspace Runtime**. The first install builds a container and can take several minutes.
3. In the app **Configuration**:
   - Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) (a Cursor user API key, not a Home Assistant token)
   - Optional extra MCP servers (`mcp_config`). Home Assistant MCP is set on the HACS integration and sent on each chat.
4. Start the app.
5. Install **AI Workspace** from HACS (Integration), restart Home Assistant, then **Settings → Devices & services → Add integration → AI Workspace**. It should find this app on its own.
6. Optional UI toggles live on the **integration**, not the app: **Settings → Devices & services → AI Workspace → Configure** (`Show AI Workspace in the sidebar`, `Show floating AI button on every page`).

Do not publish MCP to the internet. The agent runs here and calls MCP on the LAN.

## Extra MCP servers

Optional `mcp_config` is a JSON object in Cursor `mcp.json` shape if you also use GitHub, Synology, or other MCP servers:

```json
{
  "mcpServers": {
    "github": { "url": "http://github-mcp:8080/mcp" }
  }
}
```

That is merged with the Home Assistant MCP URL from the HACS integration.
