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


def test_cross_chat_matches_title_without_a_cue() -> None:
    scope = _scope()
    chats = [
        {"id": "weather", "title": "Weather entities"},
        {"id": "light", "title": "Light automation"},
        {"id": "current", "title": "New Chat"},
    ]
    assert scope.matching_chats("debug the light automation", chats, "current") == []
    named = scope.matching_chats("debug the light automation", chats, "current", cross=True)
    assert [item["id"] for item in named] == ["light"]
    assert scope.matching_chats("give me status", chats, "current", cross=True) == []


def test_handoff_includes_title_and_skips_tables() -> None:
    scope = _scope()

    class Row:
        def __init__(self, role, content, events="[]"):
            self.role = role
            self.content = content
            self.events = events

    rows = [
        Row("user", "Handy-Tracker kaputt?"),
        Row(
            "assistant",
            "Die Person hängt an toten Trackern.\n\n"
            "| Tracker | Status |\n"
            "| --- | --- |\n"
            "| Galaxy-A55-5G | not_home |\n\n"
            "Wenn du willst, setze ich A55-von-Dominik auf die Person.",
        ),
        Row("user", "Ja mach mal."),
    ]
    note = scope.handoff_note(rows, "Handy nicht zu Hause")
    assert 'titled "Handy nicht zu Hause"' in note
    assert "Handy-Tracker kaputt?" in note
    assert "setze ich A55-von-Dominik" in note
    assert "Galaxy-A55-5G" not in note
    assert "Ja mach mal." not in note
    assert "go ahead" in note


def test_handoff_skips_current_prompt() -> None:
    scope = _scope()

    class Row:
        def __init__(self, role, content, events="[]"):
            self.role = role
            self.content = content
            self.events = events

    rows = [
        Row("user", "Which lights are on?"),
        Row("assistant", "Kitchen and hallway."),
        Row("user", "Turn the hallway off."),
    ]
    note = scope.handoff_note(rows)
    assert "same chat" in note
    assert "Continue from it" in note
    assert "Which lights are on?" in note
    assert "Kitchen and hallway." in note
    assert "Turn the hallway off." not in note
    assert scope.attach_handoff("Turn the hallway off.", rows, True).endswith("Turn the hallway off.")
    assert scope.attach_handoff("Turn the hallway off.", rows, False) == "Turn the hallway off."


def test_handoff_drops_failed_replies() -> None:
    scope = _scope()

    class Row:
        def __init__(self, role, content, events="[]"):
            self.role = role
            self.content = content
            self.events = events

    rows = [
        Row("user", "List automations"),
        Row("assistant", "MCP HTTP 401", '[{"type":"error","message":"MCP HTTP 401"}]'),
        Row("user", "Continue"),
    ]
    note = scope.handoff_note(rows)
    assert "List automations" in note
    assert "MCP HTTP 401" not in note
    assert scope.handoff_note([Row("user", "Hello")]) == ""


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
