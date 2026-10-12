from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ProviderInfo
from app.settings import Settings
from app.store import Session


class FakeCursor:
    def __init__(self) -> None:
        self.info = ProviderInfo("cursor", "Cursor", True, None)
        self.last_images = None
        self.last_message = None
        self.last_mcp = None
        self.last_model = None

    async def send(self, session: Session, message: str, on_agent_id, images=None, mcp=None, model=None, **_kwargs):
        self.last_message = message
        self.last_images = images
        self.last_mcp = mcp
        self.last_model = model
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


def settings(tmp_path: Path, auth_mode: str = "dev", host: str = "127.0.0.1", token: str = "") -> Settings:
    return Settings(
        data_dir=tmp_path,
        workspace_dir=tmp_path / "workspace",
        state_dir=tmp_path / "state",
        mcp_config_path=tmp_path / "mcp.json",
        cursor_api_key="",
        model="composer-2.5",
        auth_mode=auth_mode,
        host=host,
        port=8090,
        runtime_token=token,
    )


def test_token_is_required_when_set(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, token="s3cret"), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/api/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/api/sessions", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_network_bound_runtime_without_token_refuses_chat(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, host="0.0.0.0"), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["token_required"] is True
        assert client.post("/api/sessions", json={"provider": "cursor"}).status_code == 401


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
        assert body["title"] == "Why no water"
        assert [item["role"] for item in body["messages"]] == ["user", "assistant"]
        assert body["messages"][1]["content"] == "Moisture is 18%."
        other = client.get(f"/api/sessions/{session_id}", headers={"X-Remote-User-Id": "someone-else"})
        assert other.status_code == 404


class FakeCursorTitled(FakeCursor):
    async def suggest_title(self, user: str, assistant: str = "", **_kwargs) -> str | None:
        del user, assistant
        return "Garden moisture"


def test_chat_keeps_short_first_prompt_as_title(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path), {"cursor": FakeCursorTitled()})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(
            f"/api/sessions/{session_id}/chat",
            json={"message": "Status der Bewässerung?"},
        )
        assert streamed.status_code == 200
        assert "Garden moisture" not in streamed.text
        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.json()["title"] == "Status der Bewässerung"


def test_chat_summarizes_long_first_prompt(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path), {"cursor": FakeCursorTitled()})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(
            f"/api/sessions/{session_id}/chat",
            json={
                "message": (
                    "Die dreame extension hat ein großes 2.0.1 update bekommen "
                    "und liefert jetzt wohl auch lovelace maps usw.."
                )
            },
        )
        assert streamed.status_code == 200
        assert "event: title" in streamed.text
        assert "Garden moisture" in streamed.text
        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.json()["title"] == "Garden moisture"


def test_ingress_requires_a_user(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path, "ingress"), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        missing = client.get("/api/sessions")
        assert missing.status_code == 401
        ok = client.get("/api/sessions", headers={"X-Remote-User-Id": "ha-user"})
        assert ok.status_code == 200
        assert ok.json() == []


def test_rename_and_delete_session(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        renamed = client.patch(f"/api/sessions/{session_id}", json={"title": "Kitchen leak"})
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Kitchen leak"
        assert client.get("/api/sessions").json()[0]["title"] == "Kitchen leak"
        deleted = client.delete(f"/api/sessions/{session_id}")
        assert deleted.status_code == 204
PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_chat_accepts_image_without_text(tmp_path: Path) -> None:
    provider = FakeCursor()
    app = create_app(settings(tmp_path), {"cursor": provider})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(
            f"/api/sessions/{session_id}/chat",
            json={
                "message": "",
                "images": [{"name": "kitchen.png", "mime": "image/png", "data": PNG_1PX}],
            },
        )
        assert streamed.status_code == 200
        assert provider.last_images
        assert provider.last_images[0]["mime"] == "image/png"
        detail = client.get(f"/api/sessions/{session_id}")
        user = detail.json()["messages"][0]
        assert user["content"] == "Look at this image."
        assert user["events"][0]["type"] == "image"
        assert user["events"][0]["src"].startswith("data:image/png;base64,")


def test_chat_accepts_yaml_file_without_text(tmp_path: Path) -> None:
    provider = FakeCursor()
    app = create_app(settings(tmp_path), {"cursor": provider})
    yaml_text = "id: porch_light\nalias: Porch light\n"
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(
            f"/api/sessions/{session_id}/chat",
            json={
                "message": "",
                "files": [{"name": "porch.yaml", "mime": "", "text": yaml_text}],
            },
        )
        assert streamed.status_code == 200
        assert "porch.yaml" in provider.last_message
        assert "porch_light" in provider.last_message
        detail = client.get(f"/api/sessions/{session_id}")
        user = detail.json()["messages"][0]
        assert user["content"] == "Look at this file."
        assert user["events"][0] == {"type": "file", "name": "porch.yaml"}
        assert "porch_light" not in user["content"]


def test_chat_accepts_mcp_and_model_from_request(tmp_path: Path) -> None:
    provider = FakeCursor()
    app = create_app(settings(tmp_path), {"cursor": provider})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(
            f"/api/sessions/{session_id}/chat",
            json={
                "message": "list lights",
                "model": "composer-2.6",
                "mcp": {
                    "servers": {
                        "mcp": {"type": "http", "url": "http://127.0.0.1:8123/api/webhook/mcp_test"}
                    }
                },
            },
        )
        assert streamed.status_code == 200
        assert provider.last_model == "composer-2.6"
        assert provider.last_mcp["servers"]["mcp"]["url"].endswith("/mcp_test")


def test_empty_chat_without_images_is_rejected(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path), {"cursor": FakeCursor()})
    with TestClient(app) as client:
        created = client.post("/api/sessions", json={"provider": "cursor"})
        session_id = created.json()["id"]
        streamed = client.post(f"/api/sessions/{session_id}/chat", json={"message": "  "})
        assert streamed.status_code == 400

