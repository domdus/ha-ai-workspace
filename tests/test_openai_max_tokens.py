import asyncio
from pathlib import Path

from custom_components.ai_workspace.api_provider import (
    ApiProvider,
    _openai_output_limit_key,
    _rewrite_output_limit,
)
from custom_components.ai_workspace.const import TOKEN_MODE_MEDIUM
from custom_components.ai_workspace.models import Settings

_GPT5_ERROR = (
    "Unsupported parameter: 'max_tokens' is not supported with this model. "
    "Use 'max_completion_tokens' instead."
)


def _settings(**overrides) -> Settings:
    values = {
        "data_dir": Path("/tmp"),
        "workspace_dir": Path("/tmp/workspace"),
        "state_dir": Path("/tmp/state"),
        "cursor_api_key": "",
        "model": "gpt-5",
        "mcp_servers": {},
        "api_provider": "openai",
        "api_key": "k",
        "token_mode": TOKEN_MODE_MEDIUM,
    }
    values.update(overrides)
    return Settings(**values)


class _Bundle:
    tools: list = []

    def original_name(self, name):
        return name


def test_gpt5_family_uses_max_completion_tokens() -> None:
    assert _openai_output_limit_key("gpt-5") == "max_completion_tokens"
    assert _openai_output_limit_key("gpt-5-mini") == "max_completion_tokens"
    assert _openai_output_limit_key("openai/gpt-5") == "max_completion_tokens"
    assert _openai_output_limit_key("o3-mini") == "max_completion_tokens"
    assert _openai_output_limit_key("gpt-4o") == "max_tokens"
    assert _openai_output_limit_key("gpt-4.1") == "max_tokens"
    assert _openai_output_limit_key("llama3.2") == "max_tokens"


def test_rewrite_swaps_max_tokens_when_the_model_asks() -> None:
    body = {"max_tokens": 256}
    assert _rewrite_output_limit(body, _GPT5_ERROR) is True
    assert body == {"max_completion_tokens": 256}


def test_rewrite_does_not_undo_the_fix() -> None:
    body = {"max_completion_tokens": 256}
    assert _rewrite_output_limit(body, _GPT5_ERROR) is False
    assert body == {"max_completion_tokens": 256}


def test_openai_medium_sends_max_completion_tokens_for_gpt5() -> None:
    payloads: list[dict] = []
    provider = ApiProvider(None, _settings(), None)

    async def fake_round(_http, _url, _headers, payload):
        payloads.append(dict(payload))
        yield "message", {"role": "assistant", "content": "Hi"}

    async def collect():
        provider._openai_round = fake_round
        return [event async for event in provider._openai(None, [], "Hi", _Bundle(), "", [], "en", True, False)]

    asyncio.run(collect())
    assert payloads[0]["max_completion_tokens"] == 1024
    assert "max_tokens" not in payloads[0]


def test_ollama_medium_keeps_max_tokens() -> None:
    payloads: list[dict] = []
    provider = ApiProvider(None, _settings(api_provider="ollama", model="llama3.2"), None)

    async def fake_round(_http, _url, _headers, payload):
        payloads.append(dict(payload))
        yield "message", {"role": "assistant", "content": "Hi"}

    async def collect():
        provider._openai_round = fake_round
        return [event async for event in provider._openai(None, [], "Hi", _Bundle(), "", [], "en", True, False)]

    asyncio.run(collect())
    assert payloads[0]["max_tokens"] == 1024
    assert "max_completion_tokens" not in payloads[0]


def test_open_retries_with_max_completion_tokens() -> None:
    provider = ApiProvider(None, _settings(), None)
    bodies: list[dict] = []

    class _Resp:
        def __init__(self, status, text):
            self.status = status
            self._text = text

        async def text(self):
            return self._text

        def release(self):
            pass

    class _Http:
        async def post(self, url, json, headers, timeout):
            bodies.append(dict(json))
            if "max_tokens" in json:
                return _Resp(400, f'{{"error": {{"message": "{_GPT5_ERROR}"}}}}')
            return _Resp(200, "{}")

    resp = asyncio.run(provider._open(_Http(), "u", {}, {"model": "gpt-5", "max_tokens": 256}))
    assert resp.status == 200
    assert bodies[0]["max_tokens"] == 256
    assert bodies[-1]["max_completion_tokens"] == 256
    assert "max_tokens" not in bodies[-1]
