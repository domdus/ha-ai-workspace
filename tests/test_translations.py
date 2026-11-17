from pathlib import Path
import json
import re

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


def _flat(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
EN_TEXT = _flat(_load(BASE / "translations" / "en.json"))


@pytest.mark.parametrize("path", LANGS, ids=lambda p: p.stem)
def test_translation_keeps_every_placeholder(path):
    text = _flat(_load(path))
    wrong = {
        key: value
        for key, value in text.items()
        if sorted(_PLACEHOLDER.findall(value)) != sorted(_PLACEHOLDER.findall(EN_TEXT.get(key, "")))
    }
    assert wrong == {}


@pytest.mark.parametrize("path", [p for p in LANGS if p.stem != "en"], ids=lambda p: p.stem)
def test_agent_form_is_not_english_again(path):
    # 1.6.0b1 once overwrote every locale's agent form with English. Short labels such as
    # "Model" or "Claude SDK" may match; whole forms in English may not.
    section = "config_subentries.agent."
    text = {k: v for k, v in _flat(_load(path)).items() if k.startswith(section) and len(EN_TEXT.get(k, "")) > 25}
    same = [k for k, v in text.items() if v == EN_TEXT[k] and _PLACEHOLDER.sub("", v).strip()]
    assert len(same) <= len(text) // 10, same[:10]
