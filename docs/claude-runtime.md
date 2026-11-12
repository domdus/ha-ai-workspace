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

Household Plan billing via Claude Code:

- `CLAUDE_CODE_OAUTH_TOKEN` or add-on `claude_oauth_token`
- Create with `claude setup-token` on a machine with Claude Code

Do **not** set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` on the runtime—they override Plan billing.

Plan tokens are for your household, not for multi-tenant SaaS.

### 3. Anthropic API

Direct API credits:

- `ANTHROPIC_API_KEY` or add-on `anthropic_api_key`

Optional `ANTHROPIC_BASE_URL` for proxies (not OpenRouter unless using mode 1).

## Home Assistant

1. Add an agent → **Claude (Anthropic)**.
2. Turn on **Use Claude SDK (runtime)** (German: *Claude SDK (Runtime) verwenden*).
3. In the collapsed **Claude SDK (runtime)** section: runtime URL and token (same as Cursor agents).
4. **Claude Plan token or Anthropic API key** (`sk-ant-oat-…` or `sk-ant-api…`) — optional if the runtime already has credentials.
5. Model: Anthropic id such as `claude-sonnet-5-5` (runtime OpenRouter slugs still work when the runtime is configured for OpenRouter).

Runtime health must report `"claude": true` (runtime **1.6.0** or newer). Older runtimes show an update notice for Claude SDK agents only; Cursor keeps working.

## Optional

- `CLAUDE_MODEL` / add-on `claude_model` — default when the agent model is empty
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` — optional OpenRouter model discovery
