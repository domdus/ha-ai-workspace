"""Every agent error reaches the chat as one readable message."""

import json

from custom_components.ai_workspace.error_text import public_error

_BUSY = "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later."


def test_response_bodies_become_their_message() -> None:
    gemini = json.dumps([{"error": {"code": 503, "message": _BUSY, "status": "UNAVAILABLE"}}], indent=2)
    assert public_error(gemini) == _BUSY
    assert public_error(f"Gemini API error 503: {gemini}") == _BUSY
    assert public_error('{"detail": "Session not found"}') == "Session not found"
    assert public_error('{"error": "invalid_api_key"}') == "invalid_api_key"
    assert public_error('{"error": {"status": "UNAVAILABLE"}}') == "UNAVAILABLE"
    assert public_error('Upstream failed: {"unexpected": 1}') == "Upstream failed"


def test_transport_wording_and_pages() -> None:
    assert public_error("Timeout on reading data from socket").startswith("The provider did not answer in time.")
    assert public_error("<html><body><h1>502 Bad Gateway</h1></body></html>") == "502 Bad Gateway"
    trace = 'Traceback (most recent call last):\n  File "x.py", line 1\nValueError: model not found'
    assert public_error(trace) == "ValueError: model not found"


def test_plain_messages_stay() -> None:
    assert public_error("Add an agent under AI Workspace in Devices & services.") == (
        "Add an agent under AI Workspace in Devices & services."
    )
    assert public_error("") == "The agent failed."
    assert len(public_error("x" * 1000)) == 400
