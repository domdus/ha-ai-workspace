import json
from pathlib import Path

from custom_components.ai_workspace.const import (
    API_COMPATIBLE,
    API_KEY_URLS,
    API_OLLAMA,
    API_PROVIDERS,
    MODE_CURSOR,
    api_key_url,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "custom_components" / "ai_workspace"
_NO_KEY_PAGE = {API_OLLAMA, API_COMPATIBLE}
_LINK_FIELDS = (
    ("provider_cursor", "cursor_api_key"),
    ("provider_cloud", "api_key"),
    ("provider_azure", "api_key"),
)


def test_cloud_providers_have_key_pages():
    for kind in API_PROVIDERS:
        url = api_key_url(kind)
        if kind in _NO_KEY_PAGE:
            assert url == ""
        else:
            assert url.startswith("https://"), kind
    assert api_key_url(MODE_CURSOR).startswith("https://")
    assert set(API_KEY_URLS) == (set(API_PROVIDERS) | {MODE_CURSOR}) - _NO_KEY_PAGE


def test_agent_form_strings_include_key_link():
    files = [BASE / "strings.json", *sorted((BASE / "translations").glob("*.json"))]
    for path in files:
        steps = json.loads(path.read_text(encoding="utf-8"))["config_subentries"]["agent"]["step"]
        for step, field in _LINK_FIELDS:
            text = steps[step]["data_description"][field]
            assert "{api_key_url}" in text, f"{path.name} {step}.{field}"
            assert "]({api_key_url})" in text, f"{path.name} {step}.{field}"


def test_hacs_uses_git_archive_and_has_brand_icon():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert "zip_release" not in hacs
    assert "filename" not in hacs
    icon = BASE / "brand" / "icon.png"
    assert icon.is_file()
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
