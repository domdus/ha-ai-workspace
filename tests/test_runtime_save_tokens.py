"""Save tokens on Runtime agents: the effort still reaches the Runtime, and Claude hears about changed notes.

Save tokens dropped the effort, which on cloud agents goes with a reply cap. The Runtime has no reply cap,
so Claude Code and Cursor ran at their own, often higher, default effort.
"""

import asyncio
from types import SimpleNamespace

import pytest

http = pytest.importorskip("custom_components.ai_workspace.http")
from custom_components.ai_workspace.const import TOKEN_MODE_MEDIUM, TOKEN_MODE_OFF  # noqa: E402
from test_claude_auth_error import _Stream  # noqa: E402


def _send(monkeypatch, kind: str, mode: str):
    sent, notes_seen = {}, []

    class Session:
        async def post(self, url, json=None, headers=None, timeout=None):
            sent.update(json or {})
            return _Stream([{"type": "done", "answer": "ok"}])

    async def ensure(*args, **kwargs):
        return True

    hass = SimpleNamespace(data={http.DOMAIN: {"runtime_url": "http://rt:8090", "settings": None, "providers": {}}})
    monkeypatch.setattr(http, "async_get_clientsession", lambda hass_: Session())
    monkeypatch.setattr(http, "_ensure_runtime_session", ensure)
    monkeypatch.setattr(http, "_runtime_headers_for", lambda *a, **k: {})
    monkeypatch.setattr(http, "standing_chat_prompt", lambda *a, **k: "")
    monkeypatch.setattr(http, "house_zone", lambda hass_: None)
    monkeypatch.setattr(http, "issue_callback_key", lambda *a, **k: "key")
    import custom_components.ai_workspace.notes as notes

    monkeypatch.setattr(notes, "notes_update", lambda *a, fresh=False, **k: notes_seen.append(fresh) or "")
    chat = SimpleNamespace(id="s1", agent_id="", provider=kind)

    async def collect():
        return [
            e
            async for e in http._runtime_chat(
                hass, "u1", chat, "Hallo", effort="fast", token_mode=mode, runtime_provider=kind
            )
        ]

    asyncio.run(collect())
    return sent, notes_seen


@pytest.mark.parametrize("kind", ["claude", "cursor"])
@pytest.mark.parametrize("mode", [TOKEN_MODE_OFF, TOKEN_MODE_MEDIUM])
def test_effort_reaches_the_runtime_with_save_tokens(monkeypatch, kind, mode) -> None:
    sent, _ = _send(monkeypatch, kind, mode)
    assert sent["effort"] == "fast"
    assert sent["fresh"] is (mode == TOKEN_MODE_MEDIUM)


def test_claude_keeps_its_session_so_it_hears_about_changed_notes(monkeypatch) -> None:
    assert _send(monkeypatch, "claude", TOKEN_MODE_MEDIUM)[1] == [False]
    assert _send(monkeypatch, "cursor", TOKEN_MODE_MEDIUM)[1] == [True]
