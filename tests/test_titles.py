from app.store import Store
from app.titles import (
    accept_generated_title,
    clean_title,
    is_placeholder_title,
    needs_title_summary,
    title_from_prompt,
    title_prompt,
)


def test_clean_title_strips_quotes_and_prefix() -> None:
    assert clean_title('Title: "Garage lights"\nMore') == "Garage lights"
    assert clean_title("  Kitchen leak.  ") == "Kitchen leak"
    assert clean_title("**headline**") == "headline"
    assert clean_title("Status **of** lights") == "Status of lights"


def test_short_prompt_stays_the_title() -> None:
    assert title_from_prompt("Status?") == "Status"
    assert title_from_prompt("Status der Bewässerung?") == "Status der Bewässerung"
    assert not needs_title_summary("Status?")
    assert not needs_title_summary("Status der Bewässerung?")


def test_long_prompt_needs_a_summary() -> None:
    prompt = (
        "Die dreame extension hat ein großes 2.0.1 update bekommen und liefert "
        "jetzt wohl auch lovelace maps usw.."
    )
    assert needs_title_summary(prompt)
    assert accept_generated_title(prompt, "Lovelace maps nach Dreame Update") == (
        "Lovelace maps nach Dreame Update"
    )
    assert accept_generated_title(prompt, "Home Assistant MCP assistance") == ""
    assert accept_generated_title(prompt, prompt[:40]) == ""


def test_title_prompt_uses_the_question_only() -> None:
    prompt = title_prompt("Can you check the garage light automation?", "It did not fire.")
    assert "garage light" in prompt
    assert "It did not fire." not in prompt
    assert "Assistant:" not in prompt


def test_apply_generated_title_replaces_first_prompt(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("local", "cursor")
    first = "Die dreame extension hat ein großes 2.0.1 update bekommen"
    store.rename_if_default(session.id, first)
    assert (
        store.apply_generated_title("local", session.id, first, "Lovelace maps nach Dreame Update")
        == "Lovelace maps nach Dreame Update"
    )
    store.rename_session("local", session.id, "Kitchen leak")
    assert store.apply_generated_title("local", session.id, first, "Something else") is None
    assert store.get_session("local", session.id).title == "Kitchen leak"
    store.close()


def test_placeholder_is_new_chat_or_first_prompt() -> None:
    assert is_placeholder_title("New Chat", "Why no water?")
    assert is_placeholder_title("Why no water?", "Why no water?")
    assert is_placeholder_title("Why no water", "Why no water?")
    assert not is_placeholder_title("Kitchen leak", "Why no water?")


def test_rename_does_not_change_chat_order(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    older = store.create_session("local", "cursor")
    newer = store.create_session("local", "cursor")
    store.add_message(older.id, "user", "first")
    store.add_message(newer.id, "user", "second")
    assert [item.id for item in store.list_sessions("local")] == [newer.id, older.id]
    store.rename_session("local", older.id, "Renamed older chat")
    sessions = store.list_sessions("local")
    assert [item.id for item in sessions] == [newer.id, older.id]
    assert sessions[1].title == "Renamed older chat"
    store.close()


def test_pinned_chats_sort_above_unpinned(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    older = store.create_session("local", "cursor")
    newer = store.create_session("local", "cursor")
    store.add_message(older.id, "user", "first")
    store.add_message(newer.id, "user", "second")
    store.set_pinned("local", older.id, True)
    sessions = store.list_sessions("local")
    assert [item.id for item in sessions] == [older.id, newer.id]
    assert sessions[0].pinned is True
    store.set_pinned("local", older.id, False)
    sessions = store.list_sessions("local")
    assert [item.id for item in sessions] == [newer.id, older.id]
    store.close()


# The reported chat: a Heise link as the first line, then the question in German.
HEISE = (
    "https://www.heise.de/tests/DGX-Spark-Nvidias-Desktop-KI-Computer-im-Test-11102661.html?seite=3\n\n"
    "Die verfügbaren mini PCs haben alle Schwächen beim Speicher interface etc.\n"
    "Weißt du ob Modelle angekündigt wurden auf die es sich lohnt zu warten? Wo die Schwächen beseitigt werden?"
)


def test_a_link_never_becomes_the_title() -> None:
    title = title_from_prompt(HEISE)
    assert title == "Heise: DGX Spark Nvidias Desktop KI Computer"
    assert "http" not in title and "heise.de" not in title
    # The link alone, as the floating chat once showed it cut at 80 characters.
    assert title_from_prompt(HEISE.split("\n")[0][:80]) == title
    assert needs_title_summary(HEISE)


def test_link_without_a_slug_leaves_the_words() -> None:
    assert title_from_prompt("Kannst du das erklären? https://www.youtube.com/watch?v=dQw4w9WgXcQ") == (
        "Kannst du das erklären"
    )
    assert title_from_prompt("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "YouTube"
    assert title_from_prompt("https://www.home-assistant.io/integrations/mqtt/") == "Home Assistant: mqtt"


def test_long_text_is_cut_to_a_few_words_of_the_first_sentence() -> None:
    title = title_from_prompt(
        "Die verfügbaren mini PCs haben alle Schwächen beim Speicher interface etc. Weißt du mehr?"
    )
    assert title == "Die verfügbaren mini PCs"
    assert len(title.split()) <= 6 and len(title) <= 48
    # No dangling little word at the end.
    assert title_from_prompt("Warum geht das Licht in der Küche nicht mehr an") == "Warum geht das Licht"


def test_generated_title_replaces_the_first_title_but_no_url() -> None:
    assert accept_generated_title(HEISE, "Heise Artikel über Nvidia Spark") == "Heise Artikel über Nvidia Spark"
    assert accept_generated_title(HEISE, "https://www.heise.de/tests/DGX-Spark") == ""
    assert is_placeholder_title(title_from_prompt(HEISE), HEISE)
    # Older versions stored the first line cut at 80 characters: still automatic, may be replaced.
    assert is_placeholder_title(HEISE.replace("\n", " ")[:80], HEISE)
    assert not is_placeholder_title("Nvidia Spark Alternativen", HEISE)


def test_apply_generated_title_replaces_a_link_title(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("local", "cursor")
    store.rename_if_default(session.id, title_from_prompt(HEISE))
    assert store.apply_generated_title("local", session.id, HEISE, "Heise Artikel über Nvidia Spark") == (
        "Heise Artikel über Nvidia Spark"
    )
    store.close()
