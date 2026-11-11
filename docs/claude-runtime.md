# Claude SDK agents on the AI Workspace Runtime

The **AI Workspace Runtime** (the Home Assistant App, or the Compose service `ai-workspace-runtime`) that runs Cursor also runs **Claude SDK** agents. They use Anthropic's [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/), which drives the Claude Code agent inside the runtime. Home Assistant talks to it the same way as to Cursor: Runtime address, Runtime password, and MCP through the runtime.

The cloud agent **Claude (Anthropic)** is a different thing and is unchanged: it calls Anthropic's API from inside Home Assistant and needs no runtime.

## What you need

An **Anthropic API key** (`sk-ant-api…`) from [Claude Console → API keys](https://console.anthropic.com/settings/keys). Usage is billed as API credits on that account.

Put it in one of two places:

- **On the agent** (Home Assistant → AI Workspace → Add agent → **Claude SDK** → **Anthropic API key**). Each agent can use its own key.
- **On the runtime**, for every Claude SDK agent without its own key: the App option **Anthropic API key**, or `ANTHROPIC_API_KEY` in Docker.

The key on the agent wins. Saving the agent form checks the key with Anthropic.

### Claude.ai subscriptions (Pro, Max, Team) do not work

A Claude.ai plan token (`sk-ant-oat…`, made with `claude setup-token`) is refused, on the form and on the runtime. Anthropic does not allow apps built on the Agent SDK to sign in with Claude.ai or to use a subscription's limits; it asks such apps to use API keys ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). AI Workspace therefore has no Claude.ai sign-in and does not store plan tokens.

To use a Claude subscription, use Claude Code or the Claude apps themselves.

## Home Assistant

1. Add an agent → **Claude SDK** (not “Claude (Anthropic)”).
2. Runtime address and password: the same as for Cursor agents. Leave the address empty when the form says **Runtime found**.
3. **Anthropic API key**: see above.
4. **Model**: an Anthropic model id such as `claude-sonnet-5-5`. Empty uses the runtime's **Claude model** option, or Claude Sonnet.
5. **Effort**: Fast, High, and High fast map to Claude Code's low, high, and medium effort. Default lets Claude decide.

The runtime must be **1.6.0b1** or newer. An older runtime shows an update hint on Claude SDK agents only; Cursor agents keep working.

## Tools

The same rules as for Cursor agents:

- **Normal users and voice satellites:** only the MCP tools for your house. No files, no shell, no web.
- **Admin chats:** also read and write files in the runtime's workspace folder.
- **Admin chats with Allow internet:** also web search, page fetch, and the shell. Without Allow internet the shell is removed too, so `curl` or a script cannot reach the web.

Claude SDK agents never load Claude Code settings, `CLAUDE.md`, skills, hooks, or MCP servers from the runtime's disk; each turn gets only what Home Assistant sends. Subagents are off.

## Runtime options

| App option | Docker variable | Meaning |
|---|---|---|
| Anthropic API key | `ANTHROPIC_API_KEY` | Key for Claude SDK agents without their own key. |
| Claude model | `CLAUDE_MODEL` | Default model when the agent's model is empty. |

Claude Code keeps chat state in `claude-config` inside the runtime's data folder (`/data`), so a chat can resume after the runtime restarts.
