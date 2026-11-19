"""Built-in agent instructions on disk follow new releases, edited copies stay as they are."""

import hashlib

from app import prompt


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_house_rule_skips_general_questions() -> None:
    text = prompt.CURSOR_IDENTITY
    assert "Call a Home Assistant tool only when the user asks for live house data" in text
    assert "Plant care, gardening" in text
    assert "Before you answer any question about this house" not in text
    assert "only if you are actually calling a tool in this answer" in text
    assert "Link only real Home Assistant items returned by a tool in this chat." in text


def test_missing_files_are_written(tmp_path) -> None:
    prompt.write_workspace_defaults(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == prompt.CURSOR_IDENTITY
    rule = tmp_path / ".cursor" / "rules" / "home-assistant.mdc"
    assert rule.read_text(encoding="utf-8") == prompt.CURSOR_RULE


def test_unedited_old_default_is_replaced(tmp_path, monkeypatch) -> None:
    old = "old built-in text\n"
    monkeypatch.setattr(prompt, "_OLD_IDENTITY_SHA256", frozenset({_sha(old)}))
    (tmp_path / "AGENTS.md").write_text(old, encoding="utf-8")
    prompt.write_workspace_defaults(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == prompt.CURSOR_IDENTITY


def test_edited_file_is_kept(tmp_path) -> None:
    mine = prompt.CURSOR_IDENTITY + "\nMy own rule.\n"
    (tmp_path / "AGENTS.md").write_text(mine, encoding="utf-8")
    prompt.write_workspace_defaults(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == mine


def test_current_defaults_are_not_listed_as_old() -> None:
    assert _sha(prompt.CURSOR_IDENTITY) not in prompt._OLD_IDENTITY_SHA256
    assert _sha(prompt.CURSOR_RULE) not in prompt._OLD_RULE_SHA256
