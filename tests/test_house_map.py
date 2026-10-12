import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str):
    path = ROOT / "custom_components" / "ai_workspace" / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _store_mod():
    return _load("store.py", "ai_workspace_store")


def _catalog():
    return _load("catalog_index.py", "ai_workspace_catalog_index")


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


def test_catalog_detail_compact_strips_wiring() -> None:
    catalog = _catalog()
    row = {
        "kind": "automation",
        "id": "automation.balkon",
        "name": "Bewässerung - Balkon",
        "config_id": "1778612154557",
        "trigger_summary": "time 08:00",
        "acts_on": ["switch.water_pump_balcony"],
        "depends_on": ["sensor.radar_max_rain_last_24h"],
        "related_config_ids": ["1782683008999"],
    }
    compact = catalog.apply_catalog_detail([row], "compact")
    assert compact == [
        {
            "kind": "automation",
            "id": "automation.balkon",
            "name": "Bewässerung - Balkon",
            "config_id": "1778612154557",
        }
    ]
    wiring = catalog.apply_catalog_detail([row], "wiring")
    assert wiring[0]["acts_on"] == ["switch.water_pump_balcony"]
    assert wiring[0]["trigger_summary"] == "time 08:00"


def test_catalog_instructions_are_not_list_first() -> None:
    text = (ROOT / "custom_components" / "ai_workspace" / "house_map.py").read_text()
    assert "call search_catalog first" not in text
    assert "For counts, lists, names, and on/off, call the Home Assistant tools" in text
    assert "Do not call" not in text
    assert "detail=wiring" in text


def test_search_matches_aliases_in_extra(tmp_path: Path) -> None:
    Store = _store_mod().Store
    store = Store(tmp_path / "map.sqlite")
    extra = json.dumps(
        {
            "config_id": "1778612154557",
            "aliases": ["balkon"],
            "trigger_summary": "time 08:00",
            "acts_on": ["switch.water_pump_balcony"],
        }
    )
    store.replace_house_map(
        [("automation", "automation.balkon", "Bewässerung - Balkon", "balcony", "automation", extra)]
    )
    hits = store.search_house_map("balkon")
    assert hits and hits[0]["config_id"] == "1778612154557"
    assert hits[0]["trigger_summary"] == "time 08:00"
    store.close()


def test_trigger_summary_and_wiring() -> None:
    catalog = _catalog()
    config = {
        "alias": "Bewässerung - Balkon",
        "trigger": [{"platform": "time", "at": "08:00:00"}],
        "condition": [
            {"condition": "numeric_state", "entity_id": "sensor.radar_max_rain_last_24h", "below": 20},
            {"condition": "state", "entity_id": "input_number.bewaesserung_reduktion_heute"},
        ],
        "action": [
            {"action": "switch.turn_on", "target": {"entity_id": "switch.water_pump_balcony"}},
        ],
    }
    assert catalog.summarize_triggers(config) == "time 08:00"
    assert "switch.water_pump_balcony" in catalog.acts_on(config)
    assert "sensor.radar_max_rain_last_24h" in catalog.depends_on(config)
    assert "input_number.bewaesserung_reduktion_heute" in catalog.depends_on(config)


def test_related_config_ids_by_actor_and_name() -> None:
    catalog = _catalog()
    related = catalog.related_config_ids(
        [
            {
                "config_id": "morning",
                "name": "Bewässerung - Balkon",
                "acts_on": ["switch.water_pump_balcony"],
            },
            {
                "config_id": "evening",
                "name": "Bewässerung - Balkon Abendcheck",
                "acts_on": ["switch.water_pump_balcony"],
            },
            {
                "config_id": "other",
                "name": "Lights off",
                "acts_on": ["light.kitchen"],
            },
        ]
    )
    assert "evening" in related["morning"]
    assert "morning" in related["evening"]
    assert "other" not in related.get("morning", [])


def test_catalog_auth_paths() -> None:
    mod = _load("mcp_config.py", "ai_workspace_mcp_config_catalog")
    servers = {
        "catalog": {"type": "http", "url": "http://homeassistant:8123/api/ai_workspace/catalog/mcp"},
        "mcp": {"type": "http", "url": "http://homeassistant:8123/api/webhook/mcp_x"},
    }
    out = mod.with_mcp_auth(servers, access_token="ha-token")
    assert out["catalog"]["headers"]["Authorization"] == "Bearer ha-token"
    assert "headers" not in out["mcp"]
    dropped = mod.with_mcp_auth(servers, access_token="")
    assert "catalog" not in dropped
