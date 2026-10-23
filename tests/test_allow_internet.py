"""Allow internet: web tools for cloud agents, and what they must never reach."""

import asyncio
from pathlib import Path

import pytest

from custom_components.ai_workspace import web_tools
from custom_components.ai_workspace.agents import agent_from_mapping
from custom_components.ai_workspace.api_provider import ApiProvider
from custom_components.ai_workspace.mcp_client import McpError
from custom_components.ai_workspace.models import Settings
from custom_components.ai_workspace.yaml_config import agent_payload


def _settings(**overrides) -> Settings:
    values = {
        "data_dir": Path("/tmp"),
        "workspace_dir": Path("/tmp/workspace"),
        "state_dir": Path("/tmp/state"),
        "cursor_api_key": "",
        "model": "m",
        "mcp_servers": {},
        "api_provider": "openai",
        "api_key": "k",
        "agent_id": "agent-1",
    }
    values.update(overrides)
    return Settings(**values)


def test_off_by_default_for_every_agent() -> None:
    assert agent_from_mapping("a", "Cursor", {"api_provider": "cursor"}).allow_internet is False
    assert agent_from_mapping("b", "OpenAI", {"api_provider": "openai"}).allow_internet is False
    assert agent_payload({"provider": "openai"}, "openai")["data"]["allow_internet"] is False
    assert agent_from_mapping("c", "OpenAI", {"api_provider": "openai", "allow_internet": True}).allow_internet


@pytest.mark.parametrize(
    ("allow", "admin", "has_web"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_cloud_agent_gets_web_tools_only_for_admins_when_allowed(allow, admin, has_web) -> None:
    provider = ApiProvider(None, _settings(allow_internet=allow), None)
    bundle, _skipped, _error = asyncio.run(provider._open_tools(None, "", admin))
    names = {tool["name"] for tool in bundle.tools}
    assert ({"web_fetch", "web_search"} <= names) is has_web


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.10/",
        "http://127.0.0.1:8123/api/states",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost:8123/",
        "http://homeassistant.local:8123/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_local_and_odd_addresses_are_refused(url) -> None:
    with pytest.raises(McpError):
        web_tools._check_url(url)


def test_public_addresses_pass() -> None:
    assert web_tools._check_url("https://www.home-assistant.io/docs/") == "https://www.home-assistant.io/docs/"
    assert web_tools.public_ip("1.1.1.1")
    assert not web_tools.public_ip("10.0.0.5")
    assert not web_tools.public_ip("fd00::1")


def test_resolver_drops_private_answers(monkeypatch) -> None:
    async def fake(self, host, port=0, family=0):
        return [{"host": "10.0.0.2"}, {"host": "93.184.216.34"}] if host == "mixed" else [{"host": "192.168.0.9"}]

    monkeypatch.setattr(web_tools.DefaultResolver, "resolve", fake)
    resolver = web_tools._PublicResolver.__new__(web_tools._PublicResolver)
    assert asyncio.run(resolver.resolve("mixed")) == [{"host": "93.184.216.34"}]
    with pytest.raises(OSError):
        asyncio.run(resolver.resolve("router"))


def test_page_text_skips_scripts_and_keeps_title() -> None:
    parser = web_tools._Text()
    parser.feed(
        "<html><head><title> Prices </title><style>p{}</style></head>"
        "<body><script>var x=1</script><h1>Plans</h1><p>Haiku &amp; Sonnet</p></body></html>"
    )
    assert parser.title.strip() == "Prices"
    assert parser.text() == "Plans\nHaiku & Sonnet"


def test_search_results_unwrap_duckduckgo_links() -> None:
    parser = web_tools._Results()
    parser.feed(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.anthropic.com%2Fmodels&rut=x">'
        "Models overview</a>"
        '<a class="result__snippet" href="#">All Claude <b>model</b> ids</a>'
    )
    assert parser.rows == [
        {"title": "Models overview", "url": "https://docs.anthropic.com/models", "snippet": "All Claude model ids"}
    ]
