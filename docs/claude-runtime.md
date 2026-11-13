# Claude Agent SDK on the AI Workspace runtime

The same **AI Workspace Runtime** container (add-on or Compose service `ai-workspace-runtime`) that runs Cursor also runs **Claude SDK** agents via the [`claude-agent-sdk`](https://pypi.org/project/claude-agent-sdk/) package. Home Assistant talks to it the same way as Cursor: Runtime URL, shared `RUNTIME_TOKEN`, and MCP proxied through the runtime.

**Claude (Anthropic)** in Home Assistant is one provider row: leave **Use Claude SDK (runtime)** off for the direct Messages API, or turn it on for this runtime (same fields as below in a collapsed section).

## Credentials (runtime or add-on)

Configure **one** of these on the runtime host (environment or `ai_workspace` add-on options). Per-agent credentials can override on the **Claude (Anthropic)** agent when **Use Claude SDK (runtime)** is on.

### 1. OpenRouter (Agent SDK)

For [OpenRouter’s Anthropic Agent SDK](https://openrouter.ai/docs/guides/community/anthropic-agent-sdk) routing:

- `OPENROUTER_API_KEY` or add-on `openrouter_api_key`
- Or per-chat key starting with `sk-or-`

The runtime sets subprocess env:

- `ANTHROPIC_BASE_URL=https://openrouter.ai/api`
- `ANTHROPIC_AUTH_TOKEN=<key>`
- `ANTHROPIC_API_KEY=` (empty string)

Use OpenRouter model slugs on the agent (e.g. `anthropic/claude-sonnet-4.5`).

### 2. Claude Pro / Max / Ultra Plan (OAuth)

Household Plan billing via Claude Code. Easiest: **Sign in with Claude plan** in the agent form (see [Sign in with Claude plan](#sign-in-with-claude-plan) below) — no Claude Code on your computer, nothing to paste except the code Anthropic shows.

Or set a token yourself:

- `CLAUDE_CODE_OAUTH_TOKEN` or add-on `claude_oauth_token`
- Create with `claude setup-token` on a machine with Claude Code

Do **not** set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` on the runtime—they override Plan billing.

Plan tokens are for your household, not for multi-tenant SaaS.

### 3. Anthropic API

Direct API credits:

- `ANTHROPIC_API_KEY` or add-on `anthropic_api_key`

Optional `ANTHROPIC_BASE_URL` for proxies (not OpenRouter unless using mode 1).

### Which credential wins

1. A token or key on the agent in Home Assistant (**Claude Plan token or Anthropic API key**).
2. `OPENROUTER_API_KEY` / `openrouter_api_key` on the runtime.
3. `CLAUDE_CODE_OAUTH_TOKEN` / `claude_oauth_token` on the runtime.
4. The token from **Sign in with Claude plan**.
5. `ANTHROPIC_API_KEY` / `anthropic_api_key` on the runtime.

## Home Assistant

1. Add an agent → **Claude (Anthropic)**.
2. Turn on **Use Claude SDK (runtime)** (German: *Claude SDK (Runtime) verwenden*).
3. In the collapsed **Claude SDK (runtime)** section: runtime URL and token (same as Cursor agents).
4. **Claude Plan token or Anthropic API key** (`sk-ant-oat-…` or `sk-ant-api…`) — optional. Leave it empty and sign in on the next step instead.
5. Model: Anthropic id such as `claude-sonnet-5-5` (runtime OpenRouter slugs still work when the runtime is configured for OpenRouter).
6. Submit. The **Claude account** step shows whether the runtime has a credential and where it comes from.

## Sign in with Claude plan

Only for **Claude (Anthropic)** agents with **Use Claude SDK (runtime)** on. Cloud-API agents and Cursor agents look as before (the Cursor SDK has no plan sign-in; it keeps its API key).

1. After submitting the agent form, the **Claude account** step says, for example, *⚠️ Not signed in yet* or *✅ Signed in with your Claude plan on the Runtime (since 2026-11-13, valid until about 2027-11-13)*.
2. Pick **Sign in with Claude plan**. The runtime starts Anthropic's own `claude setup-token` (bundled with `claude-agent-sdk`) and the form shows its sign-in link.
3. Open the link, sign in with the Claude account that has your Pro or Max plan, and copy the code Anthropic shows.
4. Paste the code into **Code from Anthropic** and submit. A mistyped code can be pasted again; a code Anthropic rejects gives you a fresh link on the same form.
5. **Signed in** confirms it (no token is shown). Submit to save the agent.

Other choices on the **Claude account** step: **Save agent** (when a credential exists), **Sign out on the Runtime** (forgets the signed-in token), **Back to the agent settings** (for example to paste a token by hand).

Good to know:

- The token is stored on the runtime only, in `/data/auth/claude-oauth-token` (owner-only file in the add-on's or container's data volume). It never goes to Home Assistant or its config entries, and is never logged.
- The sign-in belongs to the runtime, so every Claude SDK agent on that runtime uses it.
- Signing in clears an older token saved on that agent, because the agent's own token would win.
- Setup tokens last about one year. Sign in again when chats start failing with an authentication error.
- Anthropic does not tell a setup token which account or plan it belongs to, so the form shows when you signed in, not the account name.
- Without Home Assistant: `docker exec -it ai-workspace-runtime python -m app.claude_login` prints the link and asks for the code.

### Runtime API

Bearer `RUNTIME_TOKEN` as for chats. One shape for every engine, so a later plan login (for example Codex) uses the same calls:

| Call | What it does |
| --- | --- |
| `GET /api/auth` | Status of every engine |
| `GET /api/auth/{engine}` | `ready`, `credential` (`settings` / `signed-in` / `none`), `kind` (`plan` / `api` / `openrouter`), `signed_in` dates, `overridden`, `login.supported` / `login.flow` |
| `POST /api/auth/{engine}/login` | Start; returns `id`, `url`, `flow` (`paste_code` for Claude; a device-code engine would add `user_code`), `expires_in` |
| `GET /api/auth/{engine}/login/{id}` | State: `awaiting_code`, `verifying`, `succeeded`, `failed`, `cancelled`, `expired` |
| `POST /api/auth/{engine}/login/{id}` | `{"code": "…"}` for paste-back flows; on success the new status, never the token |
| `DELETE /api/auth/{engine}/login/{id}` | Cancel |
| `DELETE /api/auth/{engine}` | Sign out (forget the stored credential; options and environment are untouched) |

`/api/health` lists engines with a plan sign-in in `"login": ["claude"]`. Cursor answers the status calls and refuses login with `501 not_supported`.

Runtime health must report `"claude": true` (runtime **1.6.0** or newer). Older runtimes show an update notice for Claude SDK agents only; Cursor keeps working.

## Optional

- `CLAUDE_MODEL` / add-on `claude_model` — default when the agent model is empty
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` — optional OpenRouter model discovery
