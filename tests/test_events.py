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


def test_mcp_wrapper_uses_nested_tool_name() -> None:
    start = map_sdk_message(
        SimpleNamespace(
            type="tool_call",
            name="mcp",
            status="running",
            call_id="c1",
            args={"server": "home-assistant", "toolName": "GetLiveContext", "arguments": {"name": "kitchen"}},
        )
    )
    done = map_sdk_message(
        SimpleNamespace(
            type="tool_call",
            name="mcp",
            status="completed",
            call_id="c1",
            args={"server": "home-assistant", "toolName": "ha_get_automations"},
        )
    )
    assert start[0]["name"] == "GetLiveContext"
    assert start[0]["text"] == "Calling GetLiveContext..."
    assert start[0]["id"] == "c1"
    assert done[0]["name"] == "ha_get_automations"
    assert done[0]["text"] == "Finished ha_get_automations"


def test_call_mcp_tool_block_uses_input_tool_name() -> None:
    message = SimpleNamespace(
        type="assistant",
        message=SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="u1",
                    name="CallMcpTool",
                    input={"server": "ha-mcp", "toolName": "ha_get_logs"},
                )
            ]
        ),
    )
    events = map_sdk_message(message)
    assert events[0]["name"] == "ha_get_logs"
    assert events[0]["text"] == "Calling ha_get_logs..."
    assert events[0]["id"] == "u1"


def test_thinking_is_a_status() -> None:
    assert map_sdk_message(SimpleNamespace(type="thinking", text="secret chain")) == [
        {"type": "status", "text": "Thinking..."}
    ]


def test_status_error_is_surfaced() -> None:
    events = map_sdk_message(SimpleNamespace(type="status", status="ERROR", error="usage limited"))
    assert events == [{"type": "error", "message": "usage limited"}]
