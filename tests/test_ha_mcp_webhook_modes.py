"""HA-MCP inside Core: discovery follows its webhook switch and sign-in mode (issue #2)."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ai_workspace import mcp_resolve
from custom_components.ai_workspace.mcp_client import McpError, ha_mcp_trouble
from custom_components.ai_workspace.mcp_config import with_mcp_auth

WEBHOOK = "/api/webhook/mcp_hook"
DIRECT = "http://127.0.0.1:9584/private_path"


class _Entries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain=None):
        return [e for e in self._entries if domain in (None, e.domain)]


def _hass(**options):
    entry = SimpleNamespace(
        domain="ha_mcp_tools",
        data={"webhook_id": "mcp_hook", "secret_path": "/private_path", "entry_type": "server"},
        options=options,
    )
    return SimpleNamespace(
        config=SimpleNamespace(api=SimpleNamespace(port=8123, use_ssl=False), components={"ha_mcp_tools"}),
        config_entries=_Entries([entry]),
    )


def _found(hass):
    return [url for url in mcp_resolve._entry_mcp_urls(hass) if url.startswith("http://127.0.0.1")]


def test_secret_url_mode_keeps_the_webhook_first() -> None:
    urls = _found(_hass(enable_webhook=True, webhook_auth="none"))
    assert urls == [f"http://127.0.0.1:8123{WEBHOOK}", DIRECT]
    # Older HA-MCP without these options behaves like the secret URL mode.
    assert _found(_hass()) == urls


def test_webhook_off_uses_the_direct_address() -> None:
    assert _found(_hass(enable_webhook=False, webhook_auth="none")) == [DIRECT]


def test_legacy_oauth_webhook_is_never_picked() -> None:
    assert _found(_hass(enable_webhook=True, webhook_auth="legacy")) == [DIRECT]
    hint = mcp_resolve.ha_mcp_setup_hint(_hass(enable_webhook=True, webhook_auth="legacy"))
    assert "Secret webhook URL" in hint


def test_home_assistant_sign_in_prefers_the_direct_address() -> None:
    urls = _found(_hass(enable_webhook=True, webhook_auth="ha_auth"))
    assert urls == [DIRECT, f"http://127.0.0.1:8123{WEBHOOK}"]


def test_own_server_port_is_used() -> None:
    urls = _found(_hass(server_port=9700))
    assert urls[-1] == "http://127.0.0.1:9700/private_path"
    assert 9700 in mcp_resolve._component_ports(_hass(server_port=9700))


class _Resp:
    def __init__(self, status, length):
        self.status, self.content_length = status, length

    def release(self):
        pass


@pytest.mark.parametrize(
    ("status", "length", "works"),
    [(200, 0, False), (200, None, True), (200, 120, True), (401, 0, True), (404, 0, False)],
)
def test_empty_answer_of_an_unknown_webhook_is_not_a_server(monkeypatch, status, length, works) -> None:
    class Session:
        async def post(self, *args, **kwargs):
            return _Resp(status, length)

    monkeypatch.setattr(mcp_resolve, "async_get_clientsession", lambda hass: Session())
    url = f"http://homeassistant:8123{WEBHOOK}"
    assert asyncio.run(mcp_resolve.async_probe_mcp(None, url)) is works


def test_webhook_on_home_assistant_carries_the_login_when_there_is_one() -> None:
    servers = {"mcp": {"type": "http", "url": f"http://homeassistant:8123{WEBHOOK}"}}
    signed = with_mcp_auth(servers, access_token="user-token")
    assert signed["mcp"]["headers"] == {"Authorization": "Bearer user-token"}
    # No login: the secret-URL mode still works, so the connection stays.
    assert with_mcp_auth(servers, access_token="") == servers
    # A webhook on another host never gets the Home Assistant login.
    other = {"mcp": {"type": "http", "url": f"https://elsewhere.example{WEBHOOK}"}}
    assert with_mcp_auth(other, access_token="user-token") == other


def test_failures_explain_what_to_change() -> None:
    assert "Secret webhook URL" in ha_mcp_trouble(McpError("MCP HTTP 401: Unauthorized", 401))
    assert "Remote access via webhook" in ha_mcp_trouble(McpError("MCP response was empty."))
    assert ha_mcp_trouble(McpError("boom")) == ""
    assert ha_mcp_trouble(McpError("x", 401), "use this") == "use this"
