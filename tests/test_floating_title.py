"""A new chat gets its title in the header while the reply runs, also in the floating chat.

The floating chat has no chat list that would bring a saved title in later, so the server tells
the open chat about the first title, and the chat asks again when the header still says "New chat".
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("custom_components.ai_workspace")
from custom_components.ai_workspace import http  # noqa: E402
from custom_components.ai_workspace.const import DOMAIN  # noqa: E402
from custom_components.ai_workspace.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "custom_components" / "ai_workspace" / "www"
URL = "https://www.heise.de/tests/DGX-Spark-Nvidias-Desktop-KI-Computer-im-Test-1110266"
# The first title of a chat that starts with this link: the article's name, never the URL.
FIRST = "Heise: DGX Spark Nvidias Desktop KI Computer"


class _Provider:
    kind = "api"
    allow_internet = False
    check_house = True
    model = "m"
    info = SimpleNamespace(available=True, label="Test")

    def __init__(self, generated: str | None = None):
        if generated is not None:

            async def suggest_title(message, assistant):
                return generated

            self.suggest_title = suggest_title

    async def send(self, session, message, on_agent_id, **_kw):
        yield {"type": "text", "delta": "Der Artikel testet den DGX Spark."}


class _Request(dict):
    headers: dict = {}
    host = "ha:8123"
    scheme = "http"
    transport = SimpleNamespace(is_closing=lambda: False)


async def _executor(func, *args):
    return func(*args)


def _events(chunks: list[bytes]) -> list[tuple[str, dict]]:
    out = []
    for block in b"".join(chunks).decode().split("\n\n"):
        if not block.strip():
            continue
        name, data = block.split("\n", 1)
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def _run_turn(tmp_path: Path, monkeypatch, message: str, provider: _Provider, first_title: str = "New Chat"):
    async def run():
        store = Store(tmp_path / "db.sqlite")
        session = store.create_session("u1", "agent1")
        if first_title != "New Chat":
            store.rename_session("u1", session.id, first_title)
            session = store.get_session("u1", session.id)
        data = {"providers": {"agent1": provider}, "chat_jobs": set()}
        hass = SimpleNamespace(
            data={DOMAIN: data},
            async_add_executor_job=_executor,
            auth=SimpleNamespace(async_get_user=lambda uid: asyncio.sleep(0, None)),
        )
        settings = SimpleNamespace(change_history=False, model_switcher=False, cross_chat=False, context_window=0)
        monkeypatch.setattr(http, "assist_agent_ids", lambda hass_: set())

        async def no_activity(*_a, **_k):
            return {}

        monkeypatch.setattr(http, "_activity_kwargs", no_activity)
        monkeypatch.setattr(http, "_runtime_headers", lambda request_: {})
        chunks: list[bytes] = []

        class _Response:
            async def prepare(self, request):
                return None

            async def write(self, chunk):
                chunks.append(chunk)

        monkeypatch.setattr(http.web, "StreamResponse", lambda **_kw: _Response())
        lock = asyncio.Lock()
        await lock.acquire()
        view = object.__new__(http.ChatView)
        task = await view._start(
            _Request(hass_user=SimpleNamespace(id="u1")),
            hass, data, settings, store, "u1", True, session, {}, [], [], message, lock,
        )
        await asyncio.wait_for(task, timeout=20)
        saved = store.get_session("u1", session.id).title
        store.close()
        return _events(chunks), saved

    return asyncio.run(run())


def test_first_title_reaches_the_open_chat_before_the_reply(tmp_path, monkeypatch) -> None:
    # The reported chat: a long URL as first message, no generated title.
    events, saved = _run_turn(tmp_path, monkeypatch, URL, _Provider())
    assert saved == FIRST
    names = [name for name, _ in events]
    assert names[0] == "title" and events[0][1]["title"] == FIRST
    assert names.index("title") < names.index("text") < names.index("done")


def test_generated_title_follows_after_the_reply(tmp_path, monkeypatch) -> None:
    events, saved = _run_turn(tmp_path, monkeypatch, URL, _Provider("DGX Spark im Test"))
    titles = [data["title"] for name, data in events if name == "title"]
    assert titles == [FIRST, "DGX Spark im Test"]
    assert saved == "DGX Spark im Test"


def test_a_chat_with_a_title_gets_no_new_one(tmp_path, monkeypatch) -> None:
    events, saved = _run_turn(tmp_path, monkeypatch, "Und noch eine Frage", _Provider(), first_title="Kitchen leak")
    assert saved == "Kitchen leak"
    assert "title" not in [name for name, _ in events]


@pytest.mark.parametrize("placeholder", ["New Chat", "New chat", "Neuer Chat"])
def test_rename_if_default_says_what_it_set(tmp_path, placeholder) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("u1", "agent1")
    store.rename_session("u1", session.id, placeholder)
    assert store.rename_if_default(session.id, URL) == URL
    assert store.rename_if_default(session.id, "Second message") == ""
    assert store.get_session("u1", session.id).title == URL
    store.close()


def test_floating_chat_header_follows_the_title() -> None:
    chat = (WWW / "chat.js").read_text(encoding="utf-8")
    # Live title events reach the header in the send stream, the queued send and a followed reply.
    assert chat.count('name === "title" && data.title') >= 3
    assert "applySessionTitle(id, data.title);" in chat
    # Without a chat list (floating chat) the header asks the server once the reply is done.
    assert "else void syncHeaderTitle(chatId);" in chat
    assert "applySessionTitle(id, session.title);" in chat
    # "New chat" in the header is never handed to the chat list as a title.
    assert "bumpSession(chatId, titleEl.textContent)" not in chat
    assert "bumpSession(sessionId, titleEl.textContent)" not in chat


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_chat_title_module() -> None:
    subprocess.run(["node", str(ROOT / "tests" / "test_chat_title.mjs")], check=True, cwd=ROOT)


HEISE = (
    "https://www.heise.de/tests/DGX-Spark-Nvidias-Desktop-KI-Computer-im-Test-11102661.html?seite=3\n\n"
    "Die verfügbaren mini PCs haben alle Schwächen beim Speicher interface etc.\n"
    "Weißt du ob Modelle angekündigt wurden auf die es sich lohnt zu warten?"
)


class _RuntimeAgent(_Provider):
    kind = "claude"
    token_mode = "off"


def _runtime_turn(tmp_path, monkeypatch, message, written: str | None, first_title: str = "New Chat"):
    seen: dict = {}

    async def fake_runtime_chat(hass, user_id, session, message_, *args, **kwargs):
        seen.update(kwargs)
        yield {"type": "text", "delta": "Angekündigt sind ..."}
        if written is not None:
            yield {"type": "title", "title": written}
        yield {"type": "done", "answer": "Angekündigt sind ..."}

    monkeypatch.setattr(http, "_runtime_chat", fake_runtime_chat)
    monkeypatch.setattr(http, "_is_runtime_provider", lambda provider: True)
    events, saved = _run_turn(tmp_path, monkeypatch, message, _RuntimeAgent(), first_title)
    return events, saved, seen


def test_runtime_agent_is_asked_for_a_title_on_the_first_turn(tmp_path, monkeypatch) -> None:
    # The reported chat ran on a Runtime agent: until now it never got a written title.
    events, saved, seen = _runtime_turn(tmp_path, monkeypatch, HEISE, "Heise Artikel über Nvidia Spark")
    assert seen["title"] is True
    titles = [data["title"] for name, data in events if name == "title"]
    assert titles == ["Heise: DGX Spark Nvidias Desktop KI Computer", "Heise Artikel über Nvidia Spark"]
    assert saved == "Heise Artikel über Nvidia Spark"


def test_runtime_title_never_overwrites_a_real_title(tmp_path, monkeypatch) -> None:
    events, saved, seen = _runtime_turn(
        tmp_path, monkeypatch, HEISE, "Heise Artikel über Nvidia Spark", first_title="Mini PC Kauf"
    )
    assert saved == "Mini PC Kauf"
    assert "title" not in [name for name, _ in events]


def test_short_first_message_asks_the_runtime_for_no_title(tmp_path, monkeypatch) -> None:
    _, saved, seen = _runtime_turn(tmp_path, monkeypatch, "Status der Bewässerung?", None)
    assert seen["title"] is False
    assert saved == "Status der Bewässerung"


def test_runtime_payload_carries_title_now_only_when_asked(monkeypatch) -> None:
    from test_claude_auth_error import _Stream

    def send(title: bool, mode: str = "off") -> dict:
        sent: dict = {}

        class Session:
            async def post(self, url, json=None, headers=None, timeout=None):
                sent.update(json or {})
                return _Stream([{"type": "done", "answer": "ok"}])

        async def ensure(*a, **k):
            return True

        hass = SimpleNamespace(data={DOMAIN: {"runtime_url": "http://rt:8090", "settings": None, "providers": {}}})
        monkeypatch.setattr(http, "async_get_clientsession", lambda hass_: Session())
        monkeypatch.setattr(http, "_ensure_runtime_session", ensure)
        monkeypatch.setattr(http, "_runtime_headers_for", lambda *a, **k: {})
        monkeypatch.setattr(http, "standing_chat_prompt", lambda *a, **k: "")
        monkeypatch.setattr(http, "house_zone", lambda hass_: None)
        monkeypatch.setattr(http, "issue_callback_key", lambda *a, **k: "key")
        chat = SimpleNamespace(id="s1", agent_id="", provider="claude")

        async def collect():
            return [
                e
                async for e in http._runtime_chat(
                    hass, "u1", chat, HEISE, token_mode=mode, runtime_provider="claude", title=title
                )
            ]

        asyncio.run(collect())
        return sent

    assert send(True)["title_now"] is True
    assert "title_now" not in send(False)
    # Save tokens: no extra call for a title.
    assert "title_now" not in send(True, "medium")
