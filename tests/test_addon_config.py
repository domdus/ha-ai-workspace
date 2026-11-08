"""Checks for the App (add-on) manifest and its translations."""

from pathlib import Path

import pytest
import yaml

ADDON = Path(__file__).resolve().parent.parent / "ai_workspace"
CONFIG = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))
TRANSLATIONS = sorted((ADDON / "translations").glob("*.yaml"))


def test_default_options_are_in_schema():
    assert set(CONFIG["options"]) <= set(CONFIG["schema"])


def test_optional_url_has_no_empty_default():
    # The Supervisor rejects "" for a url? field, so a fresh install could not be saved.
    for key, kind in CONFIG["schema"].items():
        if str(kind).startswith("url") and key in CONFIG["options"]:
            assert CONFIG["options"][key], f"{key} defaults to an empty URL"


def test_fallback_toggles_are_not_defaulted():
    # The runtime defaults both to True, the same as the Docker image; the App must not override that.
    for key in ("shorten_mcp_results", "change_history"):
        assert key not in CONFIG["options"]
        assert CONFIG["schema"][key] == "bool?"


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.name)
def test_translation_covers_every_option(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in CONFIG["schema"]:
        entry = doc["configuration"].get(key)
        assert entry, f"{path.name}: {key} has no translation"
        assert entry.get("name") and entry.get("description"), f"{path.name}: {key} needs name and description"


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.name)
def test_translation_covers_every_port(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ports = {p.upper() for p in CONFIG.get("ports", {})}
    assert ports <= {p.upper() for p in doc.get("network", {})}
