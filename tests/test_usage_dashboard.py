from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.ai_workspace.usage_record import daily_series, model_kpis, usage_range_of


def test_usage_range_of() -> None:
    assert usage_range_of("today") == "today"
    assert usage_range_of("ALL") == "all"
    assert usage_range_of("nope") == "month"
    assert usage_range_of(None) == "month"


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
