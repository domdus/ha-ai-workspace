# Troubleshooting

- **"Runtime token is missing or wrong."** The token on the Cursor agent and on the runtime differ. On Docker, copy `RUNTIME_TOKEN` into **Cursor agent → Runtime token**. On the Home Assistant OS app, the integration pairs by itself as long as you never filled in Runtime token on the agent form; if you typed one there, use the same value as the app’s **Runtime token** option.
- **"Set RUNTIME_TOKEN on the runtime and the same token on AI Workspace."** The runtime has no token and is listening beyond this machine’s loopback. Either set `HOST: "127.0.0.1"` (typical host network), or set `RUNTIME_TOKEN` and put the same value in **Cursor agent → Runtime token**.
- **The agent invents answers instead of checking.** Turn on **Always check the house first** under **Configure → Cost and tokens**. It makes the model call a tool first for every message that is not a greeting or thanks. Some providers and small local models do not honor a forced tool call. Use a model with reliable tool calling (for example GPT-4.1 mini, Claude Sonnet, Gemini 2.5, or Composer) and check that the MCP connection’s device is enabled. See [Always check the house first](settings.md#always-check-the-house-first).
- **Built-in MCP Server tools are missing in Assist.** That server needs a login, and a voice satellite has none. Set a long-lived token on the connection (see [Privacy](privacy.md)).
- **OpenAI rejects the tool name.** Names over 64 characters are shortened. Two MCP connections that share a tool get a short prefix. Disable a connection’s device to drop its tools. Turning off **All LLM APIs** is not the same as disabling that device; the built-in MCP tools are omitted only while **MCP Server** is unloaded.
- **OpenAI TTS error about exhausted credit.** The OpenAI account is out of credit. That is separate from MCP tool names.
- **The microphone is greyed out.** Open Home Assistant over https:// (Nabu Casa or a reverse proxy) or on localhost.
- **Home Assistant will not start after the assistant changed an automation, script, or scene.** Stop Home Assistant and merge the matching file from `config/ai_workspace/changes/` into `automations.yaml`, `scripts.yaml`, or `scenes.yaml` (same id). Steps: [If Home Assistant will not start](mcp.md#if-home-assistant-will-not-start).

## More detail in the logs

Add this to `configuration.yaml` and restart, then check **Settings → System → Logs**:

```yaml
logger:
  logs:
    custom_components.ai_workspace: debug
```

## Remove it

1. **Settings → Devices & services → AI Workspace → ⋮ → Delete.** That removes all connections, agents, and their Assist pipelines.
2. **HACS → AI Workspace → Remove**, then restart.
3. Runtime: remove the **app**, or run `docker compose down -v` in the runtime compose folder. `-v` also deletes the `ai-workspace-data` volume with the Cursor state; leave it out to keep that. Use `docker rm -f cursor-sdk` if an old container remains.
4. Optional: delete `config/ai_workspace/`. Removing the integration keeps this folder on purpose, so a reinstall still has your chats. It holds the chat history, Change History snapshots, usage and cost records, and the workspace folder.
