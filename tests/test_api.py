from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ProviderInfo
from app.settings import Settings
from app.store import Session


class FakeCursor:
    def __init__(self) -> None:
        self.info = ProviderInfo("cursor", "Cursor", True, None)

    async def send(self, session: Session, message: str, on_agent_id):
        del message
        on_agent_id("agent-local-1")
        yield {"type": "status", "text": "Thinking..."}
        yield {"type": "text", "delta": "Moisture is 18%."}
        yield {
            "type": "tool",
            "name": "ha_config_get_automation",
            "phase": "start",
            "text": "Calling ha_config_get_automation...",
        }
        yield {"type": "result", "text": "Moisture is 18%.", "run_id": "run-1", "status": "finished"}


def settings(tmp_path: Path, auth_mode: str = "dev") -> Settings:
    return Settings(
        data_dir=tmp_path,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        auth_mode=auth_mode,
        host="127.0.0.1",
        port=8090,
    )


def test_chat_keeps_agent_id_and_transcript(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        assert created.status_code == 201
        session_id = created.json()["id"]
        streamed = client.post(f"/api/sessions/{session_id}/chat", json={"message": "Why no water?"})
        assert streamed.status_code == 200
        assert "event: text" in streamed.text
        assert "Calling ha_config_get_automation..." in streamed.text
        assert "event: done" in streamed.text
        detail = client.get(f"/api/sessions/{session_id}")
        body = detail.json()
        assert body["agent_id"] == "agent-local-1"
        assert body["title"] == "Why no water?"
        assert [item["role"] for item in body["messages"]] == ["user", "assistant"]
        assert body["messages"][1]["content"] == "Moisture is 18%."
        other = client.get(f"/api/sessions/{session_id}", headers={"X-Remote-User-Id": "someone-else"})
        assert other.status_code == 404


def test_ingress_requires_a_user(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, "ingress"), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        missing = client.get("/api/sessions")
        assert missing.status_code == 401
        ok = client.get("/api/sessions", headers={"X-Remote-User-Id": "ha-user"})
        assert ok.status_code == 200
        assert ok.json() == []
