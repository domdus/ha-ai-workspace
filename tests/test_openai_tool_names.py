"""OpenAI function names stay unique, routable, and at most 64 characters."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "mcp_config.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_mcp_config_names", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_short_names_stay_unchanged():
    mcp = _load()
    routes = mcp.public_tool_names([("home-assistant", ["ha_search", "ha_get_state"])])
    assert routes["ha_search"] == ("home-assistant", "ha_search")
    assert routes["ha_get_state"] == ("home-assistant", "ha_get_state")


def test_long_name_is_capped_and_still_routes():
    mcp = _load()
    tool = "ha_config_set_dashboard_" + ("n" * 50)
    public = f"home-assistant-extra__{tool}"
    assert len(public) > mcp.OPENAI_TOOL_NAME_MAX
    name = mcp.sanitize_openai_tool_name(public, "home-assistant-extra", tool)
    assert len(name) <= mcp.OPENAI_TOOL_NAME_MAX
    routes = mcp.public_tool_names([("home-assistant-extra", [tool])])
    openai_name, route = next(iter(routes.items()))
    assert len(openai_name) <= mcp.OPENAI_TOOL_NAME_MAX
    assert route == ("home-assistant-extra", tool)
    assert openai_name != tool


def test_two_long_names_with_the_same_prefix_keep_distinct_hashes():
    mcp = _load()
    one = "x" * 70
    two = "x" * 69 + "y"
    used: set[str] = set()
    left = mcp.sanitize_openai_tool_name(one, "server", one, used)
    used.add(left)
    right = mcp.sanitize_openai_tool_name(two, "server", two, used)
    assert left != right
    assert len(left) <= mcp.OPENAI_TOOL_NAME_MAX
    assert len(right) <= mcp.OPENAI_TOOL_NAME_MAX


def test_two_servers_same_tool_get_short_prefixes_under_64():
    mcp = _load()
    routes = mcp.public_tool_names(
        [
            ("home-assistant", ["list_entities", "ha_search"]),
            ("HA-MCP", ["list_entities", "ha_get_live_context"]),
        ]
    )
    assert routes["ha__list_entities"] == ("home-assistant", "list_entities")
    assert routes["hamcp__list_entities"] == ("HA-MCP", "list_entities")
    assert routes["ha_search"] == ("home-assistant", "ha_search")
    assert routes["ha_get_live_context"] == ("HA-MCP", "ha_get_live_context")
    assert all(len(name) <= mcp.OPENAI_TOOL_NAME_MAX for name in routes)


def test_primary_and_ha_mcp_aliases_are_short():
    mcp = _load()
    assert mcp.connection_prefix("mcp") == "ha"
    assert mcp.connection_prefix("home-assistant") == "ha"
    assert mcp.connection_prefix("HA-MCP") == "hamcp"


def test_invalid_openai_names_are_reported():
    mcp = _load()
    assert mcp.openai_tool_name_errors(["ha_search"]) == []
    assert mcp.openai_tool_name_errors(["x" * 65]) == ["x" * 65]


def test_local_hass_mcp_url_is_not_ha_mcp():
    mcp = _load()
    assert mcp.is_local_hass_mcp_url("http://127.0.0.1:8123/api/mcp")
    assert mcp.is_local_hass_mcp_url("http://localhost:8123/api/mcp")
    assert not mcp.is_local_hass_mcp_url("http://ha-mcp:8086/mcp")
    assert not mcp.is_local_hass_mcp_url("http://127.0.0.1:8086/mcp")
