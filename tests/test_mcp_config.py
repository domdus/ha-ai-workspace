import json
from pathlib import Path

import pytest

from app.mcp_config import McpConfigError, load_mcp_servers


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
