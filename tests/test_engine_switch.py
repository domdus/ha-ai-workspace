"""A chat that started on Cursor and was switched to Claude kept running on Cursor in the Runtime
("Cursor API key is not set" under a Claude answer), because the Runtime only looked at the engine
the chat was created with."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ProviderInfo
from app.providers.claude import _claude_session_id
from test_api import FakeCursor, settings

CLAUDE_SID = "0b5b1c1e-6a52-4f0e-9a39-2f7b8a0c1d2e"


class FakeClaude(FakeCursor):
    def __init__(self) -> None:
        super().__init__()
        self.info = ProviderInfo("claude", "Claude", True, None)
        self.seen_agent_ids: list[str | None] = []

    async def send(self, session, message, on_agent_id, **kwargs):
        self.seen_agent_ids.append(session.agent_id)
        async for event in super().send(session, message, lambda _id: on_agent_id(CLAUDE_SID), **kwargs):
            yield event


def test_switched_chat_runs_on_the_engine_it_was_switched_to(tmp_path: Path) -> None:
    cursor, claude = FakeCursor(), FakeClaude()
    app = create_app(settings(tmp_path), {"cursor": cursor, "claude": claude})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sid = client.post("/api/sessions", json={"provider": "cursor"}).json()["id"]
        client.post(f"/api/sessions/{sid}/chat", json={"message": "on cursor", "provider": "cursor"})
        assert cursor.last_message == "on cursor"

        # Home Assistant still holds the Cursor agent id; it must not reach Claude.
        client.post(
            f"/api/sessions/{sid}/chat",
            json={"message": "on claude", "provider": "claude", "sync_agent_id": "agent-local-1"},
        )
        assert claude.last_message == "on claude" and cursor.last_message == "on cursor"
        assert claude.seen_agent_ids == [None]
        stored = client.get(f"/api/sessions/{sid}").json()
        assert stored["provider"] == "claude" and stored["agent_id"] == CLAUDE_SID

        # The next Claude turn resumes Claude's own session.
        client.post(f"/api/sessions/{sid}/chat", json={"message": "again", "provider": "claude"})
        assert claude.seen_agent_ids == [None, CLAUDE_SID]

        # And back to Cursor.
        client.post(f"/api/sessions/{sid}/chat", json={"message": "back", "provider": "cursor"})
        assert cursor.last_message == "back"


def test_older_integrations_without_a_provider_keep_the_chat_engine(tmp_path: Path) -> None:
    cursor, claude = FakeCursor(), FakeClaude()
    app = create_app(settings(tmp_path), {"cursor": cursor, "claude": claude})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        sid = client.post("/api/sessions", json={"provider": "claude"}).json()["id"]
        client.post(f"/api/sessions/{sid}/chat", json={"message": "hi"})
        client.post(f"/api/sessions/{sid}/chat", json={"message": "unknown", "provider": "codex"})
    assert claude.last_message == "unknown" and cursor.last_message is None


def test_claude_only_resumes_its_own_session_ids() -> None:
    assert _claude_session_id(CLAUDE_SID) == CLAUDE_SID
    assert _claude_session_id("agent-6f236c0186b437bd") is None
    assert _claude_session_id("01M4R90QC50BE6K2TF7CZ24JYN") is None
    assert _claude_session_id(None) is None and _claude_session_id("") is None
