# Claude Agent SDK on the AI Workspace runtime

The same **AI Workspace Runtime** container (add-on or Compose service `ai-workspace-runtime`) that runs Cursor also runs **Claude SDK** agents via the [`claude-agent-sdk`](https://pypi.org/project/claude-agent-sdk/) package. Home Assistant talks to it the same way as Cursor: Runtime URL, shared `RUNTIME_TOKEN`, and MCP proxied through the runtime.

The cloud agent **Claude (Anthropic)** in the integration is unchanged—it still uses the Messages API directly, not this runtime.

## Credentials (runtime or add-on)

Configure auth on the runtime host (environment or `ai_workspace` add-on options). Per-chat credentials can override on the **Claude SDK** agent form only when documented below.

### 1. OpenRouter (Agent SDK)

For [OpenRouter’s Anthropic Agent SDK](https://openrouter.ai/docs/guides/community/anthropic-agent-sdk) routing:

- `OPENROUTER_API_KEY` or add-on `openrouter_api_key`
- Or per-chat key starting with `sk-or-`

The runtime sets subprocess env:

- `ANTHROPIC_BASE_URL=https://openrouter.ai/api`
- `ANTHROPIC_AUTH_TOKEN=<key>`
- `ANTHROPIC_API_KEY=` (empty string)

Use OpenRouter model slugs on the agent (e.g. `anthropic/claude-sonnet-4.5`).

### 2. Claude Pro / Max / Ultra (Plan)

Household Plan billing via Claude Code:

- `CLAUDE_CODE_OAUTH_TOKEN` or add-on `claude_oauth_token`
- Create with `claude setup-token` on your **computer** (not on the Home Assistant or runtime host)

Do **not** set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` on the runtime—they override Plan billing.

Plan tokens are for your household, not for multi-tenant SaaS.

### 3. Anthropic API

Direct API credits:

- `ANTHROPIC_API_KEY` or add-on `anthropic_api_key`

Optional `ANTHROPIC_BASE_URL` for proxies (not OpenRouter unless using mode 1).

## Home Assistant

1. Add an agent → **Claude SDK** (not “Claude (Anthropic)”).
2. Runtime URL and token: same as Cursor agents.
3. **Claude Plan token**: paste the `sk-ant-oat-…` value from `claude setup-token` on your computer. The integration stores it on the runtime (`claude_oauth_token`). Leave the field empty when the runtime already has Plan or another Claude auth mode configured.
4. Model: Anthropic id (`claude-sonnet-5-5`) for Plan or API; OpenRouter slugs when using OpenRouter on the runtime.

Runtime health must report `"claude": true` (runtime **1.6.0** or newer). Older runtimes show an update notice for Claude SDK agents only; Cursor keeps working.

## Optional

- `CLAUDE_MODEL` / add-on `claude_model` — default when the agent model is empty
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` — optional OpenRouter model discovery
