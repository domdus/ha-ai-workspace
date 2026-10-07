import importlib.util
from pathlib import Path


def _scope():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "chat_scope.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_chat_scope", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_other_chats_stay_out_until_named() -> None:
    scope = _scope()
    chats = [
        {"id": "weather", "title": "Weather entities"},
        {"id": "light", "title": "Light automation"},
        {"id": "current", "title": "New Chat"},
    ]
    assert scope.matching_chats("give me status", chats, "current") == []
    assert scope.matching_chats("debug the light automation", chats, "current") == []
    named = scope.matching_chats("Do you know how we did in our weather chat?", chats, "current")
    assert [item["id"] for item in named] == ["weather"]


def test_excerpt_is_read_only() -> None:
    scope = _scope()
    note = scope.excerpt_for(
        [
            {
                "title": "Weather entities",
                "messages": [("user", "Which weather sensors?"), ("assistant", "sensor.outdoor_temp")],
            }
        ]
    )
    assert 'chat "Weather entities"' in note
    assert "Read-only" in note
    assert "sensor.outdoor_temp" in note
