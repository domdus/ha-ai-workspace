# AI Workspace Runtime

This app runs the **Cursor agent in your house**. Home Assistant OS cannot install `cursor-sdk` itself (musllinux). The app is Debian, so the official glibc wheel works. MCP comes from the AI Workspace integration.

The chat UI is the **AI Workspace** HACS integration, not this app page.

## Install (Home Assistant OS)

1. **Settings → Apps → Install app → ⋮ → Repositories**. Add this GitHub repository.
2. Install **AI Workspace Runtime**. The first install builds a container and can take several minutes.
3. In the app **Configuration**, paste the Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) (a Cursor user API key, not a Home Assistant token). Model can stay `composer-2.5`. MCP is set on the HACS integration, not here.
4. Start the app.
5. Install **AI Workspace** from HACS (Integration), restart Home Assistant, then **Settings → Devices & services → Add integration → AI Workspace**. It should find this app on its own.
6. Optional UI toggles live on the **integration**, not the app: **Settings → Devices & services → AI Workspace → Configure** (`Show AI Workspace in the sidebar`, `Show floating AI button on every page`).

## Home Assistant Container (Docker)

See [`docker-compose.runtime.yml`](../docker-compose.runtime.yml) in the repo root.

- Pull: `docker compose -f docker-compose.runtime.yml up -d` → `ghcr.io/domdus/ha-ai-workspace-runtime:latest`
- Build from this checkout: `docker compose -f docker-compose.runtime.yml up -d --build`

After the first GitHub Actions publish, set the GHCR package to **Public**.

Do not publish MCP to the internet. The agent runs here and calls MCP on the LAN.

## Extra MCP servers

Home Assistant MCP and extra MCP connections are configured on the **AI Workspace** integration, then sent with each chat. The Docker Runtime can still mount an `mcp.json` or set `MCP_URL` if you need a file fallback. The app form does not ask for MCP.
