"""A Cursor chat finds the Runtime again when it moved (for example to the beta App)."""

import asyncio
from types import SimpleNamespace

import pytest

http = pytest.importorskip("custom_components.ai_workspace.http")

OLD = "http://335cd779-ai-workspace:8090"
NEW = "http://8401652b-ai-workspace:8090"


class _Resp:
    def __init__(self, status):
        self.status = status

    def release(self):
        pass


def _setup(monkeypatch, alive: set[str], found: str):
    data = {"runtime_url": OLD, "providers": {}}
    hass = SimpleNamespace(data={http.DOMAIN: data})
    binds = []

    class Session:
        async def get(self, url, headers=None, timeout=None):
            if not any(url.startswith(base) for base in alive):
                raise OSError("unreachable")
            return _Resp(200)

    async def bind(hass_, bucket, force=False):
        binds.append(force)
        bucket["runtime_url"] = found
        return found

    async def create(hass_, user_id, session_id, agent_id):
        return None

    monkeypatch.setattr(http, "async_get_clientsession", lambda hass_: Session())
    monkeypatch.setattr(http, "async_bind_runtime", bind)
    monkeypatch.setattr(http, "_create_runtime_session", create)
    monkeypatch.setattr(http, "_runtime_headers_for", lambda *a, **k: {})
    return hass, data, binds


def test_sync_follows_the_runtime_to_its_new_address(monkeypatch) -> None:
    hass, data, binds = _setup(monkeypatch, alive={NEW}, found=NEW)
    chat = SimpleNamespace(id="s1", agent_id="")
    assert asyncio.run(http._ensure_runtime_session(hass, "u1", chat)) is True
    assert binds == [True]
    assert data["runtime_url"] == NEW


def test_no_new_address_still_fails_once(monkeypatch) -> None:
    hass, _data, binds = _setup(monkeypatch, alive=set(), found=OLD)
    chat = SimpleNamespace(id="s1", agent_id="")
    assert asyncio.run(http._ensure_runtime_session(hass, "u1", chat)) is False
    assert binds == [True]


def test_failure_names_pairing_when_that_is_the_reason() -> None:
    pairing = SimpleNamespace(kind="cursor", info=SimpleNamespace(available=False, reason="Pairing with the AI Workspace Runtime app. Try again in a minute."))
    hass = SimpleNamespace(data={http.DOMAIN: {"providers": {"c": pairing}}})
    assert http._runtime_unreachable(hass).startswith("Pairing")
    hass.data[http.DOMAIN]["providers"] = {}
    assert "could not sync" in http._runtime_unreachable(hass)


def test_unreachable_runtime_is_a_connection_error(monkeypatch) -> None:
    hass, _data, _binds = _setup(monkeypatch, alive=set(), found=OLD)
    chat = SimpleNamespace(id="s1", agent_id="")

    async def first():
        return await http._runtime_chat(hass, "u1", chat, "Jetzt?").__anext__()

    event = asyncio.run(first())
    assert event["type"] == "error"
    assert event["connection"] is True
