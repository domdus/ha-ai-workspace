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
        "catalog": {"type": "http", "url": "http://homeassistant:8123/api/ai_workspace/catalog/mcp"},
        "mcp": {"type": "http", "url": "http://homeassistant:8123/api/webhook/mcp_x"},
    }
    out = mod.with_mcp_auth(servers, access_token="ha-token")
    assert out["catalog"]["headers"]["Authorization"] == "Bearer ha-token"
    assert "headers" not in out["mcp"]


def test_with_mcp_auth_adds_bearer_to_builtin_mcp() -> None:
    servers = {"mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/mcp"}}
    out = mod.with_mcp_auth(servers, access_token="ha-token")
    assert out["mcp"]["headers"]["Authorization"] == "Bearer ha-token"


def test_with_mcp_auth_drops_house_map_without_token() -> None:
    servers = {
        "catalog": {"type": "http", "url": "http://homeassistant:8123/api/ai_workspace/catalog/mcp"},
        "mcp": {"type": "http", "url": "http://homeassistant:8123/api/webhook/mcp_x"},
    }
    out = mod.with_mcp_auth(servers, access_token="")
    assert "catalog" not in out
    assert "mcp" in out


def test_home_assistant_token_stays_on_home_assistant() -> None:
    servers = {"evil": {"type": "http", "url": "https://example.com/api/mcp"}}
    out = mod.with_mcp_auth(servers, access_token="ha-token")
    assert "headers" not in out["evil"]


def test_own_host_gets_the_token() -> None:
    servers = {"mcp": {"type": "http", "url": "http://192.168.1.5:8123/api/mcp"}}
    out = mod.with_mcp_auth(servers, access_token="ha-token", ha_hosts={"192.168.1.5"})
    assert out["mcp"]["headers"]["Authorization"] == "Bearer ha-token"


def test_row_token_is_kept() -> None:
    servers = {"mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/mcp", "headers": {"Authorization": "Bearer row"}}}
    out = mod.with_mcp_auth(servers, access_token="ha-token")
    assert out["mcp"]["headers"]["Authorization"] == "Bearer row"
