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
    store.prune_sessions("user-1", keep=1)
    leftover = store.create_session("user-1", "openai")
    store.add_usage(user_id="user-1", session_id=leftover.id, agent_id="gpt-1", total_tokens=3, cost_usd=0.0)
    dropped = store.prune_sessions("user-1", keep=1)
    assert session.id in dropped or leftover.id in dropped
    remaining = store.summarize_usage(session_id=session.id)
    if session.id in dropped:
        assert remaining["turns"] == 0
    store.close()
