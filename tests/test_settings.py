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
    assert written["mcpServers"]["mcp"]["url"] == "http://ha-mcp:8086/mcp"
    assert written["mcpServers"]["mcp"]["headers"]["Authorization"] == "Bearer mcp-secret"
    assert written["mcpServers"]["github"]["url"] == "http://github-mcp/mcp"
