# Claude SDK agents on the AI Workspace Runtime

The **AI Workspace Runtime** (the Home Assistant App, or the Compose service `ai-workspace-runtime`) that runs Cursor also runs **Claude SDK** agents. They use Anthropic's [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/), which drives the Claude Code agent inside the runtime. Home Assistant talks to it the same way as to Cursor: Runtime address, Runtime password, and MCP through the runtime.

Both are the same **Claude (Anthropic)** agent in Home Assistant. With **Use Claude SDK (runtime) (experimental)** under **Advanced** off, it calls Anthropic's API from inside Home Assistant and needs no runtime. With it on, it is a Claude SDK agent on the runtime.

## What you need

One of two Claude credentials:

- **Claude Plan token** (`sk-ant-oat…`): uses your Claude subscription (Pro, Max). On any computer with [Claude Code](https://code.claude.com), run `claude setup-token`, approve in the browser, and copy the token it prints. It lasts one year; make a new one when Claude SDK chats start failing with a sign-in error.
- **Anthropic API key** (`sk-ant-api…`): billed as API credits. From [Claude Console → API keys](https://console.anthropic.com/settings/keys).

Put it in one of two places:

- **On the agent** (Home Assistant → AI Workspace → Add agent → **Claude (Anthropic)** → **Advanced** → **Use Claude SDK (runtime) (experimental)** → OK → **Claude Plan token or Anthropic API key**). Each agent can use its own.
- **On the runtime**, for every Claude SDK agent without its own: the App options **Claude Plan token** or **Anthropic API key**, or `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` on Docker. When both are set, the Plan token is used.

The credential on the agent wins. The prefix decides how Claude Code signs in, and only that one credential reaches it, so a Plan chat never falls back to API billing or the other way round. Saving the agent form checks an API key with Anthropic; a Plan token is checked on the first chat.

You can also let the runtime do it (experimental, runtime 1.6.0b7 or newer): see [Sign in with Claude](#sign-in-with-claude). Or run `claude setup-token` yourself on any computer with Claude Code and paste the token.

Anthropic's terms for the Agent SDK say third-party products should use API keys and not offer Claude.ai sign-in ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). Whether your own Plan token on your own runtime is fine for you is your decision.

## Home Assistant

1. Add an agent → **Claude (Anthropic)**.
2. Open **Advanced**, turn on **Use Claude SDK (runtime) (experimental)**, and press **OK**. Nothing is saved yet: the form comes back with the **Claude SDK (runtime)** section instead of the API key field.
3. Runtime address and password: the same as for Cursor agents. Leave the address empty when the form says **Runtime found**.
4. **Claude Plan token or Anthropic API key**: see above.
5. **Model**: an Anthropic model id such as `claude-sonnet-5-5`. Empty uses the runtime's **Claude model** option, or Claude Sonnet.
6. **Effort**: Fast, High, and High fast map to Claude Code's low, high, and medium effort. Default lets Claude decide.

Turning the switch off again makes it a cloud Claude agent, which needs an Anthropic API key. Effort works for both. Claude SDK agents from 1.6.0b1 and b2 become Claude (Anthropic) agents with the switch on when the integration loads; nothing else about them changes. In YAML, `provider: claude` is still a Claude SDK agent.

The runtime must be **1.6.0b1** or newer (**1.6.0b7** for Sign in with Claude). An older runtime shows an update hint on Claude SDK agents only; Cursor agents keep working.

## Sign in with Claude

Experimental. The runtime runs Anthropic's own `claude setup-token` (the Claude Code CLI that comes with the Agent SDK) and hands the token back to the agent form, so you do not need Claude Code on your computer.

1. On the agent, in the **Claude SDK (runtime)** section, leave **Claude Plan token or Anthropic API key** empty, tick **Sign in with Claude (experimental)**, and press **OK**.
2. The form shows a link. Open it, sign in with the Claude account that has your plan, and copy the code Anthropic shows.
3. Paste the code and press **OK**. The token is saved on the agent like a pasted one and lasts one year.

A code works once. If Anthropic refuses it or you take longer than 15 minutes, the form shows a new link. The runtime keeps nothing: the CLI runs in a temporary folder that is deleted afterwards, and the code and token are never logged. If the CLI changes in a way the runtime does not expect, paste a token instead.

## Tools

The same rules as for Cursor agents:

- **Normal users and voice satellites:** only the MCP tools for your house. No files, no shell, no web.
- **Admin chats:** also read and write files in the runtime's workspace folder.
- **Admin chats with Allow internet:** also web search, page fetch, and the shell. Without Allow internet the shell is removed too, so `curl` or a script cannot reach the web.

Claude SDK agents never load Claude Code settings, `CLAUDE.md`, skills, hooks, or MCP servers from the runtime's disk; each turn gets only what Home Assistant sends. Subagents are off.

## Runtime options

| App option | Docker variable | Meaning |
|---|---|---|
| Claude Plan token | `CLAUDE_CODE_OAUTH_TOKEN` | Plan token for Claude SDK agents without their own credential. Used first. |
| Anthropic API key | `ANTHROPIC_API_KEY` | API key for Claude SDK agents without their own credential. |
| Claude model | `CLAUDE_MODEL` | Default model when the agent's model is empty. |

Claude Code keeps chat state in `claude-config` inside the runtime's data folder (`/data`), so a chat can resume after the runtime restarts.
