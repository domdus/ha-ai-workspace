"""Loopback MCP URLs of this Home Assistant are rewritten for a Runtime that is not on loopback."""

from types import SimpleNamespace

from custom_components.ai_workspace.mcp_resolve import for_runtime

HASS = SimpleNamespace(config=SimpleNamespace(api=SimpleNamespace(port=8123, use_ssl=False)))
AUTH = {"Authorization": "Bearer user"}


def _servers():
    return {
        "mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/mcp", "headers": dict(AUTH)},
        "ha_mcp": {"type": "http", "url": "http://127.0.0.1:8086/mcp"},
        "catalog": {"type": "http", "url": "http://192.168.1.11:8123/api/ai_workspace/catalog/mcp"},
    }


def test_runtime_app_reaches_core_by_its_hostname() -> None:
    out = for_runtime(_servers(), HASS, "http://8401652b-ai-workspace:8090", "http://homeassistant:8123")
    assert out["mcp"]["url"] == "http://homeassistant:8123/api/mcp"
    assert out["mcp"]["headers"] == AUTH
    # Another port on loopback is not Core; leave it alone.
    assert out["ha_mcp"]["url"] == "http://127.0.0.1:8086/mcp"
    assert out["catalog"]["url"] == "http://192.168.1.11:8123/api/ai_workspace/catalog/mcp"


def test_runtime_on_loopback_keeps_loopback() -> None:
    assert for_runtime(_servers(), HASS, "http://127.0.0.1:8090", "http://192.168.1.11:8123") == _servers()


def test_no_reachable_core_address_keeps_the_urls() -> None:
    assert for_runtime(_servers(), HASS, "http://runtime:8090", "http://127.0.0.1:8123") == _servers()
    assert for_runtime(_servers(), HASS, "", "http://homeassistant:8123") == _servers()


def test_ha_mcp_inside_core_is_reached_by_core_hostname() -> None:
    hass = SimpleNamespace(
        config=SimpleNamespace(api=SimpleNamespace(port=8123, use_ssl=False), components={"ha_mcp_tools"})
    )
    servers = {"mcp": {"type": "http", "url": "http://127.0.0.1:9584/private_abc"}}
    out = for_runtime(servers, hass, "http://8401652b-ai-workspace:8090", "http://homeassistant:8123")
    assert out["mcp"]["url"] == "http://homeassistant:9584/private_abc"
    # Without the integration, port 9584 on loopback is not known to be Core.
    assert for_runtime(servers, HASS, "http://x:8090", "http://homeassistant:8123") == servers


def test_ha_mcp_webhook_on_core_port_keeps_its_path() -> None:
    servers = {"mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/mcp_1?x=1"}}
    out = for_runtime(servers, HASS, "http://x:8090", "http://homeassistant:8123")
    assert out["mcp"]["url"] == "http://homeassistant:8123/api/webhook/mcp_1?x=1"
