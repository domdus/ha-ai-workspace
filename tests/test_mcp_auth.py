import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "custom_components" / "ai_workspace" / "mcp_config.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_mcp_config_auth", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load()


def test_with_mcp_auth_adds_bearer_to_house_map() -> None:
    servers = {
        "house-map": {"type": "http", "url": "http://homeassistant:8123/api/ai_workspace/house_map/mcp"},
        "mcp": {"type": "http", "url": "http://homeassistant:8123/api/webhook/mcp_x"},
    }
    out = mod.with_mcp_auth(servers, access_token="ha-token", mcp_kind="ha_mcp")
    assert out["house-map"]["headers"]["Authorization"] == "Bearer ha-token"
    assert "headers" not in out["mcp"]


def test_with_mcp_auth_drops_house_map_without_token() -> None:
    servers = {
        "house-map": {"type": "http", "url": "http://homeassistant:8123/api/ai_workspace/house_map/mcp"},
        "mcp": {"type": "http", "url": "http://homeassistant:8123/api/webhook/mcp_x"},
    }
    out = mod.with_mcp_auth(servers, access_token="", mcp_token="", mcp_kind="ha_mcp")
    assert "house-map" not in out
    assert "mcp" in out
