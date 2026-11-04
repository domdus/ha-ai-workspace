"""The Runtime sends Home Assistant's per-chat key on its callbacks."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_workspace"))

from app.mcp_proxy import McpProxy, _activity_target  # noqa: E402


def _request(token: str = "runtime-secret"):
    settings = SimpleNamespace(runtime_token=token, hass_url="http://homeassistant:8123", host="0.0.0.0")
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


def test_callback_uses_the_chats_key() -> None:
    proxy = McpProxy.__new__(McpProxy)
    from collections import OrderedDict

    proxy.actors = OrderedDict()
    proxy.note_actor("chat-1", "user-a", "Cursor", "issued-key")
    _base, token = _activity_target(_request(), proxy.actor("chat-1"))
    assert token == "issued-key"


def test_older_home_assistant_without_a_key_keeps_the_runtime_token() -> None:
    _base, token = _activity_target(_request(), {"user_id": "u", "agent": "Cursor", "callback_key": ""})
    assert token == "runtime-secret"
