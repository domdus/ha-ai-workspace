import json
from pathlib import Path

import pytest

from app.mcp_config import (
    McpConfigError,
    load_mcp_servers,
    merge_mcp_servers,
    servers_from_chat_mcp,
)


def test_http_and_stdio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_TOKEN", "secret-token")
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "ha": {"url": "http://ha-mcp:8086/mcp", "headers": {"Authorization": "Bearer ${HA_TOKEN}"}},
                    "files": {"command": "npx", "args": ["-y", "server"], "env": {"HOME": "/tmp"}},
                }
            }
        ),
        encoding="utf-8",
    )
    servers = load_mcp_servers(path)
    assert servers["ha"]["type"] == "http"
    assert servers["ha"]["headers"]["Authorization"] == "Bearer secret-token"
    assert servers["files"]["command"] == "npx"
    assert servers["files"]["args"] == ["-y", "server"]


def test_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_mcp_servers(tmp_path / "missing.json") == {}


def test_rejects_server_without_transport(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"broken": {"note": "nope"}}}), encoding="utf-8")
    with pytest.raises(McpConfigError):
        load_mcp_servers(path)


def test_request_replaces_ha_mcp_and_keeps_extra() -> None:
    file_servers = {
        "home-assistant": {"type": "http", "url": "http://127.0.0.1:8086/mcp"},
        "github": {"type": "http", "url": "http://github-mcp/mcp"},
    }
    request = servers_from_chat_mcp(
        {
            "servers": {
                "mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/mcp_new"}
            }
        }
    )
    merged = merge_mcp_servers(file_servers, request)
    assert "home-assistant" not in merged
    assert merged["mcp"]["url"] == "http://127.0.0.1:8123/api/webhook/mcp_new"
    assert merged["github"]["url"] == "http://github-mcp/mcp"


def test_empty_request_keeps_file_servers() -> None:
    file_servers = {"home-assistant": {"type": "http", "url": "http://old"}}
    assert merge_mcp_servers(file_servers, {}) == file_servers
    assert servers_from_chat_mcp(None) == {}
