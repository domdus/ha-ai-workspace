"""A long paste must reach the agent: the runtime once refused it with HTTP 422 because `question`
(a copy of the message, used for tool choice and the title) was over 8000 characters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import HANDOFF_CHARS, MESSAGE_CHARS, QUESTION_CHARS, ChatRequest, create_app
from test_api import FakeCursor, settings

# Roughly what was pasted: a <select> with ~350 <option> lines.
PASTE = "<select name=\"domain_ext\">\n" + "".join(
    f'\t<option value="tld{n}">tld{n}</option>\n' for n in range(350)
) + "</select>\n\nBitte eine Highlight-Liste aus wiese.<endung>"


def test_paste_is_longer_than_the_old_question_limit() -> None:
    assert len(PASTE) > 8000


def test_helper_fields_are_shortened_not_refused() -> None:
    body = ChatRequest(message=PASTE, question=PASTE, handoff="x" * 200_000 + "NEWEST", prompt="p" * 200_000)
    assert len(body.question) == QUESTION_CHARS and body.question == PASTE[:QUESTION_CHARS]
    # The handoff keeps its newest part.
    assert len(body.handoff) == HANDOFF_CHARS and body.handoff.endswith("NEWEST")
    assert len(body.prompt) == 120000
    # Four full attachments fit.
    assert MESSAGE_CHARS >= 4 * 256 * 1024 + 100_000


def test_the_chat_takes_a_long_paste(tmp_path: Path) -> None:
    cursor = FakeCursor()
    app = create_app(settings(tmp_path), {"cursor": cursor})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session = client.post("/api/sessions", json={}).json()
        reply = client.post(
            f"/api/sessions/{session['id']}/chat", json={"message": PASTE, "question": PASTE}
        )
    assert reply.status_code == 200
    assert cursor.last_message and "wiese.<endung>" in cursor.last_message


def test_integration_caps_helper_fields_for_older_runtimes() -> None:
    http = pytest.importorskip("custom_components.ai_workspace.http")
    question, handoff, prompt = http.runtime_helper_fields(PASTE, "h" * 130_000 + "END", "s" * 130_000)
    assert len(question) == 8000 and len(prompt) == 120000
    assert len(handoff) == 120000 and handoff.endswith("END") and handoff.startswith("…")
    assert http.runtime_helper_fields("short", "", "") == ("short", "", "")


def test_a_422_is_explained() -> None:
    http = pytest.importorskip("custom_components.ai_workspace.http")
    too_long = json.dumps(
        {"detail": [{"type": "string_too_long", "loc": ["body", "message"], "msg": "String should have at most 1200000 characters", "ctx": {"max_length": 1200000}}]}
    )
    text = http._runtime_error(422, too_long)
    assert "too long" in text and "1,200,000" in text and "HTTP 422" not in text
    other = json.dumps({"detail": [{"type": "string_too_long", "loc": ["body", "question"], "msg": "x", "ctx": {"max_length": 8000}}]})
    assert http._runtime_error(422, other) == "The AI Workspace Runtime refused the request: question is too long."
    odd = json.dumps({"detail": [{"type": "missing", "loc": ["body", "x"], "msg": "Field required"}]})
    assert http._runtime_error(422, odd) == "The AI Workspace Runtime refused the request: x: Field required"
    assert http._runtime_error(500, "oops") == "The AI Workspace Runtime answered HTTP 500."
