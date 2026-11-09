"""A pasted model list fills the picker for servers that do not list their models."""

import asyncio
import json

import pytest

from custom_components.ai_workspace.const import parse_model_list

WANT = ["gpt-5.0", "gpt-5.5", "grok-4.7"]


@pytest.mark.parametrize(
    "text",
    [
        "gpt-5.0, gpt-5.5, grok-4.7",
        "gpt-5.0; gpt-5.5; grok-4.7",
        "gpt-5.0\ngpt-5.5\ngrok-4.7\n",
        "gpt-5.0\r\n\r\ngpt-5.5\r\ngrok-4.7",
        "model\ngpt-5.0\ngpt-5.5\ngrok-4.7",
        "- gpt-5.0\n- gpt-5.5\n- grok-4.7",
        '"gpt-5.0","gpt-5.5","grok-4.7"',
        "gpt-5.0\tgpt-5.5\tgrok-4.7",
        json.dumps(WANT),
        json.dumps({"object": "list", "data": [{"id": m, "object": "model"} for m in WANT]}),
        json.dumps({"models": [{"name": f"models/{m}"} for m in WANT]}),
        "gpt-5.0, gpt-5.5, gpt-5.0, grok-4.7",
    ],
)
def test_pasted_formats(text) -> None:
    assert parse_model_list(text) == WANT


def test_empty_and_stored_lists() -> None:
    assert parse_model_list("") == []
    assert parse_model_list(None) == []
    assert parse_model_list("  \n ; , ") == []
    assert parse_model_list(WANT) == WANT
    # Half-pasted JSON still yields clean names.
    assert parse_model_list('["gpt-5.0", "gpt-5.5"') == ["gpt-5.0", "gpt-5.5"]


def test_form_picks_from_the_list() -> None:
    flow = pytest.importorskip("custom_components.ai_workspace.agent_flow")
    pick = flow.model_with_list
    # The untouched form default is not a real choice: the first pasted model wins.
    assert pick("gpt-5", WANT, "", "gpt-5") == ("gpt-5.0", WANT)
    assert pick("", WANT, "", "gpt-5") == ("gpt-5.0", WANT)
    # A model in the list stays.
    assert pick("grok-4.7", WANT, "", "gpt-5") == ("grok-4.7", WANT)
    # A model the user typed (or kept from before) stays and joins the list.
    assert pick("my-model", WANT, "", "gpt-5") == ("my-model", ["my-model", *WANT])
    assert pick("gpt-5", WANT, "gpt-5", "gpt-5") == ("gpt-5", ["gpt-5", *WANT])
    # No list: nothing changes.
    assert pick("gpt-5", [], "", "gpt-5") == ("gpt-5", [])


def test_chat_switcher_uses_the_list_instead_of_the_server() -> None:
    agents = pytest.importorskip("custom_components.ai_workspace.agents")
    from custom_components.ai_workspace import model_list

    agent = agents.agent_from_mapping(
        "a1",
        "Local",
        {"api_provider": "compatible", "mode": "api", "api_base": "http://x/v1", "model": "gpt-5.5", "models": WANT},
    )
    assert agent.models == tuple(WANT)

    async def boom(*args, **kwargs):
        raise AssertionError("server list must not be asked")

    model_list.async_provider_models, saved = boom, model_list.async_provider_models
    try:
        got = asyncio.run(model_list.async_agent_models(None, agent))
    finally:
        model_list.async_provider_models = saved
    assert got == ["gpt-5.5", "gpt-5.0", "grok-4.7"]


def test_list_sits_in_its_own_folded_section() -> None:
    flow = pytest.importorskip("custom_components.ai_workspace.agent_flow")
    assert flow.submitted_models({"model_list": {"models": "a\nb"}}) == ["a", "b"]
    assert flow.submitted_models({"model_list": {}}) == []
    assert flow.submitted_models(None) == []
    for step, provider in (("compatible", "compatible"), ("cloud", "openai"), ("cursor", "cursor")):
        schema = flow._fields_schema(step, {"api_provider": provider, "models": ["x"]}, [], new=True)
        keys = [str(k) for k in schema.schema]
        assert keys.index("model_list") == keys.index("model") + 1
        folded = schema.schema[next(k for k in schema.schema if str(k) == "model_list")]
        assert folded.options == {"collapsed": True}
        assert "models" not in keys


class _Resp:
    def __init__(self, status, text):
        self.status, self._text = status, text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _check(monkeypatch, status, text):
    api = pytest.importorskip("custom_components.ai_workspace.api_provider")
    sent = {}

    class Session:
        def post(self, url, json=None, headers=None, timeout=None):
            sent.update(url=url, model=json["model"], auth=headers.get("Authorization"))
            return _Resp(status, text)

    monkeypatch.setattr(api, "async_get_clientsession", lambda hass: Session())
    out = asyncio.run(api.async_check_model(None, "compatible", "k", "http://gw/v1/", "gpt-5.5"))
    return out, sent


def test_gateway_says_the_model_is_not_allowed(monkeypatch) -> None:
    body = json.dumps({"error": {"message": "key not allowed to access model. This key can only access models=['grok-4.7']"}})
    out, sent = _check(monkeypatch, 401, body)
    assert out.startswith("key not allowed to access model")
    assert sent == {"url": "http://gw/v1/chat/completions", "model": "gpt-5.5", "auth": "Bearer k"}


def test_model_test_never_blocks_for_other_problems(monkeypatch) -> None:
    assert _check(monkeypatch, 200, "{}")[0] is None
    assert _check(monkeypatch, 500, '{"error": {"message": "model overloaded"}}')[0] is None
    assert _check(monkeypatch, 400, '{"error": {"message": "max_tokens is too small"}}')[0] is None
    assert _check(monkeypatch, 404, '{"detail": "Model grok-9 not found"}')[0] == "Model grok-9 not found"
