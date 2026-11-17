# Claude SDK agents on the AI Workspace Runtime

The **AI Workspace Runtime** (the Home Assistant App, or the Compose service `ai-workspace-runtime`) that runs Cursor also runs **Claude SDK** agents. They use Anthropic's [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/), which drives the Claude Code agent inside the runtime. Home Assistant talks to it the same way as to Cursor: Runtime address, Runtime password, and MCP through the runtime.

Both are the same **Claude (Anthropic)** agent in Home Assistant. With **Use Claude SDK (runtime) (experimental)** under **Advanced** off, it calls Anthropic's API from inside Home Assistant and needs no runtime. With it on, it is a Claude SDK agent on the runtime.

## What you need

The easiest way: **Sign in with Claude plan** on the agent form (see [below](#sign-in-with-claude-plan)). That is the one place to set Claude up; the Runtime App has no Claude fields.

Or one of two Claude credentials, pasted on the agent:

- **Claude Plan token** (`sk-ant-oat…`): uses your Claude subscription (Pro, Max). On any computer with [Claude Code](https://code.claude.com), run `claude setup-token`, approve in the browser, and copy the token it prints. It lasts one year.
- **Anthropic API key** (`sk-ant-api…`): billed as API credits. From [Claude Console → API keys](https://console.anthropic.com/settings/keys).

Where it goes:

- **On the agent** (Home Assistant → AI Workspace → Add agent → **Claude (Anthropic)** → **Advanced** → **Use Claude SDK (runtime) (experimental)** → OK → **Claude Plan token or Anthropic API key**). Each agent can use its own.
- **Signed in on the runtime** with **Sign in with Claude plan**: every Claude SDK agent on that runtime without its own credential uses it.
- **Docker only:** `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` on the container (see [Runtime options](#runtime-options)). Handy for a headless setup; a sign-in on the agent form still wins over them.

The prefix decides how Claude Code signs in, and only that one credential reaches it, so a Plan chat never falls back to API billing or the other way round. Saving the agent form checks an API key with Anthropic; a Plan token is checked on the first chat.

⚠️ **It is not clear whether Anthropic allows the Plan token here.** Anthropic says: *"Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users"*, and products built on the Agent SDK should use API keys ([Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)). It *may* still count as private use, because the runtime runs on your own hardware with your own account and only you chat with it, but Anthropic has not confirmed that. Whether you use it is your decision; an Anthropic API key is the safe choice.

### Which credential wins

1. A token or key on the agent in Home Assistant (**Claude Plan token or Anthropic API key**).
2. The token from **Sign in with Claude plan** (kept on the runtime).
3. `CLAUDE_CODE_OAUTH_TOKEN` on the runtime (Docker).
4. `ANTHROPIC_API_KEY` on the runtime (Docker), or an Anthropic API key left in the App options from before 1.6.0b12.

A fresh sign-in or a credential typed into the agent form always wins over what the runtime's environment carries. Up to 1.6.0b11 a Plan token in the App options or `CLAUDE_CODE_OAUTH_TOKEN` won over a sign-in; that is gone.

### When the sign-in or key runs out

Setup tokens last about a year, and a token or key can be revoked in the Claude account or Console. When Anthropic refuses the credential, the chat says so in your language: open the agent's settings (**Settings → Devices & services → AI Workspace**), and on the **Claude account** step pick **Sign in with Claude plan** again, or go back and paste a new token or API key. Other errors (rate limits, overload) keep their own message.

## Home Assistant

1. Add an agent → **Claude (Anthropic)**.
2. Open **Advanced**, turn on **Use Claude SDK (runtime) (experimental)**, and press **OK**. Nothing is saved yet: the form comes back with the **Claude SDK (runtime)** section instead of the API key field.
3. Runtime address and password: the same as for Cursor agents. Leave the address empty when the form says **Runtime found**.
4. **Claude Plan token or Anthropic API key**: see above. Optional: leave it empty and sign in on the next step instead.
5. **Model**: an Anthropic model id such as `claude-sonnet-5-5`. Empty uses `CLAUDE_MODEL` on a Docker runtime, or Claude Sonnet.
6. **Effort**: Fast, High, and High fast map to Claude Code's low, high, and medium effort. Default lets Claude decide.
7. Submit. The **Claude account** step shows whether the runtime has a Claude credential and where it comes from.

Turning the switch off again makes it a cloud Claude agent, which needs an Anthropic API key. Effort works for both. Claude SDK agents from 1.6.0b1 and b2 become Claude (Anthropic) agents with the switch on when the integration loads; nothing else about them changes. In YAML, `provider: claude` is still a Claude SDK agent.

The runtime must be **1.6.0b1** or newer (**1.6.0b10** or newer for Sign in with Claude plan). An older runtime shows an update hint on Claude SDK agents only; Cursor agents keep working.

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
- Setup tokens last about one year. When chats say the sign-in has expired or was revoked, sign in again (see [When the sign-in or key runs out](#when-the-sign-in-or-key-runs-out)).
- Anthropic does not tell a setup token which account or plan it belongs to, so the form shows when you signed in, not the account name.
- Without Home Assistant: `docker exec -it ai-workspace-runtime python -m app.claude_login` prints the link and asks for the code.
- 1.6.0b7 and b8 had **Sign in with Claude (experimental)** as a tick box that saved the token on the agent. That box is gone; agents that got their token that way keep it. The runtime still answers those integrations (`/api/claude/login`).

### Runtime API

Bearer `RUNTIME_TOKEN` as for chats. One shape for every engine, so a later engine with a plan sign-in uses the same calls:

| Call | What it does |
| --- | --- |
| `GET /api/auth` | Status of every engine |
| `GET /api/auth/{engine}` | `ready`, `credential` (`signed-in` / `settings` = the runtime's environment / `none`), `kind` (`plan` / `api`), `signed_in` dates, `overridden` (always `false` since 1.6.0b12, kept for older integrations), `login.supported` / `login.flow` |
| `POST /api/auth/{engine}/login` | Start; returns `id`, `url`, `flow` (`paste_code` for Claude; a device-code engine adds `user_code`), `expires_in` |
| `GET /api/auth/{engine}/login/{id}` | State: `awaiting_code`, `verifying`, `succeeded`, `failed`, `cancelled`, `expired` (`?wait=N` long-polls device-code flows) |
| `POST /api/auth/{engine}/login/{id}` | `{"code": "…"}` for paste-back flows; on success the new status, never the token |
| `DELETE /api/auth/{engine}/login/{id}` | Cancel |
| `DELETE /api/auth/{engine}` | Sign out (forget the stored credential; the environment is untouched) |

`/api/health` lists engines with a plan sign-in in `"login": ["claude"]`. Cursor answers the status calls and refuses login with `501 not_supported`.

A chat turn whose credential Anthropic refused ends with `{"type": "error", "code": "claude_auth_failed", "message": "…"}`. The integration shows its own translation for that code.

## Tools

The same rules as for Cursor agents:

- **Normal users and voice satellites:** only the MCP tools for your house. No files, no shell, no web.
- **Admin chats:** also read and write files in the runtime's workspace folder.
- **Admin chats with Allow internet:** also web search, page fetch, and the shell. Without Allow internet the shell is removed too, so `curl` or a script cannot reach the web.

Claude SDK agents never load Claude Code settings, `CLAUDE.md`, skills, hooks, or MCP servers from the runtime's disk; each turn gets only what Home Assistant sends. Subagents are off.

## Runtime options

The Runtime App has no Claude fields: use **Sign in with Claude plan** on the agent. A Claude-only App needs nothing in its **Configuration** (the Cursor API key is optional).

On Docker, these environment variables work:

| Docker variable | Meaning |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Plan token for Claude SDK agents without their own credential, when nobody signed in. |
| `ANTHROPIC_API_KEY` | API key for Claude SDK agents without their own credential, when nobody signed in and no Plan token is set. |
| `CLAUDE_MODEL` | Default model when the agent's model is empty. |
| `CLAUDE_PLAN_USAGE_READ` | `off` stops the Runtime from reading the plan's usage from Anthropic (`/api/oauth/usage`, no tokens) when a turn reported none. Default on. See [Plan limits](cost.md#plan-limits). |

### Coming from 1.6.0b11 or older

The App options **Claude Plan token**, **Anthropic API key** and **Claude model** were removed in 1.6.0b12. Nothing to do on update:

- A Plan token from the old options becomes the runtime's sign-in on the first start, unless someone already signed in (that sign-in stays). It happens once: after **Sign out on the Runtime**, it does not come back.
- An old Anthropic API key and Claude model keep working in the background, without a field. Saving the App's **Configuration** again drops them (the Supervisor only keeps fields the App still has), so switch to **Sign in with Claude plan** or a key on the agent when convenient.
- The App log says once per start which old fields it found, never their values.

The Supervisor writes only the App's current fields into `/data/options.json`, so the runtime reads the old values from its own App info at the Supervisor (`/addons/self/info`, allowed for every App without extra permissions).

Claude Code keeps chat state in `claude-config` inside the runtime's data folder (`/data`), so a chat can resume after the runtime restarts.
