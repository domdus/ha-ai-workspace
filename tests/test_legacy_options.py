"""1.6.0b12: Claude left the App options. Old values keep working, the old Plan token becomes a sign-in once."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import claude_login, legacy_options
from app.claude_login import load_token, save_token
from app.legacy_options import MOVED_MARKER, apply_legacy_options, move_legacy_token, supervisor_options, with_legacy_options
from app.main import create_app
from app.providers.base import ProviderInfo
from app.providers.claude import credential_source, resolve_model, runtime_credential
from app.settings import Settings

OLD_TOKEN = "sk-ant-oat01-" + "Old_-" * 20
NEW_TOKEN = "sk-ant-oat01-" + "New_-" * 20
API_KEY = "sk-ant-api03-old-option-key"


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


def _from_options(tmp_path: Path, monkeypatch, options: dict) -> Settings:
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options), encoding="utf-8")
    monkeypatch.setenv("ADDON_OPTIONS", str(path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_MODEL", "SUPERVISOR_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    return Settings.from_env()


# --- the old Plan token becomes a sign-in, once ------------------------------------------------


def test_old_options_plan_token_becomes_the_sign_in(tmp_path, monkeypatch) -> None:
    settings = _from_options(tmp_path, monkeypatch, {"claude_oauth_token": OLD_TOKEN, "cursor_api_key": ""})
    assert runtime_credential(settings) == ""  # never used straight from the options
    assert move_legacy_token(settings) == "moved"
    assert load_token(settings.claude_token_path) == OLD_TOKEN
    assert runtime_credential(settings) == OLD_TOKEN and credential_source(settings) == "signed-in"
    assert (settings.claude_token_path.parent / MOVED_MARKER).is_file()
    # Next start: nothing to do.
    assert move_legacy_token(settings) == "done"


def test_a_sign_out_after_the_move_stays_signed_out(tmp_path, monkeypatch) -> None:
    settings = _from_options(tmp_path, monkeypatch, {"claude_oauth_token": OLD_TOKEN})
    assert move_legacy_token(settings) == "moved"
    claude_login.forget_token(settings.claude_token_path)
    assert move_legacy_token(settings) == "done"
    assert load_token(settings.claude_token_path) == ""


def test_an_existing_sign_in_is_kept(tmp_path, monkeypatch) -> None:
    settings = _from_options(tmp_path, monkeypatch, {"claude_oauth_token": OLD_TOKEN})
    save_token(settings.claude_token_path, NEW_TOKEN)
    assert move_legacy_token(settings) == "kept"
    assert load_token(settings.claude_token_path) == NEW_TOKEN


def test_no_or_a_wrong_old_token_changes_nothing(tmp_path, monkeypatch) -> None:
    assert move_legacy_token(_settings(tmp_path)) == "none"
    wrong = _settings(tmp_path, legacy_claude_token="sk-ant-api03-not-a-plan-token")
    assert move_legacy_token(wrong) == "invalid"
    assert load_token(wrong.claude_token_path) == ""


def test_a_failed_save_is_retried_next_start(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, legacy_claude_token=OLD_TOKEN)

    def boom(path, token):
        raise OSError("read-only")

    monkeypatch.setattr(claude_login, "save_token", boom)
    assert move_legacy_token(settings) == "failed"
    assert not (settings.claude_token_path.parent / MOVED_MARKER).exists()
    monkeypatch.undo()
    assert move_legacy_token(settings) == "moved"


# --- API key and model: quiet fallback ---------------------------------------------------------


def test_old_api_key_and_model_still_work_and_a_sign_in_wins(tmp_path, monkeypatch) -> None:
    settings = _from_options(tmp_path, monkeypatch, {"anthropic_api_key": API_KEY, "claude_model": "claude-opus-5-5"})
    assert runtime_credential(settings) == API_KEY and credential_source(settings) == "settings"
    assert resolve_model(settings, "") == "claude-opus-5-5"
    save_token(settings.claude_token_path, NEW_TOKEN)
    assert runtime_credential(settings) == NEW_TOKEN and credential_source(settings) == "signed-in"


def test_stored_supervisor_options_fill_what_options_json_no_longer_has(tmp_path) -> None:
    # The Supervisor drops fields that left the schema from /data/options.json; its stored options keep them.
    stored = {"claude_oauth_token": OLD_TOKEN, "anthropic_api_key": API_KEY, "claude_model": "claude-opus-5-5"}
    merged = with_legacy_options(_settings(tmp_path), stored)
    assert merged.legacy_claude_token == OLD_TOKEN
    assert merged.anthropic_api_key == API_KEY and merged.claude_model == "claude-opus-5-5"
    assert merged.legacy_claude_options == ("claude_oauth_token", "anthropic_api_key", "claude_model")
    # Environment (or options.json) values win over the stored ones.
    env = _settings(tmp_path, anthropic_api_key="sk-ant-api03-env", claude_model="claude-haiku-5-5")
    kept = with_legacy_options(env, stored)
    assert kept.anthropic_api_key == "sk-ant-api03-env" and kept.claude_model == "claude-haiku-5-5"
    assert kept.legacy_claude_options == ("claude_oauth_token",)
    assert with_legacy_options(env, {}) is env


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_supervisor_options_reads_the_apps_own_info(monkeypatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert supervisor_options() == {}
    seen: dict = {}

    def fake_open(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return _Response(json.dumps({"result": "ok", "data": {"options": {"anthropic_api_key": API_KEY}}}).encode())

    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setattr(legacy_options.urllib.request, "urlopen", fake_open)
    assert supervisor_options() == {"anthropic_api_key": API_KEY}
    assert seen["url"] == "http://supervisor/addons/self/info"
    assert seen["auth"] == "Bearer sup-token" and seen["timeout"] <= 5

    def broken(request, timeout):
        raise OSError("no supervisor")

    monkeypatch.setattr(legacy_options.urllib.request, "urlopen", broken)
    assert supervisor_options() == {}
    monkeypatch.setattr(legacy_options.urllib.request, "urlopen", lambda r, timeout: _Response(b"[]"))
    assert supervisor_options() == {}


def test_one_info_line_without_secrets(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.legacy_options")
    settings = apply_legacy_options(
        _settings(tmp_path), {"claude_oauth_token": OLD_TOKEN, "anthropic_api_key": API_KEY}
    )
    assert load_token(settings.claude_token_path) == OLD_TOKEN
    lines = [r for r in caplog.records if r.name == "app.legacy_options"]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO
    text = lines[0].getMessage()
    assert "claude_oauth_token, anthropic_api_key" in text and "sign-in" in text
    assert OLD_TOKEN not in caplog.text and API_KEY not in caplog.text
    caplog.clear()
    assert apply_legacy_options(_settings(tmp_path / "other"), {}) is not None
    assert not [r for r in caplog.records if r.name == "app.legacy_options"]


# --- the runtime start ------------------------------------------------------------------------


class _Provider:
    def __init__(self, name: str) -> None:
        self.info = ProviderInfo(name, name, True, None)


def test_runtime_start_moves_the_token_and_reads_the_supervisor(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setattr(legacy_options, "supervisor_options", lambda timeout=3.0: {"claude_oauth_token": OLD_TOKEN})
    app = create_app(_settings(tmp_path), {"cursor": _Provider("cursor"), "claude": _Provider("claude")})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        status = client.get("/api/auth/claude").json()
        assert status["credential"] == "signed-in" and status["overridden"] is False
        assert OLD_TOKEN not in json.dumps(status)
    assert load_token(app.state.settings.claude_token_path) == OLD_TOKEN


def test_runtime_start_survives_a_broken_supervisor(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")

    def boom(timeout=3.0):
        raise RuntimeError("down")

    monkeypatch.setattr(legacy_options, "supervisor_options", boom)
    app = create_app(_settings(tmp_path), {"cursor": _Provider("cursor"), "claude": _Provider("claude")})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").json()["ok"] is True


# --- Claude only: no Cursor key needed --------------------------------------------------------


@pytest.mark.parametrize("cursor_key", ["", "   "])
def test_claude_only_runtime_without_cursor_key(tmp_path, monkeypatch, cursor_key) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    settings = _settings(tmp_path, cursor_api_key=cursor_key.strip())
    save_token(settings.claude_token_path, NEW_TOKEN)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        health = client.get("/api/health").json()
        assert health["ok"] is True and health["cursor"] is False
        providers = {item["id"]: item for item in client.get("/api/providers").json()}
        assert providers["cursor"]["available"] is False and providers["cursor"]["reason"]
        if importlib.util.find_spec("claude_agent_sdk") is not None:
            assert providers["claude"]["available"] is True and health["claude"] is True
        cursor = client.get("/api/auth/cursor").json()
        assert cursor["ready"] is False and cursor["credential"] == "none"
        claude = client.get("/api/auth/claude").json()
        assert claude["ready"] is True and claude["credential"] == "signed-in"
