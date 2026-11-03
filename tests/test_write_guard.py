"""Agents must not invent placeholder automations, scripts or scenes to get past a write check."""

import asyncio
import json
from pathlib import Path

from app.mcp_proxy import tool_call_id
from custom_components.ai_workspace.write_guard import placeholder_write

_ROOT = Path(__file__).resolve().parents[1]


def _automation(alias: str, actions: list, **extra) -> dict:
    return {"config": {"alias": alias, "triggers": [{"trigger": "time", "at": "00:00:00"}], "actions": actions}, **extra}


_LOG = [{"action": "system_log.write", "data": {"message": "noop"}}]


def test_both_copies_are_the_same() -> None:
    home = (_ROOT / "custom_components/ai_workspace/write_guard.py").read_text()
    assert home == (_ROOT / "ai_workspace/app/write_guard.py").read_text()


def test_the_placeholders_agents_made_are_refused() -> None:
    assert placeholder_write("ha_config_set_automation", _automation("DASHBOARD_WRITE_GUARD_ONLY", _LOG))
    assert placeholder_write("ha_config_set_automation", {"identifier": "__dash_write_bps_ack_only__", "config": {}})
    assert placeholder_write("mcp_ha_config_set_script", {"script_id": "bps_probe", "config": {"sequence": []}})
    yaml = "alias: Placeholder for key\ntriggers: []\nactions: []\n"
    assert placeholder_write("ha_config_set_automation", {"config": yaml})
    assert placeholder_write("ha_config_set_scene", {"config": {"name": "test", "entities": {}}})
    assert placeholder_write("ha_config_set_automation", _automation("Check guard", []))


def test_real_requests_pass() -> None:
    light = [{"action": "light.turn_on", "target": {"entity_id": "light.hall"}}]
    assert not placeholder_write("ha_config_set_automation", _automation("Hallway motion light", light))
    assert not placeholder_write("ha_config_set_automation", _automation("Garage door guard", light))
    assert not placeholder_write("ha_config_set_automation", _automation("Test siren weekly", light))
    assert not placeholder_write("ha_config_set_automation", _automation("Log the boiler state", _LOG))
    assert not placeholder_write("ha_config_set_scene", {"config": {"name": "Movie", "entities": {"light.tv": "on"}}})
    assert not placeholder_write("ha_config_set_dashboard", {"url_path": "placeholder-board", "config": {}})
    assert not placeholder_write("ha_config_get_automation", {"identifier": "automation.noop"})


def test_runtime_refuses_with_a_tool_error_for_that_request() -> None:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "ha_config_set_automation", "arguments": _automation("guard_only", _LOG)}}
    ).encode()
    assert tool_call_id(body) == 7
    assert tool_call_id(b"not json") is None


def test_cloud_agent_gets_a_tool_error_and_nothing_is_written() -> None:
    from custom_components.ai_workspace.api_provider import ApiProvider
    from test_force_tools import _settings

    calls = []

    class Bundle:
        def original_name(self, name):
            return name

        async def call_tool(self, name, args):
            calls.append(name)
            return {"content": [{"type": "text", "text": "ok"}]}

    provider = ApiProvider(None, _settings("openai"), None)
    result = asyncio.run(
        provider._invoke_tool(Bundle(), "ha_config_set_automation", _automation("DASHBOARD_WRITE_GUARD_ONLY", _LOG), None)
    )
    assert result["isError"] is True
    assert "refused" in result["content"][0]["text"]
    assert calls == []


def test_runtime_proxy_answers_the_refusal_without_reaching_ha_mcp(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.mcp_proxy import McpProxy
    from app.settings import Settings

    app = create_app(
        Settings(
            data_dir=tmp_path,
            workspace_dir=tmp_path / "workspace",
            state_dir=tmp_path / "state",
            mcp_config_path=tmp_path / "mcp.json",
            cursor_api_key="",
            model="composer-2.5",
            auth_mode="dev",
            host="127.0.0.1",
            port=8090,
        ),
        providers={},
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        registry = McpProxy()
        client.app.state.runtime = type("Runtime", (), {"proxy": registry})()
        # Nothing listens on port 9: a forwarded call would fail with 502.
        wrapped = registry.wrap({"mcp": {"type": "http", "url": "http://127.0.0.1:9/mcp"}}, "http://test")
        url = wrapped["mcp"]["url"].removeprefix("http://test")
        call = {"name": "ha_config_set_automation", "arguments": _automation("DASHBOARD_WRITE_GUARD_ONLY", _LOG)}
        response = client.post(url, json={"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": call})
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 11
        assert body["result"]["isError"] is True
        assert "refused" in body["result"]["content"][0]["text"]
