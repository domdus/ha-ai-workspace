"""Which credential each engine runs on with the Runtime's own sign-in or environment. Never the secret.

Home Assistant reads this from /api/health (``credentials``) to decide whether a runtime agent (one
without a key of its own) pays with a subscription plan (plan limits in the chat header) or with an
API key (cost in $). Per engine:

    {"kind": "subscription" | "api_key" | None,   # None: no credential at all
     "source": "signed-in" | "env-plan" | "env-api" | "auth-json" | "none",
     "id": "c0123..." | ""}                        # credential_id of a subscription, "" otherwise

The order below is the order the engine really uses at run time, because the Runtime hands exactly one
credential to it and blanks the others:

- Claude: "Sign in with Claude" (Plan token in the data folder) > CLAUDE_CODE_OAUTH_TOKEN >
  ANTHROPIC_API_KEY. Claude Code itself would prefer ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN over an
  OAuth token, so claude_subprocess_env sets only the chosen one and empties the others.
- Codex: auth.json in CODEX_HOME (Sign in with ChatGPT; or an API key stored there by `codex login
  --with-api-key`) > OPENAI_API_KEY / CODEX_API_KEY. The environment keys never reach the Codex
  process (codex_login.SECRET_ENV); the Runtime logs in with the key only when there is no auth.json.
- Cursor: API key only (CURSOR_API_KEY / the App option).
"""

from __future__ import annotations

from typing import Any

from app.plan_quota import credential_id
from app.settings import Settings


def _row(kind: str | None, source: str, ident: str = "") -> dict[str, Any]:
    return {"kind": kind, "source": source, "id": ident if kind == "subscription" else ""}


def claude_credential(settings: Settings) -> dict[str, Any]:
    from app.providers.claude import is_plan_token, signed_in_token

    for source, value in (
        ("signed-in", signed_in_token(settings)),
        ("env-plan", (settings.claude_oauth_token or "").strip()),
        ("env-api", (settings.anthropic_api_key or "").strip()),
    ):
        if value:
            # The kind follows the secret, not the variable: an API key in CLAUDE_CODE_OAUTH_TOKEN
            # is still billed as an API key (claude_subprocess_env hands it over as ANTHROPIC_API_KEY).
            kind = "subscription" if is_plan_token(value) else "api_key"
            return _row(kind, source, credential_id(value))
    return _row(None, "none")


def codex_runtime_id(settings: Settings) -> str:
    """credential_id of the ChatGPT sign-in in auth.json, or ""."""
    from app.codex_login import account_key

    account = account_key(settings.codex_auth_path)
    return credential_id(f"codex-chatgpt:{account}") if account else ""


def codex_credential(settings: Settings) -> dict[str, Any]:
    from app.codex_login import credential_source

    source = credential_source(settings)
    if source == "chatgpt":
        return _row("subscription", "auth-json", codex_runtime_id(settings))
    if source == "api-key":
        return _row("api_key", "auth-json")
    if source == "env-api":
        return _row("api_key", "env-api")
    return _row(None, "none")


def cursor_credential(settings: Settings) -> dict[str, Any]:
    if (settings.cursor_api_key or "").strip():
        return _row("api_key", "env-api")
    return _row(None, "none")


def engine_credentials(settings: Settings) -> dict[str, dict[str, Any]]:
    """Every engine's runtime credential (kind, source, id). A broken lookup reports nothing for it."""
    out: dict[str, dict[str, Any]] = {}
    for engine, lookup in (("claude", claude_credential), ("codex", codex_credential), ("cursor", cursor_credential)):
        try:
            out[engine] = lookup(settings)
        except Exception:  # noqa: BLE001 - health must answer; HA treats a missing engine as "unknown" ($).
            continue
    return out
