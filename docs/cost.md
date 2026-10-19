# Cost and tokens

**Track usage and costs** (on by default) records tokens and estimated USD after each Cursor or cloud turn, including Assist. The sidebar **Usage** button opens `/ai-workspace/usage`: today / month / all-time totals, filters for agent, model, and date, 30-day cost and token charts, and a model comparison (tokens per turn, cost per turn, highest spend, most used, cheapest turn).

**Show cost in chat header** (on by default) puts a short usage line under the chat title. Turn it off if you only want the Usage page.

Off on **Track usage and costs** stops new records. Existing history stays.

## What is counted

- **Cursor:** token counts come from the SDK. If the Cursor account exposes billed cents, that amount is stored as the cost. Otherwise the list-price estimate for Composer is used.
- **Cloud agents:** prompt and completion tokens from the provider, including cache and reasoning when they send them. Cost is list price (OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Grok, Azure, OpenRouter, compatible). OpenRouter’s reported cost is used when it is present. Ollama is stored as $0.
- **Text-to-speech:** when an OpenAI-style AI Workspace voice is used (Assist, overlay speaker, auto-read), characters of spoken text are priced (`gpt-4o-mini-tts`, `tts-1`, and `tts-1-hd`). Piper and other Home Assistant engines are not billed here.
- Unknown models still store tokens. Cost stays empty until the price table knows that model id.

## Home Assistant sensors

**Add Home Assistant usage sensors** is off by default. The Usage page does not need them.

Turn it on if you want cost, token, and turn entities on your own Lovelace dashboards. You then get a device **AI Workspace** under **Usage**, plus sensors on each agent: cost / tokens / turns for today, this month, and total, last turn, and speech cost today / total. Home Assistant also fires `ai_workspace_usage` after every recorded turn.

Turn the option off again to remove those sensors. Tracking can stay on.

## Why a house question costs more than it looks

Cloud AI and Ollama send the system prompt and the **tool list of every enabled MCP connection** with each message. HA-MCP offers on the order of 80 tools. Even with shorter descriptions, that is several thousand tokens before you type anything. Each tool call adds its result and one more request, which sends the prompt and the tool list again. A greeting or thanks is sent without tools.

A typical house-check turn on **Off** is often around **$0.40**. A long thread with many tool rounds can reach **$0.90+**. Most of that is the tool list and tool results as input, not your last sentence.

- The last 12 messages of the chat are sent again so the model remembers the thread (each cut to a few thousand characters). Earlier tool results are not. That is not the main cost.
- **[Always check the house first](settings.md#always-check-the-house-first):** a question that needs no house data, like a poem, still costs one tool call and one more request.
- **To spend less:** pick a smaller model for everyday questions, set **Reduce token usage** (below), disable the device of an MCP connection you do not need, and start a new chat when the topic changes.

## Reduce token usage

Shared AI Workspace setting (not per agent, and not on Cursor): **Off**, **Light**, **Medium**, or **Extreme**.

The expensive part is the MCP tool list (and extra tool rounds), not the chat history. That is why Medium still costs a large share of Off, and Extreme is the only mode that usually saves most of a house-check turn.

| Mode | Tools | History | Check house | Prompt | Typical save vs Off on a house-check turn |
| --- | --- | --- | --- | --- | --- |
| **Off** | All enabled MCP tools | Last 12 | Agent toggle (on by default) | Full | — |
| **Light** | Yes | Last 12 | Always on | Full | About **5–20%**. Still pays for tools and a forced house check. Skips extras such as auto-title and effort. |
| **Medium** | Yes | Last 4 | Off | Short, tools allowed | About **25–45%**. No forced extra round; tool schemas still dominate. |
| **Extreme** | No | None | Off | Two sentences; cannot control the house | About **80–95%**. |

Light still attaches files and images; Medium and Extreme do not. Medium and Extreme also shorten a very long message and cap how long the reply can be.

**Light** is the “still accurate” house mode, not the cheapest. It can cost **more** than Medium because it always checks the house first. Use Extreme for a small local model or cheap Q&A; Medium when the agent should still call MCP; Off when you want the full product.

## Prompt cache

Separate from **Reduce token usage**. Token modes change *what* is sent. Prompt cache discounts the *same* prefix when it repeats — the system prompt and the MCP tool list on every round of a turn.

Leave it **on**. After the first round of a house-check turn, the tool-list *cost* can drop about **90%** even though the token count still looks large (cache reads are typically about 10% of the input price). Combined with Extreme you skip the tools; combined with Off you keep house control at a fraction of that ~$0.40 turn.

Cursor and Ollama ignore this setting. Local Ollama is not billed per token here.

| Provider | What happens |
| --- | --- |
| **Claude** (including Claude on OpenRouter) | Caching is explicit. This switch is what turns it on for the tool list and system prompt (about five minutes). |
| **OpenAI / Azure / GPT via OpenRouter** | Prefixes over about 1,024 tokens are often cached automatically. The switch adds a stable cache key so hits can work across chats for the same agent. |
| **Ollama** | Nothing. Ignored. |

Cache-read tokens show up on the Usage page when the provider reports them. If a provider rejects the extra cache fields, the request is retried without them for the rest of that agent session.

Turn it off only if a provider is misbehaving with cache fields. You do not need to turn it off to “compare” costs: Usage already shows cache reads when they happen.
