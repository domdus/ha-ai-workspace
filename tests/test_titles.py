from app.store import Store
from app.titles import clean_title, is_placeholder_title, title_prompt


def test_clean_title_strips_quotes_and_prefix() -> None:
    assert clean_title('Title: "Garage lights"\nMore') == "Garage lights"
    assert clean_title("  Kitchen leak.  ") == "Kitchen leak"
    assert clean_title("**headline**") == "headline"
    assert clean_title("Status **of** lights") == "Status of lights"


def test_placeholder_is_first_user_message() -> None:
    assert is_placeholder_title("New Chat", "Why no water?")
    assert is_placeholder_title("New chat", "Why no water?")
    assert is_placeholder_title("Why no water?", "Why no water?")
    assert not is_placeholder_title("Kitchen leak", "Why no water?")


def test_title_prompt_uses_the_question_only() -> None:
    prompt = title_prompt("Can you check the garage light automation?", "It did not fire.")
    assert "garage light" in prompt
    assert "3 to 6 words" in prompt
    assert "It did not fire." not in prompt
    assert "Assistant:" not in prompt


def test_apply_generated_title_skips_manual_rename(tmp_path) -> None:
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session("local", "cursor")
    store.rename_if_default(session.id, "Why no water?")
    assert store.apply_generated_title("local", session.id, "Why no water?", "Garden moisture") == "Garden moisture"
    store.rename_session("local", session.id, "Kitchen leak")
    assert store.apply_generated_title("local", session.id, "Why no water?", "Something else") is None
    assert store.get_session("local", session.id).title == "Kitchen leak"
    store.close()


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
