"""Reduce token usage and Check the house are per agent, Cursor included."""

from types import MappingProxyType, SimpleNamespace

from custom_components.ai_workspace import _move_tuning_to_agents
from custom_components.ai_workspace.agents import CursorAgent, agent_from_mapping
from custom_components.ai_workspace.const import (
    CHECK_HOUSE_NOTE,
    CONF_CHECK_HOUSE,
    CONF_LOW_TOKEN,
    LOW_TOKEN_PROMPT,
    SUBENTRY_AGENT,
    TOKEN_MODE_EXTREME,
    TOKEN_MODE_LIGHT,
    TOKEN_MODE_MEDIUM,
    TOKEN_MODE_OFF,
    provider_token_mode,
    standing_chat_prompt,
)
from custom_components.ai_workspace.http import handoff_rows


def _cursor(**raw):
    return CursorAgent(agent_from_mapping("c1", "Cursor", {"api_provider": "cursor", **raw}), True, None)


def test_cursor_agent_carries_its_own_level_and_check() -> None:
    assert provider_token_mode(_cursor()) == TOKEN_MODE_OFF
    agent = _cursor(low_token="medium", check_house=False)
    assert provider_token_mode(agent) == TOKEN_MODE_MEDIUM
    assert agent.check_house is False


def test_cursor_standing_prompt_follows_the_level() -> None:
    settings = SimpleNamespace(system_prompt="", house_map=False)
    assert LOW_TOKEN_PROMPT in standing_chat_prompt(settings, mode=TOKEN_MODE_EXTREME)
    full = standing_chat_prompt(settings, mode=TOKEN_MODE_OFF)
    assert len(full) > len(standing_chat_prompt(settings, mode=TOKEN_MODE_MEDIUM))
    assert CHECK_HOUSE_NOTE not in full


def test_fresh_cursor_turns_hand_over_only_the_allowed_history() -> None:
    rows = [SimpleNamespace(role="user" if i % 2 else "assistant", n=i) for i in range(20)]
    rows.insert(15, SimpleNamespace(role="tool", n=-1))
    turns = [row for row in rows if row.role != "tool"]
    assert handoff_rows(rows, TOKEN_MODE_OFF) == rows
    assert handoff_rows(rows, TOKEN_MODE_LIGHT) == rows
    assert handoff_rows(rows, TOKEN_MODE_MEDIUM) == turns[-5:]
    assert handoff_rows(rows, TOKEN_MODE_EXTREME) == turns[-1:]


class _Entries:
    def __init__(self, entry):
        self.entry = entry

    def async_update_subentry(self, entry, sub, data):
        entry.subentries[sub.subentry_id] = SimpleNamespace(**{**vars(sub), "data": MappingProxyType(data)})

    def async_update_entry(self, entry, data=None, options=None):
        entry.data = data if data is not None else entry.data
        entry.options = options if options is not None else entry.options


def _entry(options, *agents):
    subs = {
        sub_id: SimpleNamespace(
            subentry_id=sub_id, subentry_type=SUBENTRY_AGENT, title=sub_id, unique_id=sub_id, data=MappingProxyType(data)
        )
        for sub_id, data in agents
    }
    return SimpleNamespace(data={}, options=dict(options), subentries=subs)


def test_workspace_values_move_onto_cloud_agents_once() -> None:
    entry = _entry(
        {CONF_LOW_TOKEN: "light", CONF_CHECK_HOUSE: False, "keep_chats": 30},
        ("a", {"mode": "api", "api_provider": "openai"}),
        ("c", {"mode": "cursor", "api_provider": "cursor"}),
    )
    hass = SimpleNamespace(config_entries=_Entries(entry))
    _move_tuning_to_agents(hass, entry)
    cloud = entry.subentries["a"].data
    # Light always checked the house before, so the agent keeps doing that.
    assert (cloud[CONF_LOW_TOKEN], cloud[CONF_CHECK_HOUSE]) == (TOKEN_MODE_LIGHT, True)
    assert CONF_LOW_TOKEN not in entry.subentries["c"].data
    assert entry.options == {"keep_chats": 30}
    _move_tuning_to_agents(hass, entry)
    assert entry.subentries["a"].data[CONF_LOW_TOKEN] == TOKEN_MODE_LIGHT


def test_check_only_keeps_each_agents_old_level() -> None:
    entry = _entry(
        {CONF_CHECK_HOUSE: True},
        ("a", {"mode": "api", "api_provider": "openai", CONF_LOW_TOKEN: "medium"}),
        ("b", {"mode": "api", "api_provider": "gemini"}),
    )
    _move_tuning_to_agents(SimpleNamespace(config_entries=_Entries(entry)), entry)
    # The old setting applied the first non-off agent level to every cloud agent.
    assert entry.subentries["a"].data[CONF_LOW_TOKEN] == TOKEN_MODE_MEDIUM
    assert entry.subentries["b"].data[CONF_LOW_TOKEN] == TOKEN_MODE_MEDIUM
    assert entry.subentries["b"].data[CONF_CHECK_HOUSE] is False
