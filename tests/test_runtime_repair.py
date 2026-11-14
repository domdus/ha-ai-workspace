"""The Runtime App lost its options (reinstalled or reset) while AI Workspace still has a token saved.

Cursor agents were greyed out for good: the integration only paired the App when no token was saved.
"""

import asyncio
from types import SimpleNamespace

import pytest

discovery = pytest.importorskip("custom_components.ai_workspace.discovery")
from custom_components.ai_workspace.models import ProviderInfo  # noqa: E402

URL = "http://8401652b-ai-workspace:8090"
SAVED = "saved-token"


class _Hass:
    def __init__(self, bucket):
        self.data = {discovery.DOMAIN: bucket}
        self.tasks = []

    def async_create_background_task(self, coro, name):
        self.tasks.append(asyncio.ensure_future(coro))


def _setup(monkeypatch, app_token: str, *, entry_token: str = SAVED):
    state = {"runtime": app_token, "pairs": []}
    cursor = SimpleNamespace(kind="cursor", info=ProviderInfo("c", "Cursor", False, None))
    entry = SimpleNamespace(data={}, options={discovery.CONF_RUNTIME_TOKEN: entry_token} if entry_token else {})
    bucket = {"entry": entry, "providers": {"c": cursor}}
    hass = _Hass(bucket)

    async def resolve(hass_, configured):
        return URL

    async def health(hass_, base):
        return {"version": discovery.MIN_RUNTIME, "token_required": True, "claude": False}

    async def accepted(hass_, base, token):
        return bool(token) and token == state["runtime"]

    async def addon_token(hass_, slug):
        return state["runtime"]

    async def pair(hass_, slug, base, wanted=""):
        state["pairs"].append(wanted)
        state["runtime"] = wanted or "fresh"
        return state["runtime"]

    monkeypatch.setattr(discovery, "async_resolve_runtime_url", resolve)
    monkeypatch.setattr(discovery, "async_runtime_health", health)
    monkeypatch.setattr(discovery, "async_token_accepted", accepted)
    monkeypatch.setattr(discovery, "_async_addon_token", addon_token)
    monkeypatch.setattr(discovery, "_async_pair_addon", pair)
    monkeypatch.setattr(discovery, "_hassio_addon", lambda hass_: ("8401652b_ai_workspace", URL))
    return hass, bucket, cursor, state


async def _bind(hass, bucket):
    await discovery.async_bind_runtime(hass, bucket, force=True)
    await asyncio.gather(*hass.tasks)
    hass.tasks.clear()


def test_reset_app_gets_the_saved_token_back(monkeypatch) -> None:
    hass, bucket, cursor, state = _setup(monkeypatch, app_token="")

    async def run():
        await _bind(hass, bucket)
        assert state["pairs"] == [SAVED]
        assert cursor.info.available, cursor.info.reason
        assert bucket["runtime_token"] == SAVED
        # Next probe: all good, no second pairing.
        await _bind(hass, bucket)
        assert state["pairs"] == [SAVED] and cursor.info.available

    asyncio.run(run())


def test_app_with_its_own_token_wins_over_a_stale_saved_one(monkeypatch) -> None:
    hass, bucket, cursor, state = _setup(monkeypatch, app_token="app-token")

    async def run():
        await _bind(hass, bucket)
        assert state["pairs"] == []
        assert cursor.info.available and bucket["runtime_token"] == "app-token"

    asyncio.run(run())


def test_failed_pairing_does_not_restart_the_app_every_probe(monkeypatch) -> None:
    hass, bucket, cursor, state = _setup(monkeypatch, app_token="")

    async def broken(hass_, slug, base, wanted=""):
        state["pairs"].append(wanted)
        return ""

    monkeypatch.setattr(discovery, "_async_pair_addon", broken)

    async def run():
        await _bind(hass, bucket)
        await _bind(hass, bucket)
        assert state["pairs"] == [SAVED]
        assert not cursor.info.available and cursor.info.reason == discovery.BAD_TOKEN

    asyncio.run(run())


def test_no_saved_token_still_pairs_with_a_new_one(monkeypatch) -> None:
    hass, bucket, cursor, state = _setup(monkeypatch, app_token="", entry_token="")

    async def run():
        await _bind(hass, bucket)
        assert state["pairs"] == [""] and cursor.info.available and bucket["runtime_token"] == "fresh"

    asyncio.run(run())
