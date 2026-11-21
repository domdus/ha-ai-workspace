

def _scope():
    from custom_components.ai_workspace import chat_scope

    return chat_scope


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


def test_handoff_includes_title_and_keeps_tables_and_line_breaks() -> None:
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
            "Wenn du willst, setze ich A55-von-Alex auf die Person.",
        ),
        Row("user", "Ja mach mal."),
    ]
    note = scope.handoff_note(rows, "Handy nicht zu Hause")
    assert 'titled "Handy nicht zu Hause"' in note
    assert "Handy-Tracker kaputt?" in note
    assert "setze ich A55-von-Alex" in note
    assert "| Galaxy-A55-5G | not_home |\n" in note
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
    assert "same Home Assistant chat" in note
    assert "source of truth" in note
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


def test_handoff_keeps_recent_turns_inside_budget() -> None:
    scope = _scope()

    class Row:
        def __init__(self, role, content, events="[]"):
            self.role = role
            self.content = content
            self.events = events

    rows = []
    for index in range(12):
        rows.append(Row("user", f"Question {index} " + ("lights " * 400)))
        rows.append(Row("assistant", f"Answer {index} " + ("kitchen " * 400)))
    rows.append(Row("user", "What did we talk about?"))
    note = scope.handoff_note(rows, "Kitchen lights")
    assert "source of truth" in note
    assert "What did we talk about?" not in note
    assert "Question 11" in note
    assert "Answer 11" in note
    assert len(note) <= scope._HANDOFF_BUDGET


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


def test_merge_reply_keeps_intro_before_tools() -> None:
    scope = _scope()
    intro = "Ich suche in der Installation nach Bewässerung und dem heutigen Verlauf."
    later = "Heute ist die Bewässerung zweimal gelaufen."
    assert scope.merge_reply_text(intro, later) == f"{intro}\n\n{later}"
    assert scope.merge_reply_text(f"{intro}\n\n{later}", later) == f"{intro}\n\n{later}"
    assert scope.merge_reply_text(later, later) == later
    assert scope.merge_reply_text(later, "") == later


def test_answer_after_tools_starts_a_new_paragraph() -> None:
    scope = _scope()
    assert scope.text_after_tools(["Checking the automations."], "Two are on.") == "\n\nTwo are on."
    assert scope.text_after_tools([], "Two are on.") == "Two are on."
    assert scope.text_after_tools(["Checking.\n"], "Two are on.") == "\nTwo are on."
    assert scope.text_after_tools(["Checking.\n\n"], "Two are on.") == "Two are on."
    assert scope.text_after_tools(["Checking."], "\n\n") == "\n\n"


def test_merge_keeps_the_break_when_the_result_has_none() -> None:
    scope = _scope()
    assert scope.merge_reply_text("Checking.\n\nTwo are on.", "Checking.Two are on.") == "Checking.\n\nTwo are on."


def test_text_after_a_thinking_pause_starts_a_new_paragraph() -> None:
    from custom_components.ai_workspace.chat_scope import text_after_pause

    said = ["Einen Moment, ich schaue nach, wo die Umstellung hängt."]
    assert text_after_pause(said, "Die Umstellung war nicht fertig") == "\n\nDie Umstellung war nicht fertig"
    # A word or sentence split around the pause stays as it is.
    assert text_after_pause(["Ich stelle die Sprach"], "ausgabe um.") == "ausgabe um."
    assert text_after_pause(said, " Danach") == " Danach"
    assert text_after_pause([], "Hallo") == "Hallo"
    assert text_after_pause(["Fertig.\n\n"], "Noch was") == "Noch was"


# --- cross-chat excerpts -------------------------------------------------------------------------

_CATALOG = [
    # Newest and pinned first, like the sidebar: these must not win on recency.
    {"id": "boerse", "title": "Börse Tabelle", "pinned": True, "updated_at": "2026-11-19T10:00:00"},
    {"id": "media", "title": "Media Automation", "updated_at": "2026-11-19T09:00:00"},
    {"id": "sellpy", "title": "Sellpy", "updated_at": "2026-11-19T08:00:00"},
    {"id": "water", "title": "Bewässerung", "updated_at": "2026-11-10T08:00:00"},
    {"id": "current", "title": "New Chat", "updated_at": "2026-11-19T11:00:00"},
]


def _ids(found):
    return [item["id"] for item in found]


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "message",
    [
        "Was hatten wir im Bewässerung chat besprochen?",
        "Schau in den Bewässerungschat und mach eine neue Tabelle daraus",
        "was stand im chat zu bewaesserung",
        "Im Bewässerungs-Chat hatten wir eine Tabelle, zeig sie nochmal",
        "Was war im Bewäserung chat?",
        "Was hatten wir im Bewässerungsverlauf?",
        "Mach eine Tabelle aus dem letzten Bewässerung Thread",
    ],
)
def test_every_spelling_of_the_title_finds_the_chat(message) -> None:
    scope = _scope()
    assert _ids(scope.matching_chats(message, _CATALOG, "current")) == ["water"]


def test_newer_or_pinned_chats_do_not_win_on_common_words() -> None:
    scope = _scope()
    # "Tabelle", "neue", "letzte", "mach" are common words, not titles.
    found = scope.matching_chats("Schau in den Bewässerungschat und mach eine neue Tabelle daraus", _CATALOG, "current")
    assert _ids(found) == ["water"]
    assert scope.matching_chats("Mach eine neue Tabelle im Chat", _CATALOG, "current") == []
    assert _ids(scope.matching_chats("Was war im Media chat?", _CATALOG, "current")) == ["media"]
    assert _ids(scope.matching_chats("Was sagt der Sellpy-Chat?", _CATALOG, "current")) == ["sellpy"]


def test_folding_stemming_and_scores() -> None:
    scope = _scope()
    assert scope.fold("Bewässerungs-Chat Größe") == "bewaesserungs-chat groesse"
    assert scope.stem("bewaesserungs") == "bewaesserung"
    whole = scope.score_title("im Bewässerung chat", "Bewässerung")
    near = scope.score_title("im Media chat", "Media Automation")
    share = scope.score_title("media automation stuff", "Media Automation Garden")
    assert whole > near > share > 0
    assert scope.score_title("im Garten chat", "Bewässerung") == 0
    assert scope.mentions_chat("Bewässerungschat") and not scope.mentions_chat("Bewässerung heute")


def test_neighbor_chat_without_a_title() -> None:
    scope = _scope()
    assert scope.matching_chats("Was stand im anderen Chat?", _CATALOG, "current") == []
    near = scope.neighbor_chat("Was stand im anderen Chat?", _CATALOG, "current")
    assert near["id"] == "boerse"  # most recently updated other chat
    assert scope.neighbor_chat("Fass den vorigen Chat zusammen", _CATALOG, "current")["id"] == "boerse"
    assert scope.neighbor_chat("Wie ist das Wetter?", _CATALOG, "current") is None


class _Row:
    def __init__(self, role, content, events="[]", row_id=0, created_at=""):
        self.role = role
        self.content = content
        self.events = events
        self.id = row_id
        self.created_at = created_at


_TABLE = (
    "Hier die Laufzeiten:\n\n"
    "| Zone | Dauer | Liter |\n"
    "| --- | --- | --- |\n"
    + "".join(f"| Zone {n} | {n * 3} min | {n * 12} l |\n" for n in range(1, 120))
    + "\nSoll ich das als Automation anlegen?"
)


def test_long_newest_reply_keeps_its_table_and_line_breaks() -> None:
    scope = _scope()
    rows = [_Row("user", f"Frage {n} " + "x" * 300) if n % 2 == 0 else _Row("assistant", f"Antwort {n} " + "y" * 600) for n in range(30)]
    rows += [_Row("user", "Mach mir eine Tabelle der Laufzeiten"), _Row("assistant", _TABLE)]
    note = scope.chat_excerpt("Bewässerung", rows, budget=16000)
    assert len(note) <= 16000 + 200
    assert "| Zone | Dauer | Liter |\n| --- | --- | --- |\n| Zone 1 | 3 min | 12 l |\n" in note
    # Cut only at a line end: every table row that is there is whole.
    for line in note.splitlines():
        if line.startswith("| Zone ") and line != "| Zone | Dauer | Liter |":
            assert line.endswith(" l |"), line
    assert "Mach mir eine Tabelle der Laufzeiten" in note
    assert "ältere Nachrichten ausgelassen" in note
    assert "Summary of the older messages" in note


def test_budget_is_filled_from_the_newest_message_back() -> None:
    scope = _scope()
    rows = []
    for n in range(40):
        rows.append(_Row("user", f"Frage {n}: " + "a" * 500))
        rows.append(_Row("assistant", f"Antwort {n}: " + "b" * 900))
    note = scope.chat_excerpt("Bewässerung", rows, budget=6000)
    assert "Antwort 39:" in note and "Frage 39:" in note
    assert "Antwort 0:" not in note.split("ältere Nachrichten ausgelassen]")[-1]
    kept = note.split("ältere Nachrichten ausgelassen]")[1]
    assert kept.index("Frage 38") < kept.index("Antwort 39")  # shown oldest to newest
    assert len(note) <= 6400
    short = scope.chat_excerpt("Bewässerung", rows[-2:], budget=6000)
    assert "ausgelassen" not in short


def test_a_single_long_message_is_marked_cut() -> None:
    scope = _scope()
    text = "\n".join(f"Zeile {n} " + "z" * 80 for n in range(400))
    note = scope.chat_excerpt("Bewässerung", [_Row("user", "zeig"), _Row("assistant", text)], budget=4000, reply_cap=3000)
    assert "[gekürzt]" in note
    body = note.split("Assistant: ", 1)[1].split("\n[gekürzt]")[0]
    assert body.splitlines()[-1].startswith("Zeile ")
    assert body.splitlines()[-1].endswith("z" * 80)


def test_excerpt_survives_clipping() -> None:
    scope = _scope()
    message = "x" * 5000
    note = scope.chat_excerpt("Bewässerung", [_Row("user", "a"), _Row("assistant", "Tabelle: | a |")])
    clipped = scope.clip_keeping_excerpt(f"{message}\n\n{note}", 1200)
    assert clipped.startswith("x" * 1200) and "x" * 1201 not in clipped
    assert clipped.endswith(note)
    assert scope.clip_keeping_excerpt("short", 1200) == "short"


class _Store:
    def __init__(self, sessions, messages):
        self._sessions = sessions
        self._messages = messages

    def list_sessions(self, user_id, query=""):
        from types import SimpleNamespace

        return [SimpleNamespace(**item) for item in self._sessions if item["user_id"] == user_id]

    def list_messages(self, session_id):
        return self._messages.get(session_id, [])


def _store():
    sessions = [
        {"id": "boerse", "user_id": "u1", "title": "Börse Tabelle", "pinned": True, "updated_at": "2026-11-19T10"},
        {"id": "water", "user_id": "u1", "title": "Bewässerung", "pinned": False, "updated_at": "2026-11-10T10"},
        {"id": "current", "user_id": "u1", "title": "Neuer Chat", "pinned": False, "updated_at": "2026-11-19T11"},
        {"id": "other-user", "user_id": "u2", "title": "Bewässerung", "pinned": False, "updated_at": "2026-11-19T12"},
    ]
    messages = {
        "water": [_Row("user", "Wie lange läuft Zone 1?", row_id=1), _Row("assistant", _TABLE, row_id=2)],
        "boerse": [_Row("user", "Aktien", row_id=3), _Row("assistant", "| Aktie | Kurs |\n| A | 1 |", row_id=4)],
        "other-user": [_Row("assistant", "geheim", row_id=5)],
    }
    return _Store(sessions, messages)


def test_other_chat_context_logs_and_names_the_chat(caplog) -> None:
    scope = _scope()
    import logging

    with caplog.at_level(logging.INFO, logger="custom_components.ai_workspace.chat_scope"):
        note, chats = scope.other_chat_context(_store(), "u1", "current", "Was war im Bewässerungschat?")
    assert chats == [{"id": "water", "title": "Bewässerung"}]
    assert scope.CROSS_MARK in note and "| Zone 1 | 3 min | 12 l |" in note
    assert "geheim" not in note
    assert any("cross-chat excerpt" in rec.message and "chars=" in rec.message for rec in caplog.records)
    event = scope.cross_chat_event(note, chats)
    assert scope.public_events([event]) == [{"type": "cross_chat", "chats": chats, "chars": len(note)}]


def test_save_modes_get_a_smaller_excerpt() -> None:
    scope = _scope()
    from custom_components.ai_workspace.const import (
        TOKEN_MODE_EXTREME,
        TOKEN_MODE_LIGHT,
        TOKEN_MODE_MEDIUM,
        TOKEN_MODE_OFF,
        cross_chat_budget,
    )

    sizes = []
    for mode in (TOKEN_MODE_OFF, TOKEN_MODE_LIGHT, TOKEN_MODE_MEDIUM, TOKEN_MODE_EXTREME):
        note, _ = scope.other_chat_context(_store(), "u1", "current", "im Bewässerung chat?", False, cross_chat_budget(mode))
        assert note and scope.CROSS_MARK in note
        assert len(note) <= cross_chat_budget(mode) + 200
        sizes.append(len(note))
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > sizes[-1]


def test_neighbor_phrase_reads_the_last_updated_chat() -> None:
    scope = _scope()
    note, chats = scope.other_chat_context(_store(), "u1", "current", "Was stand im anderen Chat?")
    assert chats == [{"id": "boerse", "title": "Börse Tabelle"}]
    assert "| Aktie | Kurs |" in note


def test_handoff_and_history_carry_an_earlier_excerpt() -> None:
    import json as _json

    scope = _scope()
    note, chats = scope.other_chat_context(_store(), "u1", "current", "im Bewässerung chat?")
    event = _json.dumps([scope.cross_chat_event(note, chats)])
    rows = [
        _Row("user", "Was war im Bewässerung chat?", event),
        _Row("assistant", "Zone 1 läuft 3 Minuten."),
        _Row("user", "Und Zone 2?"),
    ]
    handoff = scope.handoff_note(rows, "Neuer Chat")
    assert scope.PRIOR_EXCERPT_LEAD in handoff and "| Zone 2 | 6 min | 24 l |" in handoff
    history = scope.with_prior_excerpt([{"role": "user", "content": "Was war im Bewässerung chat?"}], rows, "Und Zone 2?")
    assert "| Zone 2 | 6 min | 24 l |" in history[0]["content"]
    # The turn that brings its own excerpt does not get the old one again.
    fresh = rows[:-1] + [_Row("user", "im Bewässerung chat nochmal", event)]
    assert scope.prior_excerpt(fresh) == ""


# --- list_chats / read_chat ----------------------------------------------------------------------


def test_list_and_read_chat_tools_are_per_user_and_read_only() -> None:
    from custom_components.ai_workspace import chat_tools

    store = _store()
    listed = chat_tools.list_chats(store, "u1", "bewaesserung")
    assert [item["id"] for item in listed["chats"]] == ["water"]
    everything = chat_tools.list_chats(store, "u1")
    assert {item["id"] for item in everything["chats"]} == {"boerse", "water"}
    assert "other-user" not in {item["id"] for item in everything["chats"]}
    read = chat_tools.read_chat(store, "u1", "Bewässerungs-Chat", last_n=2, max_chars=5000)
    assert read["ok"] and read["id"] == "water"
    assert "| Zone 1 | 3 min | 12 l |\n" in read["text"]
    assert chat_tools.read_chat(store, "u1", "water")["id"] == "water"
    assert chat_tools.read_chat(store, "u2", "water")["ok"] is False  # someone else's chat id
    assert chat_tools.read_chat(store, "u1", "Raumfahrt")["ok"] is False
    names = {tool["name"] for tool in chat_tools.tool_definitions()}
    assert names == {"list_chats", "read_chat"}
    assert all(tool["annotations"]["readOnlyHint"] for tool in chat_tools.tool_definitions())


def test_chats_client_calls_the_tools() -> None:
    import asyncio
    from types import SimpleNamespace

    from custom_components.ai_workspace import chat_tools

    async def executor(func, *args):
        return func(*args)

    client = chat_tools.ChatsClient(SimpleNamespace(async_add_executor_job=executor), _store(), "u1", "current")

    async def run():
        listed = await client.call_tool("list_chats", {"query": "Börse"})
        read = await client.call_tool("read_chat", {"title_or_id": "Börse Tabelle"})
        return listed, read

    listed, read = asyncio.run(run())
    assert listed["chats"][0]["id"] == "boerse"
    assert "| Aktie | Kurs |" in read["text"]


def test_agents_are_told_about_the_chat_tools() -> None:
    from pathlib import Path

    from custom_components.ai_workspace.const import with_language_rule

    assert "read_chat" in with_language_rule("Base") and "list_chats" in with_language_rule("Base")
    prompt = (Path(__file__).resolve().parents[1] / "ai_workspace" / "app" / "prompt.py").read_text(encoding="utf-8")
    assert "read_chat tool" in prompt


def test_verlauf_alone_needs_the_whole_title() -> None:
    scope = _scope()
    chats = [{"id": "temp", "title": "Temperatur Sensoren"}, {"id": "current", "title": "New Chat"}]
    # In Home Assistant "Verlauf" is mostly an entity's history.
    assert scope.matching_chats("Wie war der Temperaturverlauf gestern?", chats, "current") == []
    assert _ids(scope.matching_chats("Wie war der Temperatur chat?", chats, "current")) == ["temp"]
    assert _ids(scope.matching_chats("Was stand im Verlauf Temperatur Sensoren?", chats, "current")) == ["temp"]
