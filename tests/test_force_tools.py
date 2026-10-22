import asyncio
from pathlib import Path

from custom_components.ai_workspace.api_provider import ApiProvider
from custom_components.ai_workspace.models import Settings

_TOOL = {"name": "GetLiveContext", "description": "Live states", "inputSchema": {"type": "object", "properties": {}}}


def _settings(provider: str) -> Settings:
    return Settings(
        data_dir=Path("/tmp"),
        workspace_dir=Path("/tmp/workspace"),
        state_dir=Path("/tmp/state"),
        cursor_api_key="",
        model="m",
        mcp_servers={},
        api_provider=provider,
        api_key="k",
    )


class _Bundle:
    tools = [_TOOL]

    def original_name(self, name):
        return name

    async def call_tool(self, name, args):
        return {"content": [{"type": "text", "text": "3 automations"}]}


def _run(provider: ApiProvider, loop, force: bool) -> list[dict]:
    payloads: list[dict] = []
    anthropic = loop == "anthropic"

    async def fake_round(_http, _url, _headers, payload):
        payloads.append(dict(payload))
        if len(payloads) == 1:
            if anthropic:
                yield "message", [{"type": "tool_use", "id": "t1", "name": "GetLiveContext", "input": {}}]
            else:
                call = {"id": "c1", "type": "function", "function": {"name": "GetLiveContext", "arguments": "{}"}}
                yield "message", {"role": "assistant", "content": None, "tool_calls": [call]}
            return
        yield "text", "Three."
        yield "message", [] if anthropic else {"role": "assistant", "content": "Three."}

    async def collect():
        if anthropic:
            provider._anthropic_round = fake_round
            gen = provider._anthropic(None, [], "How many automations?", _Bundle(), "", [], "en", True, force)
        else:
            provider._openai_round = fake_round
            gen = provider._openai(None, [], "How many automations?", _Bundle(), "", [], "en", True, force)
        return [event async for event in gen]

    asyncio.run(collect())
    return payloads


def test_openai_forces_only_the_first_round() -> None:
    payloads = _run(ApiProvider(None, _settings("openai"), None), "openai", True)
    assert payloads[0]["tool_choice"] == "required"
    assert "tool_choice" not in payloads[1]


def test_anthropic_forces_only_the_first_round() -> None:
    payloads = _run(ApiProvider(None, _settings("anthropic"), None), "anthropic", True)
    assert payloads[0]["tool_choice"] == {"type": "any"}
    assert "tool_choice" not in payloads[1]


def test_no_force_leaves_the_choice_to_the_model() -> None:
    payloads = _run(ApiProvider(None, _settings("openai"), None), "openai", False)
    assert "tool_choice" not in payloads[0]


def test_check_house_defaults_on_and_can_be_turned_off() -> None:
    from custom_components.ai_workspace.agents import agent_from_mapping

    assert agent_from_mapping("a", "OpenAI", {"api_provider": "openai"}).check_house is True
    assert agent_from_mapping("b", "OpenAI", {"api_provider": "openai", "check_house": False}).check_house is False
    assert _settings("openai").check_house is True


def test_refused_force_is_dropped_and_remembered() -> None:
    provider = ApiProvider(None, _settings("compatible"), None)
    bodies: list[dict] = []

    class _Resp:
        def __init__(self, status, text):
            self.status = status
            self._text = text

        async def text(self):
            return self._text

        def release(self):
            pass

    class _Http:
        async def post(self, url, json, headers, timeout):
            bodies.append(dict(json))
            if "tool_choice" in json:
                return _Resp(400, '{"error": {"message": "tool_choice required is not supported"}}')
            return _Resp(200, "{}")

    resp = asyncio.run(provider._open(_Http(), "u", {}, {"model": "m", "tool_choice": "required"}))
    assert resp.status == 200
    assert "tool_choice" not in bodies[-1]
    assert provider._force is False
