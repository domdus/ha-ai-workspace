"""The Runtime reports per engine which credential kind it runs on (/api/health "credentials")."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.claude_login import save_token
from app.credentials import claude_credential, codex_credential, cursor_credential, engine_credentials
from app.main import create_app
from app.plan_quota import PlanQuotaBook, credential_id, merge_snapshots
from app.providers.claude import claude_subprocess_env, resolve_credential
from app.settings import Settings

PLAN = "sk-ant-oat01-" + "p" * 40
SIGNED = "sk-ant-oat01-" + "s" * 40
API = "sk-ant-api03-" + "k" * 40


def _settings(tmp_path: Path, **kw) -> Settings:
    base = Settings(
        data_dir=tmp_path,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        auth_mode="dev",
        host="127.0.0.1",
        port=8090,
        runtime_token="",
    )
    return replace(base, **kw)


def _chatgpt_auth(path: Path, account: str = "acct-1") -> None:
    claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": "plus", "chatgpt_account_id": account}}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tokens": {"id_token": f"x.{body}.y", "refresh_token": "r", "access_token": "a"}}))


def test_claude_subscription_from_env_plan_token(tmp_path) -> None:
    row = claude_credential(_settings(tmp_path, claude_oauth_token=PLAN))
    assert row == {"kind": "subscription", "source": "env-plan", "id": credential_id(PLAN)}


def test_claude_env_api_key_is_api_key(tmp_path) -> None:
    row = claude_credential(_settings(tmp_path, anthropic_api_key=API))
    assert row == {"kind": "api_key", "source": "env-api", "id": ""}
    # An API key in the plan variable is still an API key (it reaches Claude Code as ANTHROPIC_API_KEY).
    assert claude_credential(_settings(tmp_path, claude_oauth_token=API))["kind"] == "api_key"


def test_claude_both_follow_the_runtime_precedence(tmp_path) -> None:
    # Plan token and API key both in the environment: the Runtime hands Claude Code only the plan
    # token and blanks ANTHROPIC_API_KEY (which Claude Code would otherwise prefer), so it is a plan.
    settings = _settings(tmp_path, claude_oauth_token=PLAN, anthropic_api_key=API)
    row = claude_credential(settings)
    assert row["kind"] == "subscription" and row["source"] == "env-plan"
    used = resolve_credential(settings)
    assert used == PLAN
    env = claude_subprocess_env(settings, used)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == PLAN
    assert env["ANTHROPIC_API_KEY"] == "" and env["ANTHROPIC_AUTH_TOKEN"] == ""
    # A sign-in beats both.
    save_token(settings.claude_token_path, SIGNED)
    assert claude_credential(settings) == {"kind": "subscription", "source": "signed-in", "id": credential_id(SIGNED)}


def test_claude_without_credential(tmp_path) -> None:
    assert claude_credential(_settings(tmp_path)) == {"kind": None, "source": "none", "id": ""}


def test_codex_kinds_and_precedence(tmp_path) -> None:
    assert codex_credential(_settings(tmp_path)) == {"kind": None, "source": "none", "id": ""}
    env_only = _settings(tmp_path, openai_api_key="sk-openai")
    assert codex_credential(env_only) == {"kind": "api_key", "source": "env-api", "id": ""}
    # auth.json (ChatGPT sign-in) wins over OPENAI_API_KEY, as at run time (codex resolve_credential).
    _chatgpt_auth(env_only.codex_auth_path)
    row = codex_credential(env_only)
    assert row["kind"] == "subscription" and row["source"] == "auth-json"
    assert row["id"] == credential_id("codex-chatgpt:acct-1")
    from app.providers.codex import resolve_credential as codex_resolve

    assert codex_resolve(env_only)[0] == "chatgpt"
    # An API key stored in auth.json is an API key.
    env_only.codex_auth_path.write_text(json.dumps({"OPENAI_API_KEY": "sk-stored"}))
    assert codex_credential(env_only) == {"kind": "api_key", "source": "auth-json", "id": ""}


def test_cursor_is_always_an_api_key(tmp_path) -> None:
    assert cursor_credential(_settings(tmp_path, cursor_api_key="key"))["kind"] == "api_key"
    assert cursor_credential(_settings(tmp_path))["kind"] is None


def test_health_reports_kinds_without_secrets(tmp_path) -> None:
    settings = _settings(tmp_path, claude_oauth_token=PLAN, anthropic_api_key=API, openai_api_key="sk-openai")
    app = create_app(settings, {})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = client.get("/api/health").json()
    creds = body["credentials"]
    assert creds["claude"]["kind"] == "subscription"
    assert creds["codex"]["kind"] == "api_key"
    assert creds["cursor"]["kind"] is None
    text = json.dumps(body)
    for secret in (PLAN, API, "sk-openai"):
        assert secret not in text
    assert engine_credentials(settings) == creds


def test_snapshots_are_tagged_and_never_mixed(tmp_path) -> None:
    book = PlanQuotaBook(tmp_path / "plan_quota.json")
    book.apply("claude", {"session_percent": 70, "week_percent": 40}, credential_id(PLAN))
    snap = book.get("claude")
    assert snap["credential"] == credential_id(PLAN) and snap["session_percent"] == 70
    # Another credential's reading replaces the old one instead of keeping its week percent.
    book.apply("claude", {"session_percent": 5}, credential_id(SIGNED))
    snap = book.get("claude")
    assert snap["credential"] == credential_id(SIGNED)
    assert snap["session_percent"] == 5 and snap.get("week_percent") is None
    # Same credential: the usual merge.
    merged = merge_snapshots(snap, {"week_percent": 9, "credential": credential_id(SIGNED)})
    assert merged["session_percent"] == 5 and merged["week_percent"] == 9


def test_credential_id_is_one_way_and_shared() -> None:
    from custom_components.ai_workspace.plan_quota import credential_id as ha_credential_id

    ident = credential_id(PLAN)
    assert ident == ha_credential_id(f"  {PLAN} ") and ident.startswith("c") and len(ident) == 17
    assert PLAN not in ident and credential_id("") == ""
    assert credential_id(PLAN) != credential_id(SIGNED)
