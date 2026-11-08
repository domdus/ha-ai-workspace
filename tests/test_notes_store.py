"""Remembered notes in storage: YAML, the Configure form, warm Cursor agents, and Change History."""

import asyncio
from types import SimpleNamespace

from custom_components.ai_workspace import notes
from custom_components.ai_workspace.const import DOMAIN


class _FakeStore:
    def __init__(self, data=None):
        self.data = data

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = dict(data)


def _hass(monkeypatch, data=None):
    store = _FakeStore(data)
    monkeypatch.setattr(notes, "_store", lambda hass: store)
    settings = SimpleNamespace(notes=True, notes_text="")
    hass = SimpleNamespace(data={DOMAIN: {"settings": settings}})
    return hass, store, settings


def test_yaml_sets_notes_only_when_its_value_changes(monkeypatch) -> None:
    hass, store, settings = _hass(monkeypatch)
    assert asyncio.run(notes.async_apply_yaml_notes(hass, "- Quiet after 22:00")) is True
    assert settings.notes_text == "- Quiet after 22:00"
    # The agent adds a note. A restart with the same YAML keeps it.
    store.data["text"] = "- Quiet after 22:00\n- Ask before unlocking doors"
    assert asyncio.run(notes.async_apply_yaml_notes(hass, "- Quiet after 22:00")) is False
    assert store.data["text"].endswith("Ask before unlocking doors")
    # Editing notes_text in YAML sets the notes again.
    assert asyncio.run(notes.async_apply_yaml_notes(hass, "- Short answers")) is True
    assert store.data["text"] == "- Short answers"


def test_yaml_matching_old_notes_is_not_a_change(monkeypatch) -> None:
    hass, store, _ = _hass(monkeypatch, {"text": "- Short answers"})
    assert asyncio.run(notes.async_apply_yaml_notes(hass, "- Short answers")) is False
    assert store.data == {"text": "- Short answers", "yaml": "- Short answers"}


def test_untouched_form_keeps_what_the_agent_wrote(monkeypatch) -> None:
    hass, store, _ = _hass(monkeypatch, {"text": "- A"})
    shown = "- A"
    store.data["text"] = "- A\n- B from the agent"
    assert asyncio.run(notes.async_save_form_notes(hass, "- A", shown)) is False
    assert store.data["text"] == "- A\n- B from the agent"
    assert asyncio.run(notes.async_save_form_notes(hass, "- A\n- C", shown)) is True
    assert store.data["text"] == "- A\n- C"


def test_tool_writes_one_at_a_time(monkeypatch) -> None:
    hass, store, _ = _hass(monkeypatch, {"text": ""})
    client = notes.NotesClient(hass)

    async def run():
        await asyncio.gather(
            client.call_tool(notes.TOOL_NAME, {"action": "add", "text": "first"}),
            client.call_tool(notes.TOOL_NAME, {"action": "add", "text": "second"}),
        )

    asyncio.run(run())
    assert store.data["text"] == "- first\n- second"


def test_warm_cursor_agent_hears_about_changed_notes() -> None:
    hass = SimpleNamespace(data={})
    settings = SimpleNamespace(notes=True, notes_text="- A")
    assert notes.notes_update(hass, settings, "chat") == ""
    assert notes.notes_update(hass, settings, "chat") == ""
    settings.notes_text = "- A\n- B"
    update = notes.notes_update(hass, settings, "chat")
    assert "changed" in update and update.endswith("- A\n- B")
    assert notes.notes_update(hass, settings, "chat") == ""
    settings.notes_text = "- C"
    # A fresh agent gets the standing prompt with the notes anyway.
    assert notes.notes_update(hass, settings, "chat", fresh=True) == ""
    assert notes.notes_update(hass, SimpleNamespace(notes=False, notes_text="- D"), "chat") == ""


def test_note_write_is_in_change_history_and_can_be_undone(monkeypatch) -> None:
    from custom_components.ai_workspace import activity_ha
    from custom_components.ai_workspace.logical_commit import document_is_restorable, turn_bucket

    hass, store, _ = _hass(monkeypatch, {"text": "- Keep evenings quiet"})
    client = notes.NotesClient(hass)

    async def write(action, text):
        token = await activity_ha.prepare(hass, "u1", "Dom", "Claude", "notes__workspace_notes", {"action": action, "text": text}, "chat")
        result = await client.call_tool(notes.TOOL_NAME, {"action": action, "text": text})
        await activity_ha.commit(hass, None, token, ok=True)
        return result

    asyncio.run(write("add", "Ask before unlocking doors"))
    asyncio.run(write("replace", "- Short answers"))
    # Nothing changed: no row.
    asyncio.run(write("remove", "vacuum the kitchen floor"))
    fragments = turn_bucket(hass, "u1", "chat").fragments
    assert [item.summary for item in fragments] == ["Added a remembered note", "Rewrote the remembered notes"]
    assert fragments[0].document["text"] == "- Keep evenings quiet"
    combined = {"kind": "logical_commit", "changes": [{"document": item.document} for item in fragments]}
    assert document_is_restorable(combined)
    asyncio.run(activity_ha.rollback(hass, combined))
    # Undo puts back how the notes were before the turn, not between the two writes.
    assert store.data["text"] == "- Keep evenings quiet"
