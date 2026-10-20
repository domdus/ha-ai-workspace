from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from custom_components.ai_workspace.const import DOMAIN
from custom_components.ai_workspace.store import Store
from custom_components.ai_workspace.usage_record import (
    daily_series,
    dashboard_payload,
    model_kpis,
    parse_usage_day,
    usage_day_text,
    usage_range_of,
)


def test_usage_range_of() -> None:
    assert usage_range_of("today") == "today"
    assert usage_range_of("ALL") == "all"
    assert usage_range_of("custom") == "custom"
    assert usage_range_of("nope") == "month"
    assert usage_range_of(None) == "month"


def test_parse_usage_day() -> None:
    hass = SimpleNamespace(config=SimpleNamespace(time_zone="UTC"))
    assert usage_day_text("2026-10-19T12:00:00") == "2026-10-19"
    assert usage_day_text("nope") == ""
    assert parse_usage_day(hass, "2026-10-19") == "2026-10-19T00:00:00+00:00"
    assert parse_usage_day(hass, "2026-10-19", end=True) == "2026-10-20T00:00:00+00:00"
    assert parse_usage_day(hass, "nope") is None


def test_daily_series_fills_empty_days() -> None:
    tz = ZoneInfo("UTC")
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    events = [
        {"created_at": "2026-10-01T12:00:00+00:00", "total_tokens": 100, "cost_usd": 0.05},
        {"created_at": "2026-10-03T08:00:00+00:00", "total_tokens": 50, "cost_usd": 0.01},
        {"created_at": "2026-10-03T09:00:00+00:00", "total_tokens": 25, "cost_usd": None},
    ]
    days = daily_series(events, start=start, days=4, tz=tz)
    assert [row["date"] for row in days] == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    assert days[0]["turns"] == 1 and days[0]["cost_usd"] == 0.05
    assert days[1]["turns"] == 0 and days[1]["total_tokens"] == 0
    assert days[2]["turns"] == 2 and days[2]["total_tokens"] == 75 and days[2]["cost_usd"] == 0.01


def test_model_kpis_picks_spend_used_efficient_lean() -> None:
    models = [
        {
            "model": "claude-sonnet-4-5",
            "turns": 4,
            "total_tokens": 8000,
            "cost_usd": 1.2,
            "tokens_per_turn": 2000,
            "cost_per_turn": 0.3,
        },
        {
            "model": "gpt-5-mini",
            "turns": 10,
            "total_tokens": 3000,
            "cost_usd": 0.2,
            "tokens_per_turn": 300,
            "cost_per_turn": 0.02,
        },
        {
            "model": "llama3.2",
            "turns": 6,
            "total_tokens": 1200,
            "cost_usd": 0.0,
            "tokens_per_turn": 200,
            "cost_per_turn": 0.0,
        },
    ]
    kpis = model_kpis(models)
    assert kpis["most_spend"]["model"] == "claude-sonnet-4-5"
    assert kpis["most_used"]["model"] == "gpt-5-mini"
    assert kpis["most_efficient"]["model"] == "llama3.2"
    assert kpis["leanest"]["model"] == "llama3.2"


def test_dashboard_payload_filters(tmp_path) -> None:
    store = Store(tmp_path / "usage.sqlite")
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    store.add_usage(
        user_id="user-1",
        session_id="s1",
        agent_id="claude-1",
        agent="Claude",
        provider="anthropic",
        model="claude-sonnet-4-5",
        total_tokens=2200,
        cost_usd=0.40,
        origin="chat",
        created_at=now.isoformat(),
    )
    store.add_usage(
        user_id="user-1",
        session_id="s2",
        agent_id="gpt-1",
        agent="OpenAI",
        provider="openai",
        model="gpt-5-mini",
        total_tokens=480,
        cost_usd=0.02,
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
        total_tokens=900,
        cost_usd=0.10,
        origin="chat",
        created_at=(now - timedelta(days=10)).isoformat(),
    )
    hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="UTC"),
        data={DOMAIN: {"settings": SimpleNamespace(track_usage=True), "providers": {}}},
    )
    bounds = ("2026-10-19T00:00:00+00:00", "2026-10-20T00:00:00+00:00", "2026-10-01T00:00:00+00:00")
    with patch("custom_components.ai_workspace.usage_record.day_bounds", return_value=bounds):
        month = dashboard_payload(hass, store, range_key="month", agent_id="claude-1")
        custom = dashboard_payload(hass, store, since="2026-10-18", until="2026-10-19")
        swapped = dashboard_payload(hass, store, since="2026-10-19", until="2026-10-01")
    assert month["range"] == "month"
    assert month["totals"]["today"]["turns"] == 1
    assert month["totals"]["month"]["turns"] == 2
    assert {row["model"] for row in month["models"]} == {"claude-sonnet-4-5"}
    assert month["filters"]["agent_id"] == "claude-1"
    assert "claude-sonnet-4-5" in month["filters"]["models"]
    assert custom["range"] == "custom"
    assert custom["totals"]["selected"]["turns"] == 2
    assert custom["filters"]["since"] == "2026-10-18"
    assert custom["filters"]["until"] == "2026-10-19"
    assert swapped["filters"]["since"] == "2026-10-01"
    assert swapped["filters"]["until"] == "2026-10-19"
    store.close()


def test_dashboard_payload_for_one_user_hides_other_users(tmp_path) -> None:
    store = Store(tmp_path / "usage.sqlite")
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc).isoformat()
    store.add_usage(
        user_id="admin", session_id="a1", agent_id="claude-1", agent="Claude", model="claude-sonnet-4-5",
        total_tokens=5000, cost_usd=2.0, origin="chat", created_at=now,
    )
    store.add_usage(
        user_id="kid", session_id="k1", agent_id="gpt-1", agent="OpenAI", model="gpt-5-mini",
        total_tokens=100, cost_usd=0.01, origin="chat", created_at=now,
    )
    hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="UTC"),
        data={DOMAIN: {"settings": SimpleNamespace(track_usage=True), "providers": {}}},
    )
    bounds = ("2026-10-19T00:00:00+00:00", "2026-10-20T00:00:00+00:00", "2026-10-01T00:00:00+00:00")
    with patch("custom_components.ai_workspace.usage_record.day_bounds", return_value=bounds):
        mine = dashboard_payload(hass, store, range_key="all", user_id="kid")
        everyone = dashboard_payload(hass, store, range_key="all")
        other_chat = dashboard_payload(hass, store, range_key="all", user_id="kid", session_id="a1")
    assert mine["totals"]["all"]["turns"] == 1
    assert mine["totals"]["all"]["total_tokens"] == 100
    assert {row["model"] for row in mine["models"]} == {"gpt-5-mini"}
    assert [row["id"] for row in mine["agents"]] == ["gpt-1"]
    assert "claude-sonnet-4-5" not in mine["filters"]["models"]
    assert everyone["totals"]["all"]["turns"] == 2
    assert other_chat["session"]["turns"] == 0
    assert other_chat["totals"]["all"]["turns"] == 0
    store.close()


def test_dashboard_chat_filter_scopes_totals(tmp_path) -> None:
    store = Store(tmp_path / "usage.sqlite")
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc).isoformat()
    kitchen = store.create_session("user-1", "anthropic")
    other = store.create_session("user-1", "openai")
    store.rename_session("user-1", kitchen.id, "Kitchen leak")
    store.add_usage(
        user_id="user-1",
        session_id=kitchen.id,
        agent_id="claude-1",
        agent="Claude",
        model="claude-sonnet-5-5",
        total_tokens=2200,
        cost_usd=0.40,
        origin="chat",
        created_at=now,
    )
    store.add_usage(
        user_id="user-1",
        session_id=other.id,
        agent_id="gpt-1",
        agent="OpenAI",
        model="gpt-5-mini",
        total_tokens=480,
        cost_usd=0.02,
        origin="chat",
        created_at=now,
    )
    hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="UTC"),
        data={DOMAIN: {"settings": SimpleNamespace(track_usage=True), "providers": {}}},
    )
    bounds = ("2026-10-19T00:00:00+00:00", "2026-10-20T00:00:00+00:00", "2026-10-01T00:00:00+00:00")
    with patch("custom_components.ai_workspace.usage_record.day_bounds", return_value=bounds):
        filtered = dashboard_payload(hass, store, range_key="all", session_id=kitchen.id)
        everyone = dashboard_payload(hass, store, range_key="all")
    assert filtered["totals"]["all"]["turns"] == 1
    assert filtered["totals"]["all"]["cost_usd"] == 0.4
    assert filtered["filters"]["session_id"] == kitchen.id
    assert {row["id"] for row in filtered["filters"]["chats"]} == {kitchen.id, other.id}
    assert everyone["totals"]["all"]["turns"] == 2
    store.close()
