import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_store():
    path = ROOT / "custom_components" / "ai_workspace" / "store.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_store", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Store


Store = _load_store()


def test_get_session_rejects_empty_ids(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    created = store.create_session("user-1", "cursor")
    assert store.get_session("user-1", created.id) is not None
    assert store.get_session("user-1", None) is None  # type: ignore[arg-type]
    assert store.get_session(None, created.id) is None  # type: ignore[arg-type]
    assert store.import_session(None, "x", "cursor", "T", None, "", "") is False  # type: ignore[arg-type]
    assert store.import_session("user-1", None, "cursor", "T", None, "", "") is False  # type: ignore[arg-type]
    store.close()


def test_usage_turns_sum_and_prune(tmp_path: Path) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("user-1", "cursor")
    store.add_usage(
        user_id="user-1",
        session_id=session.id,
        agent_id="cursor-1",
        agent="Cursor",
        provider="cursor",
        model="composer-2.5",
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cost_usd=0.0123,
        cost_source="estimate",
        origin="chat",
    )
    store.add_usage(
        user_id="user-1",
        session_id=session.id,
        agent_id="gpt-1",
        agent="OpenAI",
        provider="openai",
        model="gpt-5-mini",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_usd=None,
        cost_source="",
        origin="assist",
    )
    all_rows = store.summarize_usage()
    assert all_rows["turns"] == 2
    assert all_rows["total_tokens"] == 135
    assert all_rows["cost_usd"] == 0.0123
    assert all_rows["missing_cost"] is True
    by_agent = {row["agent_id"]: row for row in store.usage_by_agent()}
    assert by_agent["cursor-1"]["cost_usd"] == 0.0123
    last = store.last_usage(session_id=session.id)
    assert last is not None
    assert last["model"] == "gpt-5-mini"
    assert last["origin"] == "assist"
    store.delete_session("user-1", session.id)
    assert store.get_session("user-1", session.id) is None
    after_delete = store.summarize_usage()
    assert after_delete["turns"] == 2
    assert after_delete["total_tokens"] == 135
    assert after_delete["cost_usd"] == 0.0123
    leftover = store.create_session("user-1", "openai")
    store.add_usage(user_id="user-1", session_id=leftover.id, agent_id="gpt-1", total_tokens=3, cost_usd=0.0)
    dropped = store.prune_sessions("user-1", keep=1)
    assert leftover.id not in dropped
    after_prune = store.summarize_usage()
    assert after_prune["turns"] == 3
    assert after_prune["total_tokens"] == 138
    store.close()


def test_usage_by_model_and_daily_events(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    store = Store(tmp_path / "models.sqlite")
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    store.add_usage(
        user_id="user-1",
        session_id="s1",
        agent_id="claude-1",
        agent="Claude",
        provider="anthropic",
        model="claude-sonnet-4-5",
        prompt_tokens=2000,
        completion_tokens=200,
        cache_read_tokens=1500,
        total_tokens=2200,
        cost_usd=0.40,
        origin="chat",
        created_at=now.isoformat(),
    )
    store.add_usage(
        user_id="user-1",
        session_id="s1",
        agent_id="claude-1",
        agent="Claude",
        provider="anthropic",
        model="claude-sonnet-4-5",
        prompt_tokens=800,
        completion_tokens=100,
        total_tokens=900,
        cost_usd=0.10,
        origin="chat",
        created_at=(now - timedelta(days=2)).isoformat(),
    )
    store.add_usage(
        user_id="user-1",
        session_id="s2",
        agent_id="gpt-1",
        agent="OpenAI",
        provider="openai",
        model="gpt-5-mini",
        prompt_tokens=400,
        completion_tokens=80,
        total_tokens=480,
        cost_usd=0.02,
        origin="chat",
        created_at=now.isoformat(),
    )
    store.add_usage(
        user_id="user-1",
        session_id="s2",
        agent_id="gpt-1",
        agent="OpenAI",
        provider="openai",
        model="gpt-4o-mini-tts",
        characters=40,
        cost_usd=0.0001,
        origin="tts",
        created_at=now.isoformat(),
    )
    models = {row["model"]: row for row in store.usage_by_model()}
    assert "gpt-4o-mini-tts" not in models
    assert models["claude-sonnet-4-5"]["turns"] == 2
    assert models["claude-sonnet-4-5"]["tokens_per_turn"] == 1550.0
    assert models["claude-sonnet-4-5"]["cost_per_turn"] == 0.25
    assert models["gpt-5-mini"]["cost_per_1k"] == 0.041667
    events = store.usage_events(since=(now - timedelta(days=3)).isoformat())
    assert len(events) == 3
    claude = store.summarize_usage(agent_id="claude-1")
    assert claude["turns"] == 2 and claude["cost_usd"] == 0.5
    sonnet = store.usage_by_model(model="claude-sonnet-4-5")
    assert len(sonnet) == 1 and sonnet[0]["turns"] == 2
    gpt_events = store.usage_events(model="gpt-5-mini")
    assert len(gpt_events) == 1
    choices = store.usage_filter_choices()
    assert {row["id"] for row in choices["agents"]} == {"claude-1", "gpt-1"}
    assert "claude-sonnet-4-5" in choices["models"]
    assert set(store.usage_filter_choices(agent_id="gpt-1")["models"]) == {"gpt-4o-mini-tts", "gpt-5-mini"}
    store.close()


def test_claude_exclusive_cache_counts_in_summaries(tmp_path: Path) -> None:
    store = Store(tmp_path / "claude-cache.sqlite")
    counted = 36 + 280912 + 73502 + 2987
    with store._lock:
        store._conn.execute(
            """
            INSERT INTO usage_turns (
                created_at, user_id, session_id, agent_id, agent, provider, model,
                prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens,
                total_tokens, cost_usd, origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-10-20T12:00:00+00:00",
                "user-1",
                "s-claude",
                "claude-1",
                "Claude",
                "anthropic",
                "claude-sonnet-5-5",
                36,
                2987,
                280912,
                73502,
                3023,
                0.241716,
                "chat",
            ),
        )
        store._conn.commit()
    summary = store.summarize_usage(agent_id="claude-1")
    assert summary["total_tokens"] == counted
    assert summary["cache_read_tokens"] == 280912
    assert summary["cache_write_tokens"] == 73502
    events = store.usage_events()
    assert events[0]["total_tokens"] == counted
    last = store.last_usage(session_id="s-claude")
    assert last is not None
    assert last["total_tokens"] == counted
    models = store.usage_by_model(model="claude-sonnet-5-5")
    assert models[0]["total_tokens"] == counted
    assert models[0]["tokens_per_turn"] == float(counted)
    store.close()


def test_usage_chat_choices_skip_deleted_sessions(tmp_path: Path) -> None:
    store = Store(tmp_path / "chats.sqlite")
    keep = store.create_session("user-1", "anthropic")
    gone = store.create_session("user-1", "anthropic")
    store.rename_session("user-1", keep.id, "Kitchen")
    store.add_usage(
        user_id="user-1",
        session_id=keep.id,
        agent_id="claude-1",
        agent="Claude",
        model="claude-sonnet-5-5",
        total_tokens=100,
        cost_usd=0.4,
        origin="chat",
    )
    store.add_usage(
        user_id="user-1",
        session_id=gone.id,
        agent_id="claude-1",
        agent="Claude",
        model="claude-sonnet-5-5",
        total_tokens=50,
        cost_usd=0.2,
        origin="chat",
    )
    store.delete_session("user-1", gone.id)
    chats = store.usage_chat_choices(user_id="user-1")
    assert [row["id"] for row in chats] == [keep.id]
    assert chats[0]["title"] == "Kitchen"
    remaining = store.summarize_usage()
    assert remaining["turns"] == 2
    assert remaining["cost_usd"] == 0.6
    scoped = store.summarize_usage(session_id=keep.id)
    assert scoped["turns"] == 1
    assert scoped["cost_usd"] == 0.4
    store.close()


def test_usage_tts_origin_and_characters(tmp_path: Path) -> None:
    store = Store(tmp_path / "tts.sqlite")
    store.add_usage(
        user_id="user-1",
        session_id="chat-1",
        agent_id="openai-1",
        agent="OpenAI",
        provider="openai",
        model="gpt-4o-mini-tts",
        characters=40,
        cost_usd=0.000024,
        cost_source="estimate",
        origin="tts",
    )
    speech = store.summarize_usage(origin="tts")
    chat = store.summarize_usage(origin="chat")
    assert speech["turns"] == 1
    assert speech["characters"] == 40
    assert speech["total_tokens"] == 0
    assert chat["turns"] == 0
    last = store.last_usage()
    assert last is not None
    assert last["origin"] == "tts"
    store.close()
