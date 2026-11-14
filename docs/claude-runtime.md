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

Easier: let the runtime do it with **Sign in with Claude plan** on the agent form (runtime 1.6.0b9 or newer), see [Sign in with Claude plan](#sign-in-with-claude-plan). The runtime then keeps the Plan token itself.

Anthropic's terms for the Agent SDK say third-party products should use API keys and not offer Claude.ai sign-in ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). Whether your own Plan token on your own runtime is fine for you is your decision.

### Which credential wins

1. A token or key on the agent in Home Assistant (**Claude Plan token or Anthropic API key**).
2. `CLAUDE_CODE_OAUTH_TOKEN` / **Claude Plan token** on the runtime.
3. The token from **Sign in with Claude plan** (kept on the runtime).
4. `ANTHROPIC_API_KEY` / **Anthropic API key** on the runtime.

## Home Assistant

1. Add an agent → **Claude (Anthropic)**.
2. Open **Advanced**, turn on **Use Claude SDK (runtime) (experimental)**, and press **OK**. Nothing is saved yet: the form comes back with the **Claude SDK (runtime)** section instead of the API key field.
3. Runtime address and password: the same as for Cursor agents. Leave the address empty when the form says **Runtime found**.
4. **Claude Plan token or Anthropic API key**: see above. Optional: leave it empty and sign in on the next step instead.
5. **Model**: an Anthropic model id such as `claude-sonnet-5-5`. Empty uses the runtime's **Claude model** option, or Claude Sonnet.
6. **Effort**: Fast, High, and High fast map to Claude Code's low, high, and medium effort. Default lets Claude decide.
7. Submit. The **Claude account** step shows whether the runtime has a Claude credential and where it comes from.

Turning the switch off again makes it a cloud Claude agent, which needs an Anthropic API key. Effort works for both. Claude SDK agents from 1.6.0b1 and b2 become Claude (Anthropic) agents with the switch on when the integration loads; nothing else about them changes. In YAML, `provider: claude` is still a Claude SDK agent.

The runtime must be **1.6.0b1** or newer (newer than **1.6.0b8** for Sign in with Claude plan). An older runtime shows an update hint on Claude SDK agents only; Cursor agents keep working.

## Sign in with Claude plan

Only for **Claude (Anthropic)** agents with **Use Claude SDK (runtime)** on. Cloud-API agents and Cursor agents look as before (the Cursor SDK has no plan sign-in; it keeps its API key).

1. After submitting the agent form, the **Claude account** step says, for example, *⚠️ Not signed in yet* or *✅ Signed in with your Claude plan on the Runtime (since 2026-11-13, valid until about 2027-11-13)*.
2. Pick **Sign in with Claude plan**. The runtime starts Anthropic's own `claude setup-token` (the Claude Code CLI bundled with `claude-agent-sdk`) and the form shows its sign-in link.
3. Open the link, sign in with the Claude account that has your Pro or Max plan, and copy the code Anthropic shows.
4. Paste the code into **Code from Anthropic** and submit. A mistyped code can be pasted again; a code Anthropic rejects gives you a fresh link on the same form.
5. **Signed in** confirms it (no token is shown). Submit to save the agent.

Other choices on the **Claude account** step: **Save agent** (when a credential exists), **Sign out on the Runtime** (forgets the signed-in token), **Back to the agent settings** (for example to paste a token by hand).

Good to know:

- The token is stored on the runtime only, in `/data/auth/claude-oauth-token` (owner-only file in the App's or container's data volume). It never goes to Home Assistant or its config entries, and is never logged. The CLI runs without the runtime's own credentials in a temporary folder that is deleted afterwards.
- The sign-in belongs to the runtime, so every Claude SDK agent on that runtime without its own credential uses it.
- Signing in clears an older token saved on that agent, because the agent's own token would win.
- Setup tokens last about one year. Sign in again when chats start failing with a sign-in error.
- Anthropic does not tell a setup token which account or plan it belongs to, so the form shows when you signed in, not the account name.
- Without Home Assistant: `docker exec -it ai-workspace-runtime python -m app.claude_login` prints the link and asks for the code.
- 1.6.0b7 and b8 had **Sign in with Claude (experimental)** as a tick box that saved the token on the agent. That box is gone; agents that got their token that way keep it. The runtime still answers those integrations (`/api/claude/login`).

### Runtime API

Bearer `RUNTIME_TOKEN` as for chats. One shape for every engine, so a later engine with a plan sign-in uses the same calls:

| Call | What it does |
| --- | --- |
| `GET /api/auth` | Status of every engine |
| `GET /api/auth/{engine}` | `ready`, `credential` (`settings` / `signed-in` / `none`), `kind` (`plan` / `api`), `signed_in` dates, `overridden`, `login.supported` / `login.flow` |
| `POST /api/auth/{engine}/login` | Start; returns `id`, `url`, `flow` (`paste_code` for Claude; a device-code engine adds `user_code`), `expires_in` |
| `GET /api/auth/{engine}/login/{id}` | State: `awaiting_code`, `verifying`, `succeeded`, `failed`, `cancelled`, `expired` (`?wait=N` long-polls device-code flows) |
| `POST /api/auth/{engine}/login/{id}` | `{"code": "…"}` for paste-back flows; on success the new status, never the token |
| `DELETE /api/auth/{engine}/login/{id}` | Cancel |
| `DELETE /api/auth/{engine}` | Sign out (forget the stored credential; options and environment are untouched) |

`/api/health` lists engines with a plan sign-in in `"login": ["claude"]`. Cursor answers the status calls and refuses login with `501 not_supported`.

## Tools

The same rules as for Cursor agents:

- **Normal users and voice satellites:** only the MCP tools for your house. No files, no shell, no web.
- **Admin chats:** also read and write files in the runtime's workspace folder.
- **Admin chats with Allow internet:** also web search, page fetch, and the shell. Without Allow internet the shell is removed too, so `curl` or a script cannot reach the web.

Claude SDK agents never load Claude Code settings, `CLAUDE.md`, skills, hooks, or MCP servers from the runtime's disk; each turn gets only what Home Assistant sends. Subagents are off.

## Runtime options

| App option | Docker variable | Meaning |
|---|---|---|
| Claude Plan token | `CLAUDE_CODE_OAUTH_TOKEN` | Plan token for Claude SDK agents without their own credential. Used first, before a sign-in. |
| Anthropic API key | `ANTHROPIC_API_KEY` | API key for Claude SDK agents without their own credential. |
| Claude model | `CLAUDE_MODEL` | Default model when the agent's model is empty. |

Claude Code keeps chat state in `claude-config` inside the runtime's data folder (`/data`), so a chat can resume after the runtime restarts.
