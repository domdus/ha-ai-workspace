"""One history builder for cloud agents and cold Cursor agents."""

import json
from types import SimpleNamespace

from custom_components.ai_workspace import context as ctx
from custom_components.ai_workspace.const import (
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_LIGHT,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
)


def _row(role, content, events=None):
    return SimpleNamespace(role=role, content=content, events=json.dumps(events or []))


def _chat(pairs: int, size: int = 200):
    rows = []
    for i in range(pairs):
        rows.append(_row("user", f"question {i} " + "q" * size))
        rows.append(_row("assistant", f"answer {i} " + "a" * size))
    rows.append(_row("user", "now"))
    return rows


def test_window_comes_from_setting_then_model_then_provider() -> None:
    assert ctx.context_window("gpt-5", manual=50_000) == 50_000
    assert ctx.context_window("gpt-5-mini") == 400_000
    assert ctx.context_window("claude-sonnet-4-5") == 200_000
    assert ctx.context_window("llama3.2:3b", "ollama") == 128_000
    assert ctx.context_window("phi4", "ollama") == 32_000
    assert ctx.context_window("something-new") == ctx.FALLBACK_WINDOW


def test_budget_shrinks_with_the_token_level_and_small_windows() -> None:
    big = 400_000
    assert ctx.history_budget(TOKEN_MODE_OFF, big) > ctx.history_budget(TOKEN_MODE_LIGHT, big)
    assert ctx.history_budget(TOKEN_MODE_LIGHT, big) > ctx.history_budget(TOKEN_MODE_MEDIUM, big) > 0
    assert ctx.history_budget(TOKEN_MODE_EXTREME, big) == 0
    assert ctx.history_budget(TOKEN_MODE_OFF, 32_000) < ctx.history_budget(TOKEN_MODE_OFF, big)


def test_short_chats_go_in_whole() -> None:
    rows = _chat(3)
    history = ctx.history_for(rows, mode=TOKEN_MODE_OFF, model="gpt-5")
    assert len(history.turns) == 6
    assert not history.digest
    assert history.turns[-1][1].startswith("answer 2")


def test_long_reply_is_not_cut_at_2000_characters() -> None:
    yaml = "automation:\n" + "\n".join(f"  - id: item_{i}\n    alias: Item {i}" for i in range(80))
    rows = [_row("user", "show the yaml"), _row("assistant", yaml), _row("user", "now")]
    history = ctx.history_for(rows, mode=TOKEN_MODE_OFF, model="gpt-5")
    assert len(yaml) > 2000
    assert history.turns[-1][1] == yaml


def test_huge_message_keeps_start_and_end() -> None:
    text = "START " + "x" * 50_000 + " END"
    out = ctx.fit_text(text, 2_000)
    assert out.startswith("START")
    assert out.endswith("END")
    assert "characters left out" in out
    assert len(out) < 2_100


def test_old_turns_leave_in_blocks_so_the_start_stays_put() -> None:
    starts = []
    for pairs in range(30, 60):
        history = ctx.history_for(_chat(pairs, 800), mode=TOKEN_MODE_MEDIUM, model="gpt-5")
        assert history.digest.startswith(ctx.DIGEST_LEAD)
        assert history.dropped % ctx.BLOCK == 0
        starts.append(history.dropped)
    # The start moves only now and then, not every turn.
    moves = sum(1 for a, b in zip(starts, starts[1:]) if a != b)
    assert moves < len(starts) / 2


def test_digest_mentions_left_out_questions() -> None:
    history = ctx.history_for(_chat(40, 800), mode=TOKEN_MODE_MEDIUM, model="gpt-5")
    assert history.dropped
    assert "- User: question" in history.digest
    messages = ctx.as_messages(history)
    assert messages[0]["role"] == "user"
    assert messages[0]["content"].startswith(ctx.DIGEST_LEAD)


def test_tool_notes_ride_along_with_the_reply() -> None:
    events = [
        {"name": "ha_search", "phase": "start", "text": "Calling ha_search..."},
        {"name": "ha_search", "phase": "end", "note": "ha_search(query=Bewässerung) → 3 results"},
    ]
    rows = [_row("user", "Welche Bewässerung?"), _row("assistant", "Drei.", events), _row("user", "now")]
    history = ctx.history_for(rows, mode=TOKEN_MODE_OFF, model="gpt-5")
    assert history.turns[-1][1] == "Drei.\n\n[tools: ha_search(query=Bewässerung) → 3 results]"


def test_failed_replies_and_the_current_question_stay_out() -> None:
    rows = [
        _row("user", "List automations"),
        _row("assistant", "MCP HTTP 401", [{"type": "error", "message": "MCP HTTP 401"}]),
        _row("user", "Again"),
    ]
    turns = ctx.chat_turns(rows)
    assert [t.text for t in turns] == ["List automations"]


def test_tool_call_note_skips_keys_and_big_payloads() -> None:
    note = ctx.tool_call_note(
        "ha_config_set_automation",
        {"identifier": "balcony", "BestPracticeKey": "I-HAVE-READ", "config": {"alias": "x"}},
        '{"success": true, "entity_id": "automation.balcony"}',
    )
    assert note.startswith("ha_config_set_automation(identifier=balcony)")
    assert "I-HAVE-READ" not in note
    assert "success" in note
