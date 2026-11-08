"""Cloud agents start with a few tools and load the rest when they need them."""

import asyncio
from pathlib import Path

from custom_components.ai_workspace.api_provider import ApiProvider, _openai_tools
from custom_components.ai_workspace.models import Settings
from custom_components.ai_workspace.tool_loading import LOAD_TOOLS, ToolPicker, pick_tools, used_tool_names


def _tool(name, tag, size=10):
    return {
        "name": name,
        "description": f"{name} " + "d" * size,
        "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
        "_meta": {"fastmcp": {"tags": [tag]}},
    }


TOOLS = [
    _tool("ha_search", "Search & Discovery"),
    _tool("ha_get_state", "Search & Discovery"),
    _tool("ha_call_service", "Service & Device Control"),
    _tool("ha_get_skill_guide", "System"),
    _tool("ha_restart", "System"),
    _tool("ha_config_get_automation", "Automations"),
    _tool("ha_config_set_automation", "Automations"),
    _tool("ha_config_get_dashboard", "Dashboards"),
    _tool("ha_config_set_dashboard", "Dashboards"),
    _tool("ha_get_history", "History & Statistics"),
] + [_tool(f"ha_zone_{i}", "Zones") for i in range(25)]


def _names(tools):
    return [tool["name"] for tool in tools]


def test_small_tool_sets_are_sent_whole() -> None:
    assert pick_tools(TOOLS[:10], "hi") is None


def test_starter_set_has_core_tools_and_the_topic() -> None:
    picker = pick_tools(TOOLS, "Füge eine Karte zum Dashboard hinzu")
    names = _names(picker.visible())
    assert {"ha_search", "ha_get_state", "ha_call_service", "ha_get_skill_guide"} <= set(names)
    assert {"ha_config_get_dashboard", "ha_config_set_dashboard"} <= set(names)
    assert "ha_config_set_automation" not in names
    assert "ha_zone_0" not in names
    assert names[-1] == LOAD_TOOLS


def test_untagged_tools_are_always_sent() -> None:
    plain = [{"name": f"other_{i}", "description": "", "inputSchema": {}} for i in range(5)]
    picker = pick_tools(TOOLS + plain, "hi")
    assert {"other_0", "other_4"} <= set(_names(picker.visible()))


def test_load_by_name_or_group_appends_at_the_end() -> None:
    picker = ToolPicker(TOOLS, "Licht an")
    before = _names(picker.visible())[:-1]
    reply = picker.load({"names": ["Automations", "ha_restart", "nope"]})
    assert "ha_config_set_automation" in reply and "nope" in reply
    after = _names(picker.visible())
    assert after[: len(before)] == before
    assert {"ha_config_get_automation", "ha_config_set_automation", "ha_restart"} <= set(after)


def test_follow_up_turn_keeps_the_group_it_used() -> None:
    class Row:
        role = "assistant"
        events = '[{"name": "ha_config_get_dashboard", "phase": "end"}, {"name": "load_tools"}]'

    used = used_tool_names([Row()])
    assert used == {"ha_config_get_dashboard"}
    picker = ToolPicker(TOOLS, "ja mach das", used)
    assert "ha_config_set_dashboard" in _names(picker.visible())


def test_load_tools_keeps_its_full_list_after_slimming() -> None:
    picker = ToolPicker(TOOLS, "hi")
    sent = _openai_tools(picker.visible(), 40)
    load = next(tool for tool in sent if tool["function"]["name"] == LOAD_TOOLS)
    assert "ha_zone_24" in load["function"]["description"]


class _Bundle:
    def __init__(self, picker):
        self.tools = TOOLS
        self.picker = picker
        self.calls = []

    def original_name(self, name):
        return name

    async def call_tool(self, name, args):
        self.calls.append(name)
        return {"content": [{"type": "text", "text": "ok"}]}


def _settings() -> Settings:
    return Settings(
        data_dir=Path("/tmp"),
        workspace_dir=Path("/tmp/workspace"),
        state_dir=Path("/tmp/state"),
        cursor_api_key="",
        model="m",
        mcp_servers={},
        api_provider="openai",
        api_key="k",
    )


def test_openai_loop_loads_then_calls_without_a_tool_chip_for_loading() -> None:
    provider = ApiProvider(None, _settings(), None)
    bundle = _Bundle(ToolPicker(TOOLS, "Licht an"))
    payloads = []

    async def fake_round(_http, _url, _headers, payload):
        payloads.append(payload)
        call = None
        if len(payloads) == 1:
            call = {"id": "c1", "type": "function", "function": {"name": LOAD_TOOLS, "arguments": '{"names": ["Automations"]}'}}
        elif len(payloads) == 2:
            call = {"id": "c2", "type": "function", "function": {"name": "ha_config_get_automation", "arguments": "{}"}}
        if call:
            yield "message", {"role": "assistant", "content": None, "tool_calls": [call]}
            return
        yield "text", "Done."
        yield "message", {"role": "assistant", "content": "Done."}

    async def collect():
        provider._openai_round = fake_round
        gen = provider._openai(None, [], "Licht an", bundle, "", [], "en", True, False)
        return [event async for event in gen]

    events = asyncio.run(collect())
    first = [tool["function"]["name"] for tool in payloads[0]["tools"]]
    second = [tool["function"]["name"] for tool in payloads[1]["tools"]]
    assert "ha_config_get_automation" not in first
    assert "ha_config_get_automation" in second
    assert bundle.calls == ["ha_config_get_automation"]
    chips = [event["name"] for event in events if event.get("type") == "tool"]
    assert LOAD_TOOLS not in chips
    ends = [event for event in events if event.get("type") == "tool" and event.get("phase") == "end"]
    assert ends[0]["note"].startswith("ha_config_get_automation() → ")
