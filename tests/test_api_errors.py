"""Provider errors reach the chat as the provider's message, not as a response body."""

import json
from pathlib import Path

from aiohttp import ServerTimeoutError

from custom_components.ai_workspace.api_provider import ApiProvider, _friendly_api_error
from custom_components.ai_workspace.models import Settings

_BUSY = "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later."


def test_gemini_list_wrapped_error_shows_only_the_message() -> None:
    body = json.dumps([{"error": {"code": 503, "message": _BUSY, "status": "UNAVAILABLE"}}])
    assert _friendly_api_error(503, body) == _BUSY


def test_other_shapes() -> None:
    assert _friendly_api_error(400, json.dumps({"error": {"message": "Bad tool schema"}})) == "Bad tool schema"
    assert _friendly_api_error(404, json.dumps({"detail": "Model not found"})) == "Model not found"
    assert _friendly_api_error(502, json.dumps({"unexpected": True})) == "The model provider returned HTTP 502."
    assert _friendly_api_error(502, "<html><body>Bad gateway</body></html>") == "The model provider returned HTTP 502."
    assert _friendly_api_error(500, "") == "The model provider returned HTTP 500."
    assert _friendly_api_error(500, "upstream connect error") == "upstream connect error"


def test_socket_timeout_reads_like_the_other_timeouts() -> None:
    provider = ApiProvider(
        None,
        Settings(
            data_dir=Path("/tmp"),
            workspace_dir=Path("/tmp/workspace"),
            state_dir=Path("/tmp/state"),
            cursor_api_key="",
            model="m",
            mcp_servers={},
            api_provider="gemini",
            api_key="k",
        ),
        None,
    )
    text = provider._public(ServerTimeoutError("Timeout on reading data from socket"))
    assert text.startswith("The provider did not answer in time.")
