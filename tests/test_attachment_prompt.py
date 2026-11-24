"""Images or files sent without text get a default prompt in the chat's language."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from app.images import CAPTIONS, caption_for, is_default_caption

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "ai_workspace"
KEYS = ("attach_prompt_image", "attach_prompt_images", "attach_prompt_file", "attach_prompt_files", "attach_prompt_mixed")


def _integration_images():
    spec = importlib.util.spec_from_file_location("ai_workspace_images", COMPONENT / "images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _i18n_tables() -> dict[str, dict[str, str]]:
    src = (COMPONENT / "www" / "i18n.js").read_text(encoding="utf-8")
    tables: dict[str, dict[str, str]] = {}
    lang = ""
    for line in src.splitlines():
        head = re.match(r'^  (?:"([\w-]+)"|(\w+)): \{$', line)
        if head:
            lang = head.group(1) or head.group(2)
            tables[lang] = {}
            continue
        item = re.match(r"^    (attach_prompt_\w+): (\".*\"),$", line)
        if lang and item:
            tables[lang][item.group(1)] = json.loads(item.group(2))
    return tables


def test_every_shipped_language_has_the_prompts() -> None:
    shipped = sorted(p.stem for p in (COMPONENT / "translations").glob("*.json"))
    assert sorted(CAPTIONS) == shipped
    for lang, row in CAPTIONS.items():
        assert len(row) == 5, lang
        assert "{count}" in row[1] and "{count}" in row[3], lang
        if lang != "en":
            assert row != CAPTIONS["en"], lang


def test_frontend_and_backend_use_the_same_words() -> None:
    tables = _i18n_tables()
    assert sorted(tables) == sorted(CAPTIONS)
    for lang, row in CAPTIONS.items():
        assert tuple(tables[lang][key] for key in KEYS) == row, lang


def test_integration_and_runtime_copies_match() -> None:
    assert _integration_images().CAPTIONS == CAPTIONS


def test_caption_follows_the_language() -> None:
    assert caption_for("", 1, 0, "de") == "Sieh dir dieses Bild an."
    assert caption_for("", 3, 0, "de-CH") == "Sieh dir diese 3 Bilder an."
    assert caption_for("", 0, 1, "de") == "Sieh dir diese Datei an."
    assert caption_for("", 1, 1, "fr") == "Regarde ces pièces jointes."
    assert caption_for("", 1, 0, "zh-TW") == "請看這張圖片。"
    assert caption_for("", 1, 0, "zh") == "请看这张图片。"
    assert caption_for("", 1, 0, "xx") == "Look at this image."
    assert caption_for("", 1, 0) == "Look at this image."
    assert caption_for("Was ist das?", 1, 0, "de") == "Was ist das?"
    assert _integration_images().caption_for("", 2, 0, "pl") == "Spójrz na te obrazy (2)."


def test_default_captions_are_recognized() -> None:
    assert is_default_caption("Look at these 12 images.")
    assert is_default_caption("Sieh dir diese 2 Dateien an.")
    assert is_default_caption(" 请看这些附件。 ")
    assert not is_default_caption("Sieh dir dieses Bild an und sag mir, was kaputt ist.")
    assert not is_default_caption("")


def test_language_rule_covers_the_default_prompt() -> None:
    src = (COMPONENT / "const.py").read_text(encoding="utf-8")
    assert "ATTACHMENT_LANGUAGE_NOTE" in src
    assert 'does not set the language; then answer in {name}.' in src
    assert "{ATTACHMENT_LANGUAGE_NOTE.format(name=name)}" in src


def test_both_endpoints_pass_the_language() -> None:
    http = (COMPONENT / "http.py").read_text(encoding="utf-8")
    assert re.search(r'caption_for\(\s*str\(body\.get\("message"\) or ""\), len\(images\), len\(files\), str\(body\.get\("language"\) or ""\)', http)
    main = (ROOT / "ai_workspace" / "app" / "main.py").read_text(encoding="utf-8")
    assert "caption_for(body.message, len(images), len(files), body.language)" in main
