"""HA-MCP rows that point at the wrong server or nowhere move to a working HA-MCP."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.ai_workspace import mcp_resolve

GOOD = "http://homeassistant:9584/private_abc"


class _Entries:
    def __init__(self):
        self.updates = []

    def async_update_subentry(self, entry, sub, data):
        self.updates.append((sub.title, data))


def _setup(monkeypatch, rows, answering, resolved=GOOD):
    async def probe(hass, url, headers=None, timeout=2):
        return url.rstrip("/") in answering

    async def resolve(hass, kind, configured, token=""):
        return resolved

    async def no_sleep(_):
        return None

    monkeypatch.setattr(mcp_resolve, "async_probe_mcp", probe)
    monkeypatch.setattr(mcp_resolve, "async_resolve_mcp_url", resolve)
    monkeypatch.setattr(mcp_resolve.asyncio, "sleep", no_sleep)
    entries = _Entries()
    hass = SimpleNamespace(config_entries=entries)
    subs = {
        str(i): SimpleNamespace(subentry_type="mcp", title=f"row{i}", data=data) for i, data in enumerate(rows)
    }
    entry = SimpleNamespace(subentries=subs)
    asyncio.run(mcp_resolve.async_heal_ha_mcp(hass, entry, "mcp"))
    return entries.updates


def test_ha_mcp_row_on_the_builtin_server_moves_to_ha_mcp(monkeypatch) -> None:
    updates = _setup(
        monkeypatch,
        [{"name": "ha-mcp", "url": "http://127.0.0.1:8123/api/mcp", "mcp_kind": "ha_mcp"}],
        answering={GOOD},
    )
    assert updates == [("row0", {"name": "ha-mcp", "url": GOOD, "mcp_kind": "ha_mcp"})]


def test_unreachable_ha_mcp_row_moves_to_a_working_one(monkeypatch) -> None:
    updates = _setup(
        monkeypatch,
        [{"name": "ha-mcp", "url": "http://127.0.0.1:8086/mcp", "mcp_kind": "ha_mcp"}],
        answering={GOOD},
    )
    assert updates[0][1]["url"] == GOOD


def test_working_row_is_left_alone(monkeypatch) -> None:
    webhook = "http://homeassistant:8123/api/webhook/mcp_1"
    updates = _setup(
        monkeypatch,
        [{"name": "ha-mcp", "url": webhook, "mcp_kind": "ha_mcp"}],
        answering={webhook, GOOD},
    )
    assert updates == []


def test_custom_and_builtin_rows_are_never_touched(monkeypatch) -> None:
    updates = _setup(
        monkeypatch,
        [
            {"name": "x", "url": "http://10.0.0.5:9000/mcp", "mcp_kind": "custom"},
            {"name": "ha", "url": "http://127.0.0.1:8123/api/mcp", "mcp_kind": "ha"},
        ],
        answering={GOOD},
    )
    assert updates == []


def test_nothing_better_found_keeps_the_row(monkeypatch) -> None:
    updates = _setup(
        monkeypatch,
        [{"name": "ha-mcp", "url": "http://127.0.0.1:8123/api/mcp", "mcp_kind": "ha_mcp"}],
        answering=set(),
        resolved="http://127.0.0.1:8123/api/mcp",
    )
    assert updates == []


def test_ha_mcp_app_installed_after_core_started_is_a_candidate(monkeypatch) -> None:
    hassio = pytest.importorskip("homeassistant.components.hassio")
    monkeypatch.setattr(hassio, "get_addons_info", lambda hass: {}, raising=False)
    monkeypatch.setattr(
        hassio, "get_addons_list", lambda hass: [{"slug": "abc_ha_mcp", "state": "started"}], raising=False
    )
    urls = mcp_resolve._hassio_mcp_urls(SimpleNamespace())
    assert "http://abc-ha-mcp:9583/mcp" in urls
