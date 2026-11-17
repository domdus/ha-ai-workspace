"""OpenAI agents with "Use Codex (runtime)": agent model, form fields, and Sign in with ChatGPT (device code).

The flow steps run for real against a fake Runtime (no network), as in test_claude_signin_flow.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

flow_mod = pytest.importorskip("custom_components.ai_workspace.agent_flow")
from custom_components.ai_workspace import local_text, runtime_auth  # noqa: E402
from custom_components.ai_workspace.agents import CodexAgent, agent_from_mapping  # noqa: E402
from custom_components.ai_workspace.runtime_auth import RuntimeAuthError  # noqa: E402

DEVICE_URL = "https://auth.openai.com/codex/device"


def test_openai_agent_with_the_switch_is_a_codex_runtime_agent() -> None:
    agent = agent_from_mapping("a1", "", {"api_provider": "openai", "use_codex_runtime": True, "codex_api_key": "sk-x"})
    assert agent.mode == "codex" and agent.provider == "openai" and agent.use_codex_runtime
    provider = CodexAgent(agent, True, None)
    assert provider.kind == "codex" and provider.api_key == "sk-x" and provider.info.provider == "codex"
    cloud = agent_from_mapping("a2", "", {"api_provider": "openai", "api_key": "sk-y"})
    assert cloud.mode == "api" and not cloud.use_codex_runtime
    assert flow_mod._title("openai", {"Codex"}, "codex") == "Codex 2"


def test_the_switch_shows_the_codex_section_without_speech() -> None:
    def keys(current):
        schema = flow_mod._fields_schema("cloud", {"api_provider": "openai", **current}, [], new=True, models=[])
        return {str(key) for key in schema.schema}

    cloud = keys({})
    runtime = keys({"use_codex_runtime": True})
    assert "api_key" in cloud and "codex_runtime" not in cloud and "assist_tts" in cloud
    assert "codex_runtime" in runtime and "api_key" not in runtime
    assert "assist_tts" not in runtime and "assist_stt" not in runtime


class FakeRuntime:
    def __init__(self, *, ready=False, chatgpt=False):
        self.ready = ready or chatgpt
        self.signed_in = {"mode": "chatgpt", "plan": "plus", "saved_at": "2026-11-17T10:00:00+00:00"} if chatgpt else None
        self.logins: dict[str, str] = {}
        self.waits: list[int] = []

    def status(self):
        return {
            "engine": "codex",
            "ready": self.ready,
            "credential": "signed-in" if self.signed_in else ("settings" if self.ready else "none"),
            "signed_in": self.signed_in,
            "login": {"supported": True, "flow": "device_code", "available": True},
        }

    def install(self, monkeypatch):
        async def status(hass, base, token, engine):
            assert engine == "codex"
            return self.status()

        async def start(hass, base, token, engine):
            login_id = f"L{len(self.logins) + 1}"
            self.logins[login_id] = "awaiting_code"
            return {"id": login_id, "status": "awaiting_code", "url": DEVICE_URL, "user_code": "ABCD-1234", "flow": "device_code"}

        async def state(hass, base, token, engine, login_id, wait=0):
            self.waits.append(wait)
            if login_id not in self.logins:
                raise RuntimeAuthError("expired")
            out = {"id": login_id, "status": self.logins[login_id]}
            if out["status"] == "succeeded":
                out["auth"] = self.status()
            return out

        async def cancel(hass, base, token, engine, login_id):
            self.logins.pop(login_id, None)

        async def logout(hass, base, token, engine):
            self.ready, self.signed_in = False, None
            return {"removed": True, "auth": self.status()}

        monkeypatch.setattr(runtime_auth, "async_auth_status", status)
        monkeypatch.setattr(runtime_auth, "async_login_start", start)
        monkeypatch.setattr(runtime_auth, "async_login_state", state)
        monkeypatch.setattr(runtime_auth, "async_login_cancel", cancel)
        monkeypatch.setattr(runtime_auth, "async_logout", logout)
        return self

    def finish_sign_in(self, login_id="L1"):
        self.logins[login_id] = "succeeded"
        self.ready = True
        self.signed_in = {"mode": "chatgpt", "plan": "pro", "saved_at": "2026-11-17T10:00:00+00:00"}


def _flow(monkeypatch, *, key=""):
    flow = flow_mod.AgentSubentryFlow()
    flow.hass = SimpleNamespace(config=SimpleNamespace(language="en"), async_create_task=lambda _c: None)
    flow.flow_id, flow.handler = "f1", ("entry", "agent")
    entry = SimpleNamespace(data={}, options={"runtime_url": "http://rt:8090", "runtime_token": "tok"})
    monkeypatch.setattr(flow, "_get_entry", lambda: entry)

    async def resolve(hass, configured):
        return configured or "http://detected:8090"

    monkeypatch.setattr(flow_mod, "async_resolve_runtime_url", resolve)
    saved = {}

    def finish(provider, data):
        saved.update(provider=provider, data=data)
        return {"type": "create_entry", "data": data}

    monkeypatch.setattr(flow, "_finish", finish)
    flow._provider = "openai"
    flow._pending = ("openai", {"mode": "codex", "api_provider": "openai", "use_codex_runtime": True, "codex_api_key": key})
    return flow, saved


def test_sign_in_with_chatgpt_by_device_code(monkeypatch) -> None:
    runtime = FakeRuntime().install(monkeypatch)
    flow, saved = _flow(monkeypatch)

    async def run():
        menu = await flow.async_step_codex_account()
        assert menu["menu_options"] == ["codex_login", "codex_back"]
        assert "Not signed in yet" in menu["description_placeholders"]["status"]
        form = await flow.async_step_codex_login()
        assert form["description_placeholders"] == {"url": DEVICE_URL, "code": "ABCD-1234"}
        # Submitted before the code was entered at OpenAI: same code, a hint.
        again = await flow.async_step_codex_login({})
        assert again["errors"] == {"base": "not_signed_in_yet"} and again["description_placeholders"]["code"] == "ABCD-1234"
        assert runtime.waits == [flow_mod._DEVICE_WAIT]
        runtime.finish_sign_in()
        done = await flow.async_step_codex_login({})
        assert done["step_id"] == "codex_signed_in" and "(Pro)" in done["description_placeholders"]["status"]
        await flow.async_step_codex_signed_in({})

    asyncio.run(run())
    assert saved["data"]["mode"] == "codex" and saved["data"]["codex_api_key"] == ""


def test_existing_runtime_access_is_offered_first(monkeypatch) -> None:
    FakeRuntime(chatgpt=True).install(monkeypatch)
    flow, saved = _flow(monkeypatch)

    async def run():
        menu = await flow.async_step_codex_account()
        assert menu["menu_options"][0] == "codex_use_runtime" and "codex_logout" in menu["menu_options"]
        assert "Signed in with ChatGPT on the Runtime (Plus)" in menu["description_placeholders"]["status"]
        await flow.async_step_codex_use_runtime()

    asyncio.run(run())
    assert saved["data"]["use_codex_runtime"] is True


def test_own_key_saves_directly_and_says_it_wins(monkeypatch) -> None:
    FakeRuntime().install(monkeypatch)
    flow, _saved = _flow(monkeypatch, key="sk-agent")

    async def run():
        return await flow.async_step_codex_account()

    menu = asyncio.run(run())
    assert menu["menu_options"][0] == "codex_save"
    assert "its own OpenAI API key" in menu["description_placeholders"]["status"]


def test_expired_device_code_goes_to_the_error_step(monkeypatch) -> None:
    runtime = FakeRuntime().install(monkeypatch)
    flow, _saved = _flow(monkeypatch)

    async def run():
        await flow.async_step_codex_login()
        runtime.logins["L1"] = "expired"
        return await flow.async_step_codex_login({})

    result = asyncio.run(run())
    assert result["step_id"] == "codex_login_error" and result["errors"] == {"base": "expired"}


def test_status_text_in_german() -> None:
    text = local_text.codex_signin_text(None, False, "de", "runtime_old")
    assert text.startswith("⚠️ Diese Runtime ist zu alt")
