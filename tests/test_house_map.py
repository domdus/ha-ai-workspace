import importlib.util
import sys
from pathlib import Path


def _store_mod():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "store.py"
    name = "ai_workspace_store"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_house_map_search(tmp_path: Path) -> None:
    Store = _store_mod().Store
    store = Store(tmp_path / "map.sqlite")
    store.replace_house_map(
        [
            ("entity", "light.living_room", "Living room lights (Living room)", "living_room", "light", ""),
            ("area", "living_room", "Living room", "living_room", "", ""),
            ("automation", "automation.bedtime", "Bedtime", "", "automation", '{"config_id":"bedtime"}'),
            ("dashboard", "overview", "Overview", "", "lovelace", '{"path":"/overview"}'),
        ]
    )
    lights = store.search_house_map("living lights")
    assert any(item["id"] == "light.living_room" for item in lights)
    areas = store.search_house_map("living", kind="area")
    assert areas and areas[0]["kind"] == "area"
    autos = store.search_house_map("bedtime", kind="automation")
    assert autos and autos[0].get("config_id") == "bedtime"
    store.close()
