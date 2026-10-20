import asyncio
import time
from types import SimpleNamespace

from custom_components.ai_workspace import activity_ha
from custom_components.ai_workspace.const import DOMAIN
from custom_components.ai_workspace.conversation import _is_admin
from custom_components.ai_workspace.http import _full_tools, _runtime_token_ok


def _callback(token: str, remote: str, header: str = ""):
    hass = SimpleNamespace(data={DOMAIN: {"runtime_token": token}})
    return SimpleNamespace(
        app={"hass": hass},
        remote=remote,
        headers={"Authorization": header} if header else {},
    )


def test_runtime_callbacks_without_token_only_from_loopback() -> None:
    assert _runtime_token_ok(_callback("", "127.0.0.1"))
    assert _runtime_token_ok(_callback("", "::1"))
    assert not _runtime_token_ok(_callback("", "192.168.1.20"))
    assert not _runtime_token_ok(_callback("", "172.30.32.1"))
    assert not _runtime_token_ok(_callback("", ""))


def test_runtime_callbacks_with_token_need_the_token() -> None:
    assert _runtime_token_ok(_callback("secret", "192.168.1.20", "Bearer secret"))
    assert not _runtime_token_ok(_callback("secret", "127.0.0.1"))
    assert not _runtime_token_ok(_callback("secret", "127.0.0.1", "Bearer wrong"))


def test_pending_activity_is_capped() -> None:
    def row(at: float) -> activity_ha.Pending:
        return activity_ha.Pending("u", "u", "Cursor", "t", "", None, None, "", "", at)

    now = time.monotonic()
    pending = {f"k{i}": row(now) for i in range(activity_ha._PENDING_MAX + 20)}
    pending["old"] = row(now - activity_ha._PENDING_TTL - 1)
    activity_ha._drop_old(pending)
    assert "old" not in pending
    assert len(pending) == activity_ha._PENDING_MAX - 1
    assert "k0" not in pending


def test_dashboard_load_bypasses_cache_when_forced() -> None:
    class Board:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        async def async_load(self, force):
            self.calls.append(bool(force))
            return {"views": []}

    board = Board()
    assert asyncio.run(activity_ha._load_board_config(board, False)) == {"views": []}
    assert asyncio.run(activity_ha._load_board_config(board, True)) == {"views": []}
    assert board.calls == [False, True]


def test_harvest_ignores_dashboards_without_a_before_snapshot() -> None:
    class Hass:
        def __init__(self) -> None:
            self.data = {DOMAIN: {}}

    row = SimpleNamespace(fragments=[], events=[], dashboard_docs={})
    asyncio.run(activity_ha.harvest_turn_changes(Hass(), row))
    assert row.fragments == []


def _voice_grid():
    import voluptuous as vol

    from custom_components.ai_workspace.config_flow import _SideBySide

    return _SideBySide(vol.Schema({vol.Optional("stt_engine", default="browser"): str}))


def test_voice_grid_serializes_with_probatio() -> None:
    import pytest

    pytest.importorskip("probatio")
    data = _voice_grid().serialize()
    assert data["type"] == "grid"
    assert data["schema"][0]["name"] == "stt_engine"


def test_voice_grid_serializes_before_ha_2026_9(monkeypatch) -> None:
    import sys

    import pytest

    serialize = pytest.importorskip("voluptuous_serialize")
    from custom_components.ai_workspace import config_flow

    monkeypatch.setitem(sys.modules, "probatio", None)
    monkeypatch.setattr(config_flow.cv, "custom_serializer", lambda _schema: serialize.UNSUPPORTED)
    data = _voice_grid().serialize()
    assert data["type"] == "grid"
    assert data["schema"][0]["name"] == "stt_engine"


def test_setup_note_explains_missing_mcp_server() -> None:
    from custom_components.ai_workspace.config_flow import _form_placeholders

    note = _form_placeholders(none_found=True)["mcp_url_note"]
    assert "Model Context Protocol Server" in note
    assert "Leave empty" not in note
    assert "Leave empty" in _form_placeholders()["mcp_url_note"]


def test_session_title_reads_off_the_event_loop() -> None:
    calls: list = []

    class FakeStore:
        def session_title(self, session_id):
            return f"Chat {session_id}"

    async def executor(func, *args):
        calls.append(func)
        return func(*args)

    hass = SimpleNamespace(data={DOMAIN: {"store": FakeStore()}}, async_add_executor_job=executor)
    assert asyncio.run(activity_ha._session_title(hass, "s1")) == "Chat s1"
    assert len(calls) == 1
    assert asyncio.run(activity_ha._session_title(hass, "")) == ""


def test_catalog_refresh_waits_for_registry_events_to_settle() -> None:
    from custom_components.ai_workspace import house_map

    assert house_map._EVENT_COOLDOWN >= 5


def test_timeout_has_a_readable_message() -> None:
    from custom_components.ai_workspace.api_provider import ApiProvider

    stub = SimpleNamespace(settings=SimpleNamespace(api_key="sk-secret", cursor_api_key="", mcp_token=""))
    assert "did not answer in time" in ApiProvider._public(stub, TimeoutError())
    assert ApiProvider._public(stub, RuntimeError()) == "RuntimeError"
    assert "sk-secret" not in ApiProvider._public(stub, RuntimeError("bad key sk-secret"))


def test_migrate_entry_accepts_current_version_only() -> None:
    from custom_components.ai_workspace import async_migrate_entry

    assert asyncio.run(async_migrate_entry(None, SimpleNamespace(version=2)))
    assert not asyncio.run(async_migrate_entry(None, SimpleNamespace(version=1)))


def test_full_tools_only_for_signed_in_admin() -> None:
    assert _full_tools("user-1", True)
    assert not _full_tools("user-1", False)
    assert not _full_tools("assist", True)
    assert not _full_tools("", True)


def test_unknown_assist_user_is_not_admin() -> None:
    async def get_user(user_id):
        return {"admin-1": SimpleNamespace(is_admin=True), "kid": SimpleNamespace(is_admin=False)}.get(user_id)

    hass = SimpleNamespace(auth=SimpleNamespace(async_get_user=get_user))
    assert asyncio.run(_is_admin(hass, "admin-1"))
    assert not asyncio.run(_is_admin(hass, "kid"))
    assert not asyncio.run(_is_admin(hass, "deleted-user"))
    assert asyncio.run(_is_admin(hass, "assist"))
