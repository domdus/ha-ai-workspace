import json
from pathlib import Path

from app.settings import Settings


def test_addon_options_write_mcp_json(tmp_path: Path, monkeypatch) -> None:
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps(
            {
                "cursor_api_key": "crsr_test",
                "model": "composer-2.5",
                "mcp_url": "http://ha-mcp:8086/mcp",
                "mcp_token": "mcp-secret",
                "mcp_config": json.dumps({"mcpServers": {"github": {"url": "http://github-mcp/mcp"}}}),
            }
        ),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    monkeypatch.setenv("ADDON_OPTIONS", str(options))
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.delenv("MCP_CONFIG_PATH", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    settings = Settings.from_env()
    written = json.loads(settings.mcp_config_path.read_text(encoding="utf-8"))
    assert settings.cursor_api_key == "crsr_test"
    assert settings.auth_mode == "ingress"
    assert written["mcpServers"]["home-assistant"]["url"] == "http://ha-mcp:8086/mcp"
    assert written["mcpServers"]["home-assistant"]["type"] == "streamable-http"
    assert written["mcpServers"]["home-assistant"]["headers"]["Authorization"] == "Bearer mcp-secret"
    assert written["mcpServers"]["github"]["url"] == "http://github-mcp/mcp"


def test_mcp_url_bootstraps_empty_config_path(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    empty = tmp_path / "empty-mcp.json"
    empty.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("MCP_CONFIG_PATH", str(empty))
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8123/api/webhook/mcp_test")
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    monkeypatch.delenv("ADDON_OPTIONS", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    settings = Settings.from_env()
    written = json.loads(settings.mcp_config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["home-assistant"]["url"] == "http://127.0.0.1:8123/api/webhook/mcp_test"
    assert written["mcpServers"]["home-assistant"]["type"] == "streamable-http"


def test_mcp_url_updates_stale_home_assistant(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    path = data / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {"url": "http://github-mcp/mcp"},
                    "home-assistant": {"type": "streamable-http", "url": "http://127.0.0.1:8086/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8123/api/webhook/mcp_test")
    monkeypatch.delenv("MCP_CONFIG_PATH", raising=False)
    monkeypatch.delenv("ADDON_OPTIONS", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    settings = Settings.from_env()
    written = json.loads(settings.mcp_config_path.read_text(encoding="utf-8"))
    assert written["mcpServers"]["github"]["url"] == "http://github-mcp/mcp"
    assert written["mcpServers"]["home-assistant"]["url"] == "http://127.0.0.1:8123/api/webhook/mcp_test"
    assert written["mcpServers"]["home-assistant"]["type"] == "streamable-http"
