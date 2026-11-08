"""The agent's own git pull/push uses the same token as the clone, without storing it."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

from app import git_bootstrap  # noqa: E402


def _git(*args, cwd, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def test_token_is_read_from_the_environment_when_git_asks(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "work"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    monkeypatch.setenv("GIT_TOKEN", "secret-token")
    monkeypatch.delenv("GIT_SSH_KEY", raising=False)
    for _ in range(2):  # every start; must not stack helpers
        git_bootstrap._configure_credentials("git", repo, "https://github.com/example/repo.git")
    config = (repo / ".git" / "config").read_text()
    assert "secret-token" not in config
    assert config.count("helper =") == 1
    env = {**os.environ, "GIT_TOKEN": "secret-token", "GIT_TERMINAL_PROMPT": "0"}
    out = subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        env=env,
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "username=x-access-token" in out
    assert "password=secret-token" in out


def test_ssh_key_is_used_for_later_pushes(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "work"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    monkeypatch.delenv("GIT_TOKEN", raising=False)
    monkeypatch.setenv("GIT_SSH_KEY", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----")
    git_bootstrap._configure_credentials("git", repo, "git@github.com:example/repo.git")
    command = _git("config", "core.sshCommand", cwd=repo)
    assert "ssh -i " in command and "IdentitiesOnly=yes" in command
    key = Path(command.split("-i ", 1)[1].split()[0])
    assert key.is_file() and "abc" in key.read_text()
