from types import SimpleNamespace

from app.events import map_sdk_message


def test_assistant_text_and_tool_use() -> None:
    message = SimpleNamespace(
        type="assistant",
        message=SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Hello"),
                SimpleNamespace(type="tool_use", name="ha_get_logs", input={}),
            ]
        ),
    )
    events = map_sdk_message(message)
    assert events[0] == {"type": "text", "delta": "Hello"}
    assert events[1]["text"] == "Calling ha_get_logs..."


def test_tool_call_lifecycle() -> None:
    start = map_sdk_message(SimpleNamespace(type="tool_call", name="ha_get_history", status="running"))
    done = map_sdk_message(SimpleNamespace(type="tool_call", name="ha_get_history", status="completed"))
    assert start[0]["phase"] == "start"
    assert done[0]["text"] == "Finished ha_get_history"


def test_mcp_tool_name_is_uppercase() -> None:
    start = map_sdk_message(SimpleNamespace(type="tool_call", name="mcp", status="running"))
    done = map_sdk_message(SimpleNamespace(type="tool_call", name="mcp", status="completed"))
    assert start[0]["name"] == "mcp"
    assert start[0]["text"] == "Calling MCP..."
    assert done[0]["text"] == "Finished MCP"


def test_thinking_is_a_status() -> None:
    assert map_sdk_message(SimpleNamespace(type="thinking", text="secret chain")) == [
        {"type": "status", "text": "Thinking..."}
    ]
