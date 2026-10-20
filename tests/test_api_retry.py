import asyncio
from pathlib import Path

import pytest

from custom_components.ai_workspace.api_provider import ApiError, ApiProvider, _retry_wait
from custom_components.ai_workspace.const import TOKEN_MODE_MEDIUM
from custom_components.ai_workspace.models import Settings


def _settings() -> Settings:
    return Settings(
        data_dir=Path("/tmp"),
        workspace_dir=Path("/tmp/workspace"),
        state_dir=Path("/tmp/state"),
        cursor_api_key="",
        model="gpt-5",
        mcp_servers={},
        api_provider="openai",
        api_key="k",
        token_mode=TOKEN_MODE_MEDIUM,
    )


class _Resp:
    def __init__(self, status, text, headers=None):
        self.status = status
        self.headers = headers or {}
        self._text = text

    async def text(self):
        return self._text

    def release(self):
        pass


def test_retry_wait_503_defaults_to_one_second():
    assert _retry_wait(_Resp(503, "", {}), "") == 1.0
    assert _retry_wait(_Resp(503, "", {"Retry-After": "3"}), "") == 3.0
    assert _retry_wait(_Resp(500, "", {}), "") is None


def test_open_retries_503_then_succeeds(monkeypatch):
    provider = ApiProvider(None, _settings(), None)
    statuses = [503, 503, 200]
    sleeps: list[float] = []

    class _Http:
        async def post(self, url, json, headers, timeout):
            return _Resp(statuses.pop(0), "high demand")

    async def fake_sleep(wait):
        sleeps.append(wait)

    monkeypatch.setattr("custom_components.ai_workspace.api_provider.asyncio.sleep", fake_sleep)
    resp = asyncio.run(provider._open(_Http(), "u", {}, {"model": "m"}))
    assert resp.status == 200
    assert sleeps == [1.0, 1.0]


def test_open_exhausted_503_raises_503(monkeypatch):
    provider = ApiProvider(None, _settings(), None)

    class _Http:
        async def post(self, url, json, headers, timeout):
            return _Resp(503, '{"error": {"message": "unavailable"}}')

    async def fake_sleep(wait):
        return None

    monkeypatch.setattr("custom_components.ai_workspace.api_provider.asyncio.sleep", fake_sleep)
    with pytest.raises(ApiError) as err:
        asyncio.run(provider._open(_Http(), "u", {}, {"model": "m"}, attempts=2))
    assert err.value.status == 503
