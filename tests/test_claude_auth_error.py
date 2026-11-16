"""An expired or revoked Claude credential reads as "sign in again" in the chat's language."""

import asyncio
import json

import pytest

http = pytest.importorskip("custom_components.ai_workspace.http")

from custom_components.ai_workspace import local_text  # noqa: E402
from custom_components.ai_workspace.error_text import public_error  # noqa: E402

CODE = "claude_auth_failed"
RUNTIME_TEXT = "Anthropic no longer accepts this Claude sign-in or key: it has expired or was revoked."


def test_code_matches_the_runtime() -> None:
    from app.providers.claude import AUTH_FAILED_CODE

    assert local_text.CLAUDE_AUTH_FAILED_CODE == AUTH_FAILED_CODE == CODE


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("de", local_text.CLAUDE_AUTH_FAILED["de"]),
        ("de-AT", local_text.CLAUDE_AUTH_FAILED["de"]),
        ("en", local_text.CLAUDE_AUTH_FAILED["en"]),
        ("", local_text.CLAUDE_AUTH_FAILED["en"]),
        ("zh-TW", local_text.CLAUDE_AUTH_FAILED["zh-Hant"]),
        ("pt-BR", local_text.CLAUDE_AUTH_FAILED["en"]),
    ],
)
def test_the_auth_error_is_translated(language, expected) -> None:
    event = {"type": "error", "message": RUNTIME_TEXT, "code": CODE}
    out = http._localized_runtime_error(event, language)
    assert out == {"type": "error", "message": expected, "code": CODE}
    # The chat keeps the translated text as it is.
    assert public_error(out["message"]) == expected


def test_german_and_english_say_to_sign_in_again() -> None:
    assert "melde dich erneut mit Claude an" in local_text.CLAUDE_AUTH_FAILED["de"]
    assert "sign in with Claude again" in local_text.CLAUDE_AUTH_FAILED["en"]


def test_other_events_pass_unchanged() -> None:
    plain = {"type": "error", "message": "Overloaded"}
    assert http._localized_runtime_error(plain, "de") is plain
    text = {"type": "text", "delta": "hi", "code": CODE}
    assert http._localized_runtime_error(text, "de") is text


class _Content:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class _Stream:
    status = 200

    def __init__(self, events):
        body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
        self.content = _Content([body.encode()])

    def release(self):
        pass


def test_runtime_chat_relays_the_translated_error(monkeypatch) -> None:
    from types import SimpleNamespace

    events = [{"type": "status", "text": "Thinking..."}, {"type": "error", "message": RUNTIME_TEXT, "code": CODE}]

    class Session:
        async def post(self, url, json=None, headers=None, timeout=None):
            return _Stream(events)

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

    monkeypatch.setattr(notes, "notes_update", lambda *a, **k: "")
    chat = SimpleNamespace(id="s1", agent_id="", provider="claude")

    async def collect():
        return [e async for e in http._runtime_chat(hass, "u1", chat, "Hallo", language="de", runtime_provider="claude")]

    out = asyncio.run(collect())
    assert out[-1] == {"type": "error", "message": local_text.CLAUDE_AUTH_FAILED["de"], "code": CODE}
