"""Extra MCP connections stay a list of named servers, and tool names stay unique."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "mcp_config.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_mcp_config", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_saved_servers_keep_the_first_and_add_the_rest():
    mcp = _load()
    servers = mcp.mcp_servers_from_saved(
        "http://127.0.0.1:8123/api/mcp",
        "secret",
        [{"name": "directus", "url": "https://cms.example/mcp", "token": "cms-key"}],
    )
    assert set(servers) == {"mcp", "directus"}
    assert servers["mcp"]["url"] == "http://127.0.0.1:8123/api/mcp"
    assert servers["mcp"]["headers"]["Authorization"] == "Bearer secret"
    assert servers["directus"]["url"] == "https://cms.example/mcp"
    assert servers["directus"]["headers"]["Authorization"] == "Bearer cms-key"


def test_reserved_name_does_not_replace_the_home_assistant_server():
    mcp = _load()
    assert mcp.server_slug("Home Assistant", "https://example/mcp") == "home-assistant-extra"
    servers = mcp.mcp_servers_from_saved(
        "http://127.0.0.1:8123/api/mcp",
        "",
        [{"name": "mcp", "url": "https://example/mcp", "token": ""}],
    )
    assert "mcp" in servers
    assert servers["mcp"]["url"] == "http://127.0.0.1:8123/api/mcp"
    assert "mcp-2" in servers


def test_tool_names_stay_plain_until_they_clash():
    mcp = _load()
    routes = mcp.public_tool_names([("home-assistant", ["list"]), ("directus", ["list", "read"])])
    assert routes["ha__list"] == ("home-assistant", "list")
    assert routes["directus__list"] == ("directus", "list")
    assert routes["read"] == ("directus", "read")
    assert all(len(name) <= mcp.OPENAI_TOOL_NAME_MAX for name in routes)
