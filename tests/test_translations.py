from pathlib import Path
import json

import pytest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace"
LANGS = sorted((BASE / "translations").glob("*.json"))


def _keys(node: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out |= _keys(value, f"{path}.")
        else:
            out.add(path)
    return out


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


EN = _keys(_load(BASE / "translations" / "en.json"))


def test_strings_match_english():
    assert _keys(_load(BASE / "strings.json")) == EN


@pytest.mark.parametrize("path", LANGS, ids=lambda p: p.stem)
def test_translation_has_every_key(path):
    keys = _keys(_load(path))
    assert sorted(EN - keys) == []
    assert sorted(keys - EN) == []


def test_setup_and_options_forms_share_sections():
    doc = _load(BASE / "strings.json")
    setup = doc["config"]["step"]["user"]["sections"]
    options = doc["options"]["step"]["init"]["sections"]
    for group in ("chat", "cost", "house", "prompt"):
        assert setup[group]["data"].keys() == options[group]["data"].keys()
        assert setup[group]["data"].keys() == setup[group]["data_description"].keys()
