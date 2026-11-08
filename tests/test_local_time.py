"""Times an agent passes to Home Assistant tools are read in the house's time zone, not UTC."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.ai_workspace.const import standing_chat_prompt
from custom_components.ai_workspace.local_time import house_zone, time_rule, with_local_offset

BERLIN = ZoneInfo("Europe/Berlin")


def test_times_without_offset_get_the_house_offset() -> None:
    args = {"entity_ids": "switch.pump", "start_time": "2026-11-05T08:00:00", "end_time": "2026-07-05 08:00"}
    out = with_local_offset(args, BERLIN)
    assert out["start_time"] == "2026-11-05T08:00:00+01:00"
    # Summer time is worked out for the date asked about, not for today.
    assert out["end_time"] == "2026-07-05T08:00+02:00"
    assert out["entity_ids"] == "switch.pump"
    assert args["start_time"] == "2026-11-05T08:00:00"
    assert with_local_offset({"start": "2026-11-05"}, BERLIN)["start"] == "2026-11-05T00:00:00+01:00"


def test_other_times_stay_as_they_are() -> None:
    for args in (
        {"start_time": "24h"},
        {"start_time": "2026-11-05T08:00:00+01:00"},
        {"start_time": "2026-11-05T07:00:00Z"},
        {"start_time": None},
        {"message": "2026-11-05T08:00:00"},
        {},
    ):
        assert with_local_offset(args, BERLIN) is args
    args = {"start_time": "2026-11-05T08:00:00"}
    assert with_local_offset(args, None) is args


def test_prompt_line_names_zone_and_offset() -> None:
    winter = time_rule(BERLIN, datetime(2026, 11, 5, 9, 0, tzinfo=BERLIN))
    assert "Europe/Berlin" in winter and "UTC+01:00" in winter and "08:00:00+01:00" in winter
    assert "UTC+02:00" in time_rule(BERLIN, datetime(2026, 7, 5, 9, 0, tzinfo=BERLIN))
    assert time_rule(None) == ""
    assert house_zone(SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Berlin"))) == BERLIN
    assert house_zone(SimpleNamespace(config=SimpleNamespace(time_zone="Not/AZone"))) is None
    assert house_zone(None) is None


def test_cursor_prompt_ends_with_the_time_rule() -> None:
    from test_force_tools import _settings

    rule = time_rule(BERLIN)
    text = standing_chat_prompt(_settings("openai"), language="de", time_zone_rule=rule)
    assert text.endswith(rule)
    assert standing_chat_prompt(_settings("openai"), language="de") == text[: -len(rule)].rstrip()


def test_cloud_agent_prompt_and_tool_calls_use_the_house_zone() -> None:
    from custom_components.ai_workspace.api_provider import ApiProvider
    from test_force_tools import _settings

    hass = SimpleNamespace(config=SimpleNamespace(time_zone="Europe/Berlin"))
    provider = ApiProvider(hass, _settings("openai"), None)
    assert "Europe/Berlin" in provider._system("", "de").rsplit("\n\n", 1)[-1]
    sent: list[dict] = []

    class Bundle:
        def original_name(self, name):
            return name

        async def call_tool(self, name, args):
            sent.append(args)
            return {"content": [{"type": "text", "text": "ok"}]}

    asyncio.run(provider._invoke_tool(Bundle(), "ha_get_history", {"entity_ids": "switch.pump", "start_time": "2026-11-05T08:00:00"}, None))
    assert sent[0]["start_time"] == "2026-11-05T08:00:00+01:00"
    assert "Europe/Berlin" not in ApiProvider(None, _settings("openai"), None)._system("", "de")


def _row(role, content, created_at, events="[]"):
    return SimpleNamespace(role=role, content=content, events=events, created_at=created_at)


def test_history_turns_carry_the_local_time_they_were_sent() -> None:
    from custom_components.ai_workspace.context import as_messages, as_transcript, history_for

    rows = [
        _row("user", "Regnet es gerade?", "2026-10-31T07:14:00+00:00"),
        _row("assistant", "Ja, es regnet.", "2026-10-31T07:14:20+00:00"),
        _row("user", "Wie warm ist es?", "2026-11-05T08:21:00+00:00"),
    ]
    history = history_for(rows, mode="off", model="gpt-5", zone=BERLIN)
    messages = as_messages(history)
    assert messages[0]["content"] == "[Sat 31 Oct 2026, 08:14] Regnet es gerade?"
    assert messages[1]["content"] == "Ja, es regnet."
    assert len(messages) == 2
    assert "User: [Sat 31 Oct 2026, 08:14] Regnet es gerade?" in as_transcript(history)
    # Without a zone, nothing changes.
    assert as_messages(history_for(rows, mode="off", model="gpt-5"))[0]["content"] == "Regnet es gerade?"


def test_digest_lines_keep_the_day() -> None:
    from custom_components.ai_workspace.context import Turn, digest

    when = datetime(2026, 10, 31, 8, 14, tzinfo=BERLIN)
    text = digest([Turn("user", "Regnet es?", "", when), Turn("assistant", "Ja.")], 2000)
    assert "- User (31 Oct 2026): Regnet es?" in text


def test_new_message_is_stamped_like_history() -> None:
    from custom_components.ai_workspace.context import sent_at, stamped
    from custom_components.ai_workspace.local_time import stamped_now

    now = datetime(2026, 11, 5, 9, 21, tzinfo=BERLIN)
    assert stamped_now("Hallo", BERLIN, now) == "[Thu 05 Nov 2026, 09:21] Hallo"
    assert stamped_now("Hallo", None, now) == "Hallo"
    assert stamped("Hallo", sent_at("2026-11-05T08:21:00+00:00", BERLIN)) == stamped_now("Hallo", BERLIN, now)
    assert sent_at("not a time", BERLIN) is None


def test_prompts_explain_stamps_and_reread_saved_config() -> None:
    from custom_components.ai_workspace.const import HOUSE_RULES

    rule = time_rule(BERLIN)
    assert "Never write such a mark yourself" in rule and "not a mistake" in rule
    assert "read it again with a tool" in HOUSE_RULES
