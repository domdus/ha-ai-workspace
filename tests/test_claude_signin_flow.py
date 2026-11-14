"""Agent form: "Sign in with Claude plan" for Claude SDK (runtime) agents only.

The flow steps run for real against a fake Runtime (no network); HA's flow manager is not needed
because each step returns the form/menu dict that HA would show.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

flow_mod = pytest.importorskip("custom_components.ai_workspace.agent_flow")
from custom_components.ai_workspace import local_text, runtime_auth  # noqa: E402
from custom_components.ai_workspace.runtime_auth import RuntimeAuthError  # noqa: E402

URL = "https://claude.com/cai/oauth/authorize?code=true&state=xyz"


class FakeRuntime:
    """The Runtime's /api/auth/claude... as the integration sees it."""

    def __init__(self, *, ready=False, signed_in=None, credential="none", supported=True, old=False):
        self.ready = ready
        self.signed_in = signed_in
        self.credential = credential
        self.supported = supported
        self.old = old
        self.started = 0
        self.cancelled: list[str] = []
        self.codes: list[str] = []
        self.logins: dict[str, str] = {}
        self.seen: list[tuple[str, str]] = []

    def status(self):
        return {
            "engine": "claude",
            "ready": self.ready,
            "credential": self.credential,
            "kind": "plan" if self.ready else None,
            "signed_in": self.signed_in,
            "overridden": False,
            "login": {"supported": self.supported, "flow": "paste_code"},
        }

    def install(self, monkeypatch):
        async def status(hass, base, token, engine):
            self.seen.append((base, token))
            assert engine == "claude"
            if self.old:
                raise RuntimeAuthError("runtime_old")
            return self.status()

        async def start(hass, base, token, engine):
            self.started += 1
            login_id = f"L{self.started}"
            self.logins[login_id] = "awaiting_code"
            return {"id": login_id, "status": "awaiting_code", "url": f"{URL}&n={self.started}", "flow": "paste_code"}

        async def state(hass, base, token, engine, login_id):
            if login_id not in self.logins:
                raise RuntimeAuthError("expired")
            return {"id": login_id, "status": self.logins[login_id]}

        async def code(hass, base, token, engine, login_id, value):
            self.codes.append(value)
            if " " in value:
                raise RuntimeAuthError("bad_code")
            if value != "good#state":
                self.logins[login_id] = "failed"
                raise RuntimeAuthError("code_rejected")
            self.logins[login_id] = "succeeded"
            self.ready, self.credential = True, "signed-in"
            self.signed_in = {"saved_at": "2026-11-13T10:00:00+00:00", "expires_at": "2027-11-13T10:00:00+00:00"}
            return {"id": login_id, "status": "succeeded", "auth": self.status()}

        async def cancel(hass, base, token, engine, login_id):
            self.cancelled.append(login_id)
            self.logins.pop(login_id, None)

        async def logout(hass, base, token, engine):
            self.ready, self.credential, self.signed_in = False, "none", None
            return {"removed": True, "auth": self.status()}

        monkeypatch.setattr(runtime_auth, "async_auth_status", status)
        monkeypatch.setattr(runtime_auth, "async_login_start", start)
        monkeypatch.setattr(runtime_auth, "async_login_state", state)
        monkeypatch.setattr(runtime_auth, "async_login_code", code)
        monkeypatch.setattr(runtime_auth, "async_login_cancel", cancel)
        monkeypatch.setattr(runtime_auth, "async_logout", logout)
        return self


def _flow(monkeypatch, *, language="en", pending_key=""):
    flow = flow_mod.AgentSubentryFlow()
    tasks = []
    flow.hass = SimpleNamespace(config=SimpleNamespace(language=language), async_create_task=tasks.append)
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
    flow._provider = "anthropic"
    flow._pending = (
        "anthropic",
        {"mode": "claude", "api_provider": "anthropic", "use_claude_runtime": True, "claude_api_key": pending_key},
    )
    return flow, saved, tasks


def run(coro):
    return asyncio.run(coro)


def test_menu_offers_sign_in_and_hides_save_without_a_credential(monkeypatch) -> None:
    rt = FakeRuntime().install(monkeypatch)
    flow, _saved, _ = _flow(monkeypatch)
    menu = run(flow.async_step_claude_account())
    assert menu["type"] == "menu" and menu["step_id"] == "claude_account"
    assert menu["menu_options"] == ["claude_login", "claude_back"]
    assert "Not signed in" in menu["description_placeholders"]["status"]
    assert rt.seen == [("http://rt:8090", "tok")]


def test_sign_in_paste_code_then_confirm_and_save(monkeypatch) -> None:
    rt = FakeRuntime().install(monkeypatch)
    flow, saved, _ = _flow(monkeypatch, pending_key="sk-ant-oat01-old-token-on-agent")
    form = run(flow.async_step_claude_login())
    assert form["type"] == "form" and form["step_id"] == "claude_login"
    assert form["description_placeholders"]["url"] == f"{URL}&n=1"
    assert [str(k) for k in form["data_schema"].schema] == ["code"]

    # A mistyped code keeps the same link.
    again = run(flow.async_step_claude_login({"code": "has space"}))
    assert again["errors"] == {"code": "bad_code"} and again["description_placeholders"]["url"].endswith("n=1")
    # A rejected code ends that sign-in; the form comes back with a fresh link.
    fresh = run(flow.async_step_claude_login({"code": "nope"}))
    assert fresh["errors"] == {"base": "code_rejected"} and fresh["description_placeholders"]["url"].endswith("n=2")

    done = run(flow.async_step_claude_login({"code": "good#state"}))
    assert done["type"] == "form" and done["step_id"] == "claude_signed_in"
    status = done["description_placeholders"]["status"]
    assert "Signed in with your Claude plan" in status and "2027-11-13" in status
    assert "sk-ant" not in status
    result = run(flow.async_step_claude_signed_in({}))
    assert result["type"] == "create_entry"
    # The old token on the agent would win over the sign-in, so it is dropped.
    assert saved["data"]["claude_api_key"] == ""
    assert saved["data"]["mode"] == "claude"
    assert rt.codes == ["has space", "nope", "good#state"] and rt.started == 2


def test_signed_in_menu_has_save_and_sign_out(monkeypatch) -> None:
    signed = {"saved_at": "2026-01-02T00:00:00+00:00", "expires_at": "2027-01-02T00:00:00+00:00"}
    FakeRuntime(ready=True, credential="signed-in", signed_in=signed).install(monkeypatch)
    flow, saved, _ = _flow(monkeypatch, language="de")
    menu = run(flow.async_step_claude_account())
    assert menu["menu_options"] == ["claude_save", "claude_login", "claude_logout", "claude_back"]
    assert "angemeldet" in menu["description_placeholders"]["status"]
    out = run(flow.async_step_claude_logout())
    assert out["menu_options"] == ["claude_login", "claude_back"]
    FakeRuntime(ready=True, credential="signed-in", signed_in=signed).install(monkeypatch)
    run(flow.async_step_claude_save())
    assert saved["data"]["use_claude_runtime"] is True


def test_own_token_on_the_agent_is_enough_to_save_and_is_mentioned(monkeypatch) -> None:
    FakeRuntime().install(monkeypatch)
    flow, _saved, _ = _flow(monkeypatch, pending_key="sk-ant-oat01-mine")
    menu = run(flow.async_step_claude_account())
    assert menu["menu_options"][0] == "claude_save"
    assert "own token" in menu["description_placeholders"]["status"]


def test_old_runtime_shows_update_hint_and_no_sign_in(monkeypatch) -> None:
    FakeRuntime(old=True).install(monkeypatch)
    flow, _saved, _ = _flow(monkeypatch, pending_key="sk-ant-api03-x")
    menu = run(flow.async_step_claude_account())
    assert menu["menu_options"] == ["claude_save", "claude_back"]
    assert "Update the AI Workspace Runtime" in menu["description_placeholders"]["status"]


def test_start_failure_shows_error_form_then_back_to_menu(monkeypatch) -> None:
    FakeRuntime().install(monkeypatch)

    async def broken(hass, base, token, engine):
        raise RuntimeAuthError("cli_missing")

    monkeypatch.setattr(runtime_auth, "async_login_start", broken)
    flow, _saved, _ = _flow(monkeypatch)
    form = run(flow.async_step_claude_login())
    assert form["step_id"] == "claude_login_error" and form["errors"] == {"base": "cli_missing"}
    back = run(flow.async_step_claude_login_error({}))
    assert back["type"] == "menu"


def test_back_cancels_the_pending_sign_in_and_closing_the_dialog_does_too(monkeypatch) -> None:
    rt = FakeRuntime().install(monkeypatch)
    flow, _saved, tasks = _flow(monkeypatch)
    run(flow.async_step_claude_login())
    flow.async_remove()
    assert len(tasks) == 1
    run(tasks[0])
    assert rt.cancelled == ["L1"]

    called = {}

    async def fields(step, user_input):
        called["step"] = step
        return {"type": "form", "step_id": f"provider_{step}"}

    monkeypatch.setattr(flow, "_async_step_fields", fields)
    run(flow.async_step_claude_login())
    out = run(flow.async_step_claude_back())
    assert out["step_id"] == "provider_cloud" and rt.cancelled == ["L1", "L2"]
    assert flow._pending is None


def test_entering_sign_in_again_reuses_a_waiting_link(monkeypatch) -> None:
    rt = FakeRuntime().install(monkeypatch)
    flow, _saved, _ = _flow(monkeypatch)
    first = run(flow.async_step_claude_login())
    second = run(flow.async_step_claude_login())
    assert first["description_placeholders"]["url"] == second["description_placeholders"]["url"]
    rt.logins.clear()  # expired on the Runtime
    third = run(flow.async_step_claude_login())
    assert third["description_placeholders"]["url"].endswith("n=2")


def test_form_submit_goes_to_the_menu_only_in_sdk_mode(monkeypatch) -> None:
    FakeRuntime().install(monkeypatch)
    flow, saved, _ = _flow(monkeypatch)
    flow._pending = None
    flow._current = {"api_provider": "anthropic"}
    monkeypatch.setattr(flow_mod, "borrowed_setups", lambda hass: [])
    monkeypatch.setattr(flow_mod, "borrow_by_id", lambda hass, value: None)

    async def no_errors(*args, **kwargs):
        return {}

    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(flow, "_claude_errors", no_errors)
    monkeypatch.setattr(flow, "_key_errors", no_errors)
    monkeypatch.setattr(flow, "_store_runtime", nothing)
    sdk = run(
        flow.async_step_provider_cloud(
            {"use_claude_runtime": True, "claude_runtime": {"runtime_url": "", "claude_api_key": ""}, "model": "claude-sonnet-5-5"}
        )
    )
    assert sdk["type"] == "menu" and sdk["step_id"] == "claude_account"
    assert not saved

    flow2, saved2, _ = _flow(monkeypatch)
    flow2._pending = None
    flow2._current = {"api_provider": "anthropic"}
    monkeypatch.setattr(flow2, "_key_errors", no_errors)
    cloud = run(flow2.async_step_provider_cloud({"use_claude_runtime": False, "api_key": "sk-ant-api03-x", "model": "claude-sonnet-5-5"}))
    assert cloud["type"] == "create_entry" and saved2["data"]["mode"] == "api"


def test_no_credential_is_fine_when_the_runtime_can_sign_in(monkeypatch) -> None:
    flow, _saved, _ = _flow(monkeypatch)

    async def health(hass, base):
        return {"claude": False, "login": ["claude"]}

    async def old_health(hass, base):
        return {"claude": False}

    monkeypatch.setattr(flow_mod, "async_runtime_health", health)
    assert run(flow._claude_errors("", "http://rt:8090")) == {}
    monkeypatch.setattr(flow_mod, "async_runtime_health", old_health)
    assert run(flow._claude_errors("", "http://rt:8090")) == {"claude_api_key": "required"}


def test_status_text_in_every_language() -> None:
    for lang in local_text.LANGUAGES:
        table = local_text.pick(local_text.CLAUDE_SIGNIN, lang)
        assert set(table) == set(local_text.CLAUDE_SIGNIN["en"]), lang
    status = {"credential": "settings", "kind": "plan", "overridden": True, "signed_in": {"saved_at": "x"}}
    text = local_text.claude_signin_text(status, False, "en")
    assert "Claude Plan" in text and "wins over your sign-in" in text
    assert "did not answer" in local_text.claude_signin_text(None, False, "en", "no_runtime")


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self, content_type=None):
        return self._body

    def release(self):
        return None


def test_http_client_maps_runtime_answers(monkeypatch) -> None:
    calls = []
    answers = []

    class Session:
        async def request(self, method, url, headers=None, json=None, timeout=None):
            calls.append((method, url, headers, json))
            return answers.pop(0)

    monkeypatch.setattr(runtime_auth, "async_get_clientsession", lambda hass: Session())
    answers.append(_Resp(200, {"id": "L1", "url": URL}))
    assert run(runtime_auth.async_login_start(None, "http://rt:8090/", "tok", "claude"))["id"] == "L1"
    assert calls[-1][:3] == ("POST", "http://rt:8090/api/auth/claude/login", {"Authorization": "Bearer tok"})

    for status, body, key in (
        (400, {"detail": "bad_code"}, "bad_code"),
        (401, {"detail": "Runtime token is missing or wrong."}, "runtime_rejected"),
        (404, {"detail": "Not Found"}, "runtime_old"),
        (410, {"detail": "expired"}, "expired"),
        (502, {"detail": "something new"}, "login_failed"),
    ):
        answers.append(_Resp(status, body))
        with pytest.raises(RuntimeAuthError) as err:
            run(runtime_auth.async_login_code(None, "http://rt:8090", "tok", "claude", "L1", "x"))
        assert err.value.key == key
    assert calls[-1][3] == {"code": "x"}
    with pytest.raises(RuntimeAuthError) as err:
        run(runtime_auth.async_auth_status(None, "", "tok", "claude"))
    assert err.value.key == "no_runtime"
