"""The Runtime App is found even when Core started before it was installed."""

from types import SimpleNamespace

import pytest

hassio = pytest.importorskip("homeassistant.components.hassio")

from custom_components.ai_workspace import discovery  # noqa: E402


def _patch(monkeypatch, info, listing):
    monkeypatch.setattr(hassio, "get_addons_info", lambda hass: info, raising=False)
    monkeypatch.setattr(hassio, "get_addons_list", lambda hass: listing, raising=False)


def test_app_from_the_info_cache(monkeypatch) -> None:
    _patch(monkeypatch, {"8401652b_ai_workspace": {"state": "started", "hostname": "8401652b-ai-workspace"}}, [])
    assert discovery._hassio_addon(SimpleNamespace()) == (
        "8401652b_ai_workspace",
        "http://8401652b-ai-workspace:8090",
    )


def test_app_installed_after_core_started_is_found_in_the_list(monkeypatch) -> None:
    # 2026.11 fills the info cache only on the first poll; later installs appear in the list only.
    _patch(monkeypatch, {"core_piper": {"state": "started"}}, [
        {"slug": "core_piper", "state": "started"},
        {"slug": "8401652b_ai_workspace", "state": "started"},
    ])
    assert discovery._hassio_addon(SimpleNamespace()) == (
        "8401652b_ai_workspace",
        "http://8401652b-ai-workspace:8090",
    )


def test_stopped_app_is_not_used(monkeypatch) -> None:
    _patch(monkeypatch, {}, [{"slug": "8401652b_ai_workspace", "state": "stopped"}])
    assert discovery._hassio_addon(SimpleNamespace()) is None


def test_missing_list_helper_keeps_working(monkeypatch) -> None:
    def boom(hass):
        raise RuntimeError("not ready")

    monkeypatch.setattr(hassio, "get_addons_info", boom, raising=False)
    monkeypatch.setattr(hassio, "get_addons_list", boom, raising=False)
    assert discovery._hassio_addon(SimpleNamespace()) is None


def test_old_app_options_are_removed_when_the_integration_writes_options(monkeypatch) -> None:
    monkeypatch.setattr(discovery, "_runtime_hass_url", lambda hass: "http://homeassistant:8123")
    opts = {
        "cursor_api_key": "k",
        "hass_url": "http://homeassistant:8123",
        "shorten_mcp_results": True,
        "change_history": False,
    }
    assert discovery._sync_runtime_options(SimpleNamespace(), opts) is True
    assert opts == {"cursor_api_key": "k", "hass_url": "http://homeassistant:8123"}
    # Nothing left to change: no write.
    assert discovery._sync_runtime_options(SimpleNamespace(), opts) is False
