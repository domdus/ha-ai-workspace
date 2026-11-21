# OpenAI Codex agents on the AI Workspace Runtime

The **AI Workspace Runtime** (the Home Assistant App, or the Compose service `ai-workspace-runtime`) that runs Cursor and Claude SDK agents also runs **OpenAI Codex**. It uses OpenAI's official [Codex SDK](https://pypi.org/project/openai-codex/) (`openai-codex`) and the Codex CLI that ships with it. Home Assistant talks to it the same way as to Cursor: Runtime address, Runtime password, and MCP through the runtime.

It is the same **OpenAI** agent in Home Assistant. With **Use Codex (runtime) (experimental)** under **Advanced** off, it calls OpenAI's API from inside Home Assistant with an API key. With it on, it is a Codex agent on the runtime.

## What you need

The easiest way: **Sign in with ChatGPT** on the agent form. It uses your ChatGPT plan (Plus, Pro, Business, …).

Or an **OpenAI API key**, pasted on the agent (billed as API usage). On a Docker runtime, `OPENAI_API_KEY` works too.

Order, first one found wins:

1. An OpenAI API key on the agent in Home Assistant.
2. The sign-in with ChatGPT (kept on the runtime in `/data/codex/auth.json`, owner-only).
3. `OPENAI_API_KEY` (or `CODEX_API_KEY`) on a Docker runtime.

## Home Assistant

1. Add an agent → **OpenAI**.
2. Open **Advanced**, turn on **Use Codex (runtime) (experimental)**, and press **OK**. Nothing is saved yet: the form comes back with the **Codex (runtime)** section instead of the API key field.
3. Runtime address and password: the same as for Cursor agents. Leave the address empty when the form says **Runtime found**.
4. **OpenAI API key**: optional. Leave it empty and sign in on the next step instead.
5. **Model**: empty uses Codex's default model for your account. Or type one Codex offers (for example `gpt-5.5-codex`).
6. **Effort**: Fast, High, and High fast map to Codex's low, high, and medium reasoning effort.
7. Submit. The **Codex account** step shows whether the runtime is signed in.

Speech-to-text and text-to-speech are not offered on a Codex agent: they need an OpenAI API key in Home Assistant. Use a separate OpenAI cloud agent for voice.

## Sign in with ChatGPT

1. On the **Codex account** step, pick **Sign in with ChatGPT**.
2. Open the link (`https://auth.openai.com/codex/device`) on any device, sign in with the ChatGPT account that has your plan, and enter the one-time code the form shows.
3. Wait: the form goes on by itself as soon as OpenAI confirms the code and shows **Signed in**. Submit to save the agent.

Device-code sign-in has to be allowed once: in ChatGPT, **Settings → Security**, turn on device code login. For a workspace account, the admin allows it in the workspace permissions. Without it, OpenAI refuses the code and the form says so.

The code works for 15 minutes. Your ChatGPT password never passes through Home Assistant or the runtime. **Sign out on the Runtime** removes the sign-in. If the sign-in later expires or is revoked, the chat says so in your language: sign in with ChatGPT again on the agent.

**Docker, in a terminal:** `docker exec -it ai-workspace-runtime python -m app.codex_login` runs OpenAI's own `codex login --device-auth` and stores the sign-in in the same place (`status` and `logout` work too). The sign-in lives in the data volume (`/data/codex`), so it survives restarts and image updates.

**Already signed in on another computer?** On a Docker runtime, `CODEX_AUTH_JSON` takes a copy of `~/.codex/auth.json` (a mounted file or the JSON itself). It is copied into `/data/codex` once, when there is no sign-in yet. Don't keep using the same `auth.json` on two machines: a token refresh on one can sign the other out.

> [!WARNING]
> **Experimental.** Codex with a ChatGPT plan is meant for your own use with your own account. Check OpenAI's [terms](https://openai.com/policies/) for your plan. To be on the safe side, use an OpenAI API key on the agent.

## Tools

The same rules as Cursor and Claude SDK agents:

| Chat | Codex can |
| --- | --- |
| Normal users and voice satellites | Home Assistant tools over MCP only (read-only sandbox, no shell) |
| Admin chats | plus file edits in the runtime's workspace (`/data/workspace`), still no shell |
| Admin chats with **Allow internet** | plus the shell and live web search |
| **Save tokens** chat only | no tools |

Nobody can answer an approval prompt in a chat turn, so anything that would need one is refused. Codex loads no `AGENTS.md`, skills, hooks, plugins, apps or memories: only what the chat sends. MCP servers that ask the user (elicitation) show their card in the chat as for the other runtime agents.

The container is the sandbox: Codex's own Linux sandbox needs user namespaces, which Docker does not allow by default. On a Docker runtime that allows them, `CODEX_SANDBOX=codex` uses Codex's sandbox instead.

## Sessions, Save tokens, usage

- Follow-up messages continue the same Codex thread; it survives runtime restarts (threads are kept in `/data/codex`).
- With **Save tokens**, the thread continues while a model call's input stays under about 40,000 tokens, then the next turn starts a new thread with the recent history from Home Assistant (as on Claude SDK agents).
- Tokens of each turn appear on the **Usage** page. Codex reports no price, so the cost stays unknown on a ChatGPT plan.
- **Plan limits** on the Usage page show the ChatGPT plan's 5-hour and weekly windows (read from Codex after each turn), with a chat hint near the limit and a message when it is reached.

## Runtime options (Docker)

| Variable | Meaning |
| --- | --- |
| `OPENAI_API_KEY` / `CODEX_API_KEY` | OpenAI API key for Codex agents without their own key or a sign-in |
| `CODEX_MODEL` | Model when the agent leaves it empty (default: Codex's own default) |
| `CODEX_AUTH_JSON` | An `auth.json` to start from (path or JSON), copied once |
| `CODEX_SANDBOX` | `container` (default) or `codex` (needs user namespaces) |
| `CODEX_CONFIG` | Extra Codex `--config key=value` lines (TOML values), one per line |

The runtime must be **1.6.0** or newer. An older runtime shows an update hint on Codex agents only.
