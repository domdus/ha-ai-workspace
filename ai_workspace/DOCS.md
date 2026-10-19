# AI Workspace Runtime

This app runs the **Cursor agent in your house**. Home Assistant OS cannot install `cursor-sdk` itself (musllinux). The app is Debian, so the official glibc wheel works. MCP comes from the AI Workspace integration.

The chat UI is the **AI Workspace** HACS integration, not this app page.

## Install (Home Assistant OS)

1. **Settings → Apps → Install app → ⋮ → Repositories**. Add this GitHub repository.
2. Install **AI Workspace Runtime**.
3. In the app **Configuration**, paste the Cursor API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) (a Cursor user API key, not a Home Assistant token). Model can stay `composer-2.5`. MCP is set on the HACS integration, not here.
4. Start the app.
5. Install **AI Workspace** from HACS (Integration), restart Home Assistant, then **Settings → Devices & services → Add integration → AI Workspace**. It finds this app on its own.
6. Optional UI toggles live on the **integration**, not the app: **Settings → Devices & services → AI Workspace → Configure**.

### Runtime token

The integration and this app share a token. Every chat request must carry it. On Home Assistant OS the integration creates the token, writes it into this app's **Runtime token** option, and restarts the app once. Leave the field alone unless you pair by hand.

## Home Assistant Container (Docker)

See [`docker-compose.runtime.yml`](../docker-compose.runtime.yml) in the repo root.

- Pull: `docker compose -f docker-compose.runtime.yml up -d` → `ghcr.io/domdus/ha-ai-workspace-runtime:latest`
- Build from this checkout: `docker compose -f docker-compose.runtime.yml up -d --build`

The compose file uses host networking and binds to `127.0.0.1`, so only this machine reaches port 8090. On loopback the token is optional.

If Home Assistant runs in another container on a bridge network, set `HOST: "0.0.0.0"` and a `RUNTIME_TOKEN` (for example `openssl rand -hex 32`). Put the same value in **Cursor agent → Runtime token**. Without a token, a runtime that listens beyond loopback refuses every chat.

Do not publish port 8090 or MCP to the internet. The agent runs here and calls MCP on the LAN.

Composer’s cwd is `WORKSPACE_DIR` (default `/data/workspace`). Bind a host directory only if you want extra files on disk; do not mount Home Assistant `/config`. House edits stay on MCP. Example:

```yaml
    environment:
      WORKSPACE_DIR: /workspace
    volumes:
      - ai-workspace-data:/data
      - /path/on/host:/workspace
```

The runtime seeds `AGENTS.md` and `.cursor/rules/home-assistant.mdc` only when those files are missing. Optional `GIT_REPO` plus `GIT_SSH_KEY` (mounted key file) clones into that folder on first start; credentials stay on the container, not the integration. The Home Assistant OS app cannot bind an arbitrary host path.

## Extra MCP servers

Home Assistant MCP and extra MCP connections are configured on the **AI Workspace** integration, then sent with each chat. Only HTTP MCP servers are accepted from the integration. The Docker Runtime can still mount an `mcp.json` or set `MCP_URL` if you need a file fallback (that is also the only place for stdio servers). The app form does not ask for MCP.
