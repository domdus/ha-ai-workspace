import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.git_bootstrap import GitBootstrapError, _redact_url, bootstrap_git

GIT = shutil.which("git")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _origin(tmp_path: Path) -> Path:
    src = tmp_path / "origin"
    src.mkdir()
    _git(src, "init")
    _git(src, "config", "user.email", "dev@example.com")
    _git(src, "config", "user.name", "Dev")
    (src / "README.md").write_text("hello\n", encoding="utf-8")
    _git(src, "add", "README.md")
    _git(src, "commit", "-m", "init")
    return src


def test_bootstrap_noop_without_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_REPO", raising=False)
    workspace = tmp_path / "workspace"
    bootstrap_git(workspace)
    assert not workspace.exists() or not any(workspace.iterdir())


def test_bootstrap_skips_existing_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    (workspace / "kept.txt").write_text("stay\n", encoding="utf-8")
    monkeypatch.setenv("GIT_REPO", "git@github.com:example/nope.git")
    bootstrap_git(workspace)
    assert (workspace / "kept.txt").read_text(encoding="utf-8") == "stay\n"


def test_git_token_goes_in_env_not_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    from app.git_bootstrap import _git_env

    monkeypatch.setenv("GIT_TOKEN", "secret-pat")
    monkeypatch.delenv("GIT_SSH_KEY", raising=False)
    env = _git_env("https://github.com/org/repo.git")
    assert "GIT_TOKEN" not in env
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    basic = env["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: Basic ")
    assert base64.b64decode(basic).decode() == "x-access-token:secret-pat"
    assert "GIT_CONFIG_COUNT" not in _git_env("git@github.com:org/repo.git")


def test_redact_url_strips_userinfo() -> None:
    assert _redact_url("https://x-access-token:secret@github.com/org/repo.git") == "https://github.com/org/repo.git"
    assert _redact_url("git@github.com:org/repo.git") == "git@github.com:org/repo.git"


@pytest.mark.skipif(not GIT, reason="git is not installed")
def test_bootstrap_clones_into_empty_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _origin(tmp_path)
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("GIT_REPO", str(src))
    monkeypatch.setenv("GIT_USER_NAME", "AI Workspace")
    monkeypatch.setenv("GIT_USER_EMAIL", "ai-workspace@local")
    monkeypatch.delenv("GIT_SSH_KEY", raising=False)
    monkeypatch.delenv("GIT_TOKEN", raising=False)
    bootstrap_git(workspace)
    assert (workspace / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (workspace / ".git").is_dir()
    name = subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert name.stdout.strip() == "AI Workspace"


@pytest.mark.skipif(not GIT, reason="git is not installed")
def test_bootstrap_clones_over_seed_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _origin(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("seed\n", encoding="utf-8")
    (workspace / ".cursor" / "rules").mkdir(parents=True)
    (workspace / ".cursor" / "rules" / "home-assistant.mdc").write_text("rule\n", encoding="utf-8")
    monkeypatch.setenv("GIT_REPO", str(src))
    monkeypatch.delenv("GIT_SSH_KEY", raising=False)
    monkeypatch.delenv("GIT_TOKEN", raising=False)
    bootstrap_git(workspace)
    assert (workspace / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (workspace / "AGENTS.md").exists()


@pytest.mark.skipif(not GIT, reason="git is not installed")
def test_bootstrap_does_not_clone_over_other_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = _origin(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("mine\n", encoding="utf-8")
    monkeypatch.setenv("GIT_REPO", str(src))
    bootstrap_git(workspace)
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "mine\n"
    assert not (workspace / "README.md").exists()


def test_missing_ssh_key_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_REPO", "git@github.com:example/repo.git")
    monkeypatch.setenv("GIT_SSH_KEY", str(tmp_path / "missing_key"))
    with pytest.raises(GitBootstrapError):
        bootstrap_git(tmp_path / "workspace")
