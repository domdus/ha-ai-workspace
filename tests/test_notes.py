import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str, package: str = "ai_workspace_notes_pkg"):
    if package not in sys.modules:
        pkg = type(sys)(package)
        pkg.__path__ = [str(ROOT / "custom_components" / "ai_workspace")]
        pkg.__package__ = package
        sys.modules[package] = pkg
    path = ROOT / "custom_components" / "ai_workspace" / rel
    spec = importlib.util.spec_from_file_location(f"{package}.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = package
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _notes():
    if "ai_workspace_notes_pkg.const" not in sys.modules:
        _load("const.py", "const")
    return _load("notes.py", "notes")


def test_add_and_duplicate() -> None:
    notes = _notes()
    first = notes.apply_notes_action("", "add", "Do not mass-toggle lights")
    assert first["ok"] is True
    assert first["notes"] == "- Do not mass-toggle lights"
    again = notes.apply_notes_action(first["notes"], "add", "- Do not mass-toggle lights")
    assert again["ok"] is True
    assert again["notes"] == first["notes"]


def test_remove_and_replace() -> None:
    notes = _notes()
    current = "- Keep evenings quiet\n- Ask before unlocking doors"
    removed = notes.apply_notes_action(current, "remove", "unlocking")
    assert removed["ok"] is True
    assert removed["notes"] == "- Keep evenings quiet"
    missing = notes.apply_notes_action(current, "remove", "vacuum")
    assert missing["ok"] is False
    assert missing["error"] == "not_found"
    replaced = notes.apply_notes_action(current, "replace", "- Ask before guest mode")
    assert replaced["notes"] == "- Ask before guest mode"


def test_full_add_is_refused() -> None:
    notes = _notes()
    filler = "- " + ("x" * (notes.NOTES_MAX_CHARS - 4))
    assert len(filler) == notes.NOTES_MAX_CHARS - 2
    result = notes.apply_notes_action(filler, "add", "another fact")
    assert result["ok"] is False
    assert result["error"] == "full"
    assert result["notes"] == filler
    too_long = notes.apply_notes_action("", "replace", "y" * (notes.NOTES_MAX_CHARS + 1))
    assert too_long["ok"] is False
    assert too_long["error"] == "full"


def test_clip_prefers_a_line_break() -> None:
    notes = _notes()
    text = ("a" * 1200) + "\n" + ("b" * 1200)
    clipped = notes.clip_notes(text)
    assert len(clipped) <= notes.NOTES_MAX_CHARS
    assert clipped.endswith("a")
    assert "b" not in clipped
    assert notes.as_bullet("plain fact") == "- plain fact"


def test_default_is_off() -> None:
    notes = _notes()
    unset = SimpleNamespace(notes=False, notes_text="- leftover")
    assert notes.notes_prompt(unset, admin=True) == ""
    assert notes.remember_nudge(unset, "Merke dir das", admin=True) == ""


def test_prompt_stays_empty_when_disabled() -> None:
    notes = _notes()
    off = SimpleNamespace(notes=False, notes_text="- Do not invent states")
    assert notes.notes_prompt(off, admin=True) == ""
    on = SimpleNamespace(notes=True, notes_text="- Do not invent states")
    text = notes.notes_prompt(on, admin=True, write=True)
    assert "- Do not invent states" in text
    assert "workspace_notes" in text
    guest = notes.notes_prompt(on, admin=False, write=False)
    assert "- Do not invent states" in guest
    assert "workspace_notes" not in guest


def test_remember_cues_cover_chat_languages() -> None:
    notes = _notes()
    phrases = (
        "Please remember this: no party mode after 22:00",
        "Merke dir das für später",
        "Souviens-toi de ça",
        "Acuérdate de no apagar todo",
        "Ricordati che non voglio mass actions",
        "Onthoud dit alsjeblieft",
        "Zapamiętaj proszę",
        "Zapamatuj si to",
        "Kom ihåg det här",
        "Запомни это",
        "이거 기억해",
        "记住这个",
        "記住這個",
        "Bunu yadda saxla",
        "Memoru tion",
        "Hör auf damit, das ist nervig",
        "Don't do that again",
    )
    for phrase in phrases:
        assert notes.wants_notes_write(phrase), phrase
    assert not notes.wants_notes_write("Wie ist das Wetter morgen?")
    settings = SimpleNamespace(notes=True)
    assert "workspace_notes" in notes.remember_nudge(settings, "Merke dir das", admin=True)
    assert notes.remember_nudge(settings, "Merke dir das", admin=False) == ""
    assert notes.remember_nudge(SimpleNamespace(notes=False), "Merke dir das", admin=True) == ""
    default = SimpleNamespace(notes=True, notes_text="")
    empty = notes.notes_prompt(default, admin=True, write=True)
    assert "workspace_notes" in empty
    assert "Remembered notes (English" not in empty
