"""Runtime: "Sign in with Claude" drives `claude setup-token` and keeps the Plan token in /data.

A fake `claude` program stands in for the real CLI: it prints the same lines (link, prompt, token or
OAuth error) so the terminal handling, link and token reading run for real. No network, no real CLI.
"""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import claude_login
from app.auth import ClaudeAuth
from app.claude_login import LoginError, LoginManager, clean_code, find_link, find_token, load_token, plain_text, token_info
from app.main import create_app
from app.providers.base import ProviderInfo
from app.providers.claude import claude_subprocess_env, credential_source, resolve_credential, runtime_credential
from app.settings import Settings

LINK = (
    "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    "&response_type=code&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
    "&scope=user%3Ainference&code_challenge=abc&code_challenge_method=S256&state=xyz"
)
TOKEN = "sk-ant-oat01-" + "Ab3_-" * 20

_FAKE = f'''#!{sys.executable}
import os, sys, time
assert sys.argv[1:] == ["setup-token"], sys.argv
leaked = [k for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "RUNTIME_TOKEN") if k in os.environ]
out = sys.stdout
out.write("\\x1b[2J\\x1b[1;1HWelcome\\x1b[1Cto\\x1b[1CClaude\\x1b[1CCode\\n")
if leaked:
    out.write("LEAKED " + ",".join(leaked) + "\\n")
out.write("Browser didn't open? Use the url below to sign in (c to copy)\\n\\n")
out.write("{LINK}\\n\\n")
out.write("Paste\\x1b[1Ccode\\x1b[1Chere\\x1b[1Cif\\x1b[1Cprompted\\x1b[1C>\\x1b[?25h")
out.flush()
# Like the real CLI (Ink, raw mode): a chunk with text is a paste, an Enter inside it is not a submit.
import tty
tty.setraw(0)
typed = b""
while True:
    chunk = os.read(0, 4096)
    if chunk in (b"\\r", b"\\n"):
        break
    typed += chunk.replace(b"\\r", b"").replace(b"\\n", b"")
code = typed.decode().strip()
if code == "good#state":
    out.write("\\n \\x1b[32m\\u2713 Long-lived authentication token created successfully!\\x1b[0m\\n\\n")
    out.write(" Your OAuth token (valid for 1 year):\\n\\n \\x1b[1m{TOKEN}\\x1b[0m\\n\\n")
else:
    out.write("\\nOAuth error: That code wasn't accepted. It may be incomplete, expired, already used.\\n")
out.flush()
time.sleep(30)
'''

LOCAL = "http://127.0.0.1"


class _Provider:
    def __init__(self, name: str) -> None:
        self.info = ProviderInfo(name, name, True, None)


def _settings(tmp_path: Path, **extra) -> Settings:
    base = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        auth_mode="dev",
        host="127.0.0.1",
        port=8090,
    )
    return replace(base, **extra)


@pytest.fixture
def fake_cli(tmp_path: Path) -> str:
    path = tmp_path / "bin" / "claude"
    path.parent.mkdir()
    path.write_text(_FAKE, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _client(settings: Settings, fake_cli: str, monkeypatch) -> TestClient:
    monkeypatch.setattr(claude_login, "cli_path", lambda: fake_cli)
    app = create_app(settings, {"cursor": _Provider("cursor"), "claude": _Provider("claude")})
    return TestClient(app, base_url=LOCAL)


def test_terminal_text_link_token_and_code_shape() -> None:
    raw = b"Paste\x1b[1Ccode\x1b[1Chere\n" + LINK.encode() + b"\x1b[0m\n"
    text = plain_text(raw)
    assert "Paste code here" in text
    assert find_link(text) == LINK
    assert find_token(plain_text(f"token:\n \x1b[1m{TOKEN}\x1b[0m".encode())) == TOKEN
    assert clean_code("  abc-DEF_123#state.x~ ") == "abc-DEF_123#state.x~"
    for bad in ("", "a b", "code\r\nrm -rf /", "x" * 600, "\x03"):
        with pytest.raises(LoginError) as err:
            clean_code(bad)
        assert err.value.key == "bad_code"


def test_the_cli_never_sees_runtime_credentials_and_its_folder_is_removed(fake_cli, monkeypatch) -> None:
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "RUNTIME_TOKEN"):
        monkeypatch.setenv(key, "secret-" + key)

    async def run():
        manager = LoginManager(cli_finder=lambda: fake_cli)
        login = await manager.start()
        home = login._home
        assert "LEAKED" not in login._text()
        assert await manager.finish(login.id, "good#state") == TOKEN
        assert not os.path.exists(home)

    asyncio.run(run())


def test_sign_in_over_http_saves_the_token_owner_only_and_never_returns_it(tmp_path, fake_cli, monkeypatch) -> None:
    settings = _settings(tmp_path, runtime_token="rt")
    auth = {"Authorization": "Bearer rt"}
    with _client(settings, fake_cli, monkeypatch) as client:
        assert client.get("/api/health").json()["login"] == ["claude"]
        assert client.post("/api/auth/claude/login").status_code == 401
        before = client.get("/api/auth/claude", headers=auth).json()
        assert before["credential"] == "none" and before["ready"] is False
        assert before["login"]["supported"] and before["login"]["flow"] == "paste_code"

        started = client.post("/api/auth/claude/login", headers=auth).json()
        assert started["url"] == LINK and started["status"] == "awaiting_code"
        assert started["engine"] == "claude" and started["flow"] == "paste_code" and started["expires_in"] > 0
        state = client.get(f"/api/auth/claude/login/{started['id']}", headers=auth).json()
        assert state["status"] == "awaiting_code"
        assert client.get("/api/auth/claude", headers=auth).json()["login"]["pending"]["id"] == started["id"]

        mistyped = client.post(f"/api/auth/claude/login/{started['id']}", json={"code": "has space"}, headers=auth)
        assert mistyped.status_code == 400 and mistyped.json()["detail"] == "bad_code"
        done = client.post(f"/api/auth/claude/login/{started['id']}", json={"code": "good#state"}, headers=auth)
        assert done.status_code == 200, done.text
        assert TOKEN not in done.text
        body = done.json()
        assert body["status"] == "succeeded"
        assert body["auth"]["credential"] == "signed-in" and body["auth"]["kind"] == "plan"
        assert body["auth"]["signed_in"]["expires_at"] > body["auth"]["signed_in"]["saved_at"]

        path = settings.claude_token_path
        assert path.parent == settings.data_dir / "auth"
        assert load_token(path) == TOKEN
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
        assert TOKEN not in client.get("/api/auth", headers=auth).text

        out = client.delete("/api/auth/claude", headers=auth).json()
        assert out["removed"] is True and out["auth"]["credential"] == "none"
        assert load_token(path) == ""


def test_a_rejected_code_ends_the_sign_in_and_cancel_stops_it(tmp_path, fake_cli, monkeypatch) -> None:
    with _client(_settings(tmp_path), fake_cli, monkeypatch) as client:
        started = client.post("/api/auth/claude/login").json()
        wrong = client.post(f"/api/auth/claude/login/{started['id']}", json={"code": "nope"})
        assert wrong.status_code == 400 and wrong.json()["detail"] == "code_rejected"
        state = client.get(f"/api/auth/claude/login/{started['id']}").json()
        assert state["status"] == "failed" and state["error"] == "code_rejected"

        again = client.post("/api/auth/claude/login").json()
        assert client.delete(f"/api/auth/claude/login/{again['id']}").status_code == 204
        gone = client.post(f"/api/auth/claude/login/{again['id']}", json={"code": "good#state"})
        assert gone.status_code == 410 and gone.json()["detail"] == "expired"
        assert client.get("/api/auth/claude/login/unknown").status_code == 410


def test_the_1_6_0b7_endpoint_still_answers_and_shares_the_one_sign_in(tmp_path, fake_cli, monkeypatch) -> None:
    settings = _settings(tmp_path)
    with _client(settings, fake_cli, monkeypatch) as client:
        health = client.get("/api/health").json()
        assert health["claude_login"] is True and health["login"] == ["claude"]
        old = client.post("/api/claude/login").json()
        assert old["url"] == LINK
        # One sign-in at a time: the new API sees the one an older integration started.
        assert client.get("/api/auth/claude").json()["login"]["pending"]["id"] == old["id"]
        done = client.post(f"/api/claude/login/{old['id']}", json={"code": "good#state"})
        # Older integrations save the token on the agent; the runtime keeps nothing then.
        assert done.status_code == 200 and done.json() == {"token": TOKEN}
        assert load_token(settings.claude_token_path) == ""
        newer = client.post("/api/auth/claude/login").json()
        assert client.post(f"/api/claude/login/{newer['id']}", json={"code": "bad code"}).status_code == 400
        assert client.delete(f"/api/claude/login/{newer['id']}").status_code == 204
        assert client.get("/api/auth/claude").json()["login"]["pending"] is None


def test_missing_cli_unknown_engine_and_cursor_has_no_plan_login(tmp_path, monkeypatch) -> None:
    with _client(_settings(tmp_path, cursor_api_key="crsr_x"), "", monkeypatch) as client:
        missing = client.post("/api/auth/claude/login")
        assert missing.status_code == 501 and missing.json()["detail"] == "cli_missing"
        assert client.get("/api/auth/claude").json()["login"]["available"] is False
        assert client.get("/api/auth/codex").status_code == 404
        cursor = client.get("/api/auth/cursor").json()
        assert cursor["credential"] == "settings" and cursor["login"] == {"supported": False, "reason": "api_key_only"}
        refused = client.post("/api/auth/cursor/login")
        assert refused.status_code == 501 and refused.json()["detail"] == "not_supported"


def test_credential_order_and_the_agent_turn_uses_the_signed_in_token(tmp_path) -> None:
    plain = _settings(tmp_path)
    claude_login.save_token(plain.claude_token_path, TOKEN)
    assert credential_source(plain) == "signed-in"
    assert runtime_credential(plain) == TOKEN
    env = claude_subprocess_env(plain, resolve_credential(plain, ""))
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN and env["ANTHROPIC_API_KEY"] == ""
    # The agent's own credential still wins over the sign-in.
    assert resolve_credential(plain, "sk-ant-api03-agent") == "sk-ant-api03-agent"

    # A sign-in beats an Anthropic API key in the add-on options...
    api = replace(plain, anthropic_api_key="sk-ant-api03-x")
    assert runtime_credential(api) == TOKEN and credential_source(api) == "signed-in"
    # ...but an explicit Plan token in the options wins, and the status says so.
    option = replace(plain, claude_oauth_token="sk-ant-oat01-option")
    assert runtime_credential(option) == "sk-ant-oat01-option"
    status = ClaudeAuth(option, LoginManager(cli_finder=lambda: "")).status()
    assert status["credential"] == "settings" and status["overridden"] is True


def test_token_info_and_a_broken_file(tmp_path) -> None:
    path = tmp_path / "auth" / "claude-oauth-token"
    assert token_info(path) is None
    path.parent.mkdir()
    path.write_text("not a token", encoding="utf-8")
    assert load_token(path) == "" and token_info(path) is None
    with pytest.raises(LoginError):
        claude_login.save_token(path, "sk-ant-api03-not-a-plan-token")


def test_an_unfinished_sign_in_expires(fake_cli, monkeypatch) -> None:
    async def run():
        manager = LoginManager(cli_finder=lambda: fake_cli)
        login = await manager.start()
        real = time.monotonic
        monkeypatch.setattr(claude_login.time, "monotonic", lambda: real() + 10_000)
        with pytest.raises(LoginError) as err:
            await manager.finish(login.id, "good#state")
        assert err.value.key == "expired"
        assert login._proc is None and login.status == "expired"

    asyncio.run(run())
