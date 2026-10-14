import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.mcp_fit import FitRegistry, parse_tool_call, tool_response_ok
from app.settings import Settings
from app.tool_result import PASS, compact_mcp_response, fit_tool_result


def _component():
    path = Path(__file__).resolve().parents[1] / "custom_components" / "ai_workspace" / "tool_result.py"
    spec = importlib.util.spec_from_file_location("ai_workspace_tool_result", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_parse_tool_call_reads_only_tool_invocations() -> None:
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ha_config_set_automation","arguments":{"identifier":"a"}}}'
    assert parse_tool_call(body) == ("ha_config_set_automation", {"identifier": "a"})
    assert parse_tool_call(
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ha_config_set_automation","arguments":"{\\"identifier\\":\\"a\\"}"}}'
    ) == ("ha_config_set_automation", {"identifier": "a"})
    assert parse_tool_call(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}') is None
    assert tool_response_ok(200, b'{"result":{"isError": false}}') is True
    assert tool_response_ok(200, b'{"result":{"isError": true}}') is False
    assert tool_response_ok(500, b"{}") is False
    described = json.dumps(
        {
            "result": {
                "content": [{"type": "text", "text": 'description example "isError": true'}],
                "isError": False,
            }
        }
    ).encode()
    assert tool_response_ok(200, described) is True
    transform = json.dumps(
        {
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "success": True,
                                "action": "python_transform",
                                "skill_content": 'docs mention "isError": true',
                            }
                        ),
                    }
                ]
            }
        }
    ).encode()
    assert tool_response_ok(200, transform) is True


def test_fit_secret_stays_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "mcp-fit-secret"
    first = FitRegistry(path).secret
    second = FitRegistry(path).secret
    assert first == second
    assert path.read_text(encoding="utf-8").strip() == first


def test_runtime_and_integration_fitters_match() -> None:
    root = Path(__file__).resolve().parents[1]
    integration = (root / "custom_components" / "ai_workspace" / "tool_result.py").read_text(encoding="utf-8")
    runtime = (root / "ai_workspace" / "app" / "tool_result.py").read_text(encoding="utf-8")
    assert integration == runtime


def test_small_json_is_unchanged() -> None:
    fit = _component().fit_tool_result
    raw = json.dumps({"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 40}})
    assert fit(raw) == raw
    parsed = json.loads(fit(raw))
    assert parsed["attributes"]["brightness"] == 40


def test_house_listing_becomes_a_complete_area_map() -> None:
    fit = _component().fit_tool_result
    entities = []
    for index in range(500):
        area = "Kitchen" if index % 2 == 0 else "Bedroom"
        entities.append(
            {
                "entity_id": f"light.room_{index}",
                "state": "on",
                "friendly_name": f"Room light {index} with a long name",
                "area_name": area,
                "attributes": {"noise": "x" * 200},
            }
        )
    raw = json.dumps({"entities": entities})
    assert len(raw) > PASS
    body = json.loads(fit(raw))
    areas = body["entities"]["areas"]
    assert set(areas) == {"Kitchen", "Bedroom"}
    listed = [entity for ids in areas.values() for entity in ids]
    assert set(listed) == {f"light.room_{index}" for index in range(500)}
    assert len(listed) == 500
    assert "noise" not in fit(raw)
    assert body["entities"]["note"]


def test_short_entity_list_keeps_state_and_drops_attributes() -> None:
    fit = _component().fit_tool_result
    entities = [
        {
            "entity_id": f"sensor.probe_{index}",
            "state": str(index),
            "area_name": "Balcony",
            "attributes": {"history": "y" * 800},
        }
        for index in range(10)
    ]
    raw = json.dumps(entities)
    assert len(raw) > PASS
    body = json.loads(fit(raw))
    assert isinstance(body, list)
    assert body[0]["entity_id"] == "sensor.probe_0"
    assert body[0]["state"] == "0"
    assert "attributes" not in body[0]
    assert "history" not in fit(raw)


def test_long_json_list_omits_whole_items() -> None:
    fit = _component().fit_tool_result
    items = [{"id": f"automation-{index}", "alias": "water " * 40, "config": "z" * 2000} for index in range(80)]
    text = fit(json.dumps(items))
    body = json.loads(text)
    assert isinstance(body, list)
    assert body[-1]["omitted"] > 0
    assert all(item.get("config") != "z" * 2000 for item in body)
    assert "z" * 50 not in text


def test_mcp_envelope_text_stays_json() -> None:
    fit = _component().fit_tool_result
    entities = [
            {
                "entity_id": f"switch.lamp_{index}",
                "state": "off",
                "friendly_name": f"Hall lamp {index} with a long name",
                "area": "Hall",
                "attributes": {"blob": "q" * 400},
            }
            for index in range(500)
        ]
    envelope = {"content": [{"type": "text", "text": json.dumps(entities)}], "isError": False}
    body = json.loads(fit(envelope))
    inner = json.loads(body["content"][0]["text"])
    assert "Hall" in inner["areas"]
    assert inner["areas"]["Hall"][0] == "switch.lamp_0"
    assert body["isError"] is False


def test_tools_call_is_compacted_and_other_methods_are_not() -> None:
    entities = [
        {"entity_id": f"light.n_{index}", "friendly_name": f"Light {index} with a long name", "attributes": {"blob": "m" * 400}}
        for index in range(500)
    ]
    result = {"content": [{"type": "text", "text": json.dumps(entities)}]}
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
    call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}).encode()
    listed = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    compact = json.loads(compact_mcp_response(call, response, "application/json"))
    inner = json.loads(compact["result"]["content"][0]["text"])
    assert "areas" in inner
    untouched = compact_mcp_response(listed, response, "application/json")
    assert untouched == response


def test_proxy_returns_a_fitted_tool_result(tmp_path: Path) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    entities = [
            {
                "entity_id": f"light.n_{index}",
                "area_name": "Kitchen",
                "friendly_name": f"Light {index} with a long name",
                "attributes": {"blob": "m" * 400},
            }
            for index in range(500)
        ]
    payload = json.dumps({"jsonrpc": "2.0", "id": 4, "result": {"content": [{"type": "text", "text": json.dumps(entities)}]}}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "sess-1")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            del fmt, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        app = create_app(
            Settings(
                data_dir=tmp_path,
                workspace_dir=tmp_path / "workspace",
                state_dir=tmp_path / "state",
                mcp_config_path=tmp_path / "mcp.json",
                cursor_api_key="",
                model="composer-2.5",
                auth_mode="dev",
                host="127.0.0.1",
                port=8090,
            ),
            providers={},
        )
        with TestClient(app) as client:
            registry = FitRegistry()
            client.app.state.runtime = type("Runtime", (), {"fit": registry})()
            wrapped = registry.wrap(
                {"mcp": {"type": "http", "url": f"http://127.0.0.1:{server.server_address[1]}/mcp", "headers": {"Authorization": "Bearer secret"}}},
                "http://test",
            )
            url = wrapped["mcp"]["url"].removeprefix("http://test")
            assert "Bearer" not in url
            response = client.post(url, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}})
            assert response.status_code == 200
            assert response.headers["mcp-session-id"] == "sess-1"
            body = response.json()
            inner = json.loads(body["result"]["content"][0]["text"])
            assert inner["areas"]["Kitchen"][0] == "light.n_0"
            assert "blob" not in response.text
    finally:
        server.shutdown()
