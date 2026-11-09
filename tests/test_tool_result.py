import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.mcp_proxy import McpProxy, parse_tool_call, proxy_secret_path, tool_response_ok
from app.settings import Settings
from app.tool_result import AREA_MAP, LIMIT, OFF, PASS, TRUNCATED, UNCHANGED, shorten_mcp_response, shorten_tool_result


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
    assert parse_tool_call(
        b'[{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ha_config_set_dashboard","arguments":{"url_path":"home-weather","patch":[{"op":"add","path":"/views/-","value":{}}]}}}]'
    ) == (
        "ha_config_set_dashboard",
        {"url_path": "home-weather", "patch": [{"op": "add", "path": "/views/-", "value": {}}]},
    )
    assert parse_tool_call(
        b'data: {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ha_config_set_dashboard","arguments":{"url_path":null,"python_transform":"config[\'views\'].append({})"}}}\n\n'
    ) == (
        "ha_config_set_dashboard",
        {"url_path": None, "python_transform": "config['views'].append({})"},
    )
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


def test_proxy_secret_stays_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "mcp-proxy-secret"
    first = McpProxy(path).secret
    second = McpProxy(path).secret
    assert first == second
    assert path.read_text(encoding="utf-8").strip() == first


def test_proxy_secret_keeps_legacy_file(tmp_path: Path) -> None:
    legacy = tmp_path / "mcp-fit-secret"
    legacy.write_text("legacy-secret\n", encoding="utf-8")
    assert proxy_secret_path(tmp_path) == legacy
    assert McpProxy(proxy_secret_path(tmp_path)).secret == "legacy-secret"


def test_runtime_and_integration_fitters_match() -> None:
    root = Path(__file__).resolve().parents[1]
    integration = (root / "custom_components" / "ai_workspace" / "tool_result.py").read_text(encoding="utf-8")
    runtime = (root / "ai_workspace" / "app" / "tool_result.py").read_text(encoding="utf-8")
    assert integration == runtime


def test_small_json_is_unchanged() -> None:
    shorten = _component().shorten_tool_result
    raw = json.dumps({"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 40}})
    text, kind = shorten(raw)
    assert kind == UNCHANGED
    assert text == raw
    parsed = json.loads(text)
    assert parsed["attributes"]["brightness"] == 40


def test_shorten_can_be_turned_off() -> None:
    shorten = _component().shorten_tool_result
    entities = [{"entity_id": f"light.n_{i}", "state": "on", "attributes": {"blob": "m" * 400}} for i in range(500)]
    raw = json.dumps(entities)
    text, kind = shorten(raw, enabled=False)
    assert kind == OFF
    assert text == raw


def test_house_listing_becomes_a_complete_area_map() -> None:
    fit = lambda raw: _component().shorten_tool_result(raw)[0]
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
    text, kind = _component().shorten_tool_result(raw)
    assert kind == AREA_MAP
    body = json.loads(text)
    areas = body["entities"]["areas"]
    assert set(areas) == {"Kitchen", "Bedroom"}
    listed = [entity for ids in areas.values() for entity in ids]
    assert set(listed) == {f"light.room_{index}" for index in range(500)}
    assert len(listed) == 500
    assert "noise" not in fit(raw)
    assert body["entities"]["note"]


def test_short_entity_list_keeps_state_and_drops_attributes() -> None:
    fit = lambda raw: _component().shorten_tool_result(raw)[0]
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


def test_skill_guide_arrives_whole_with_its_key() -> None:
    """HA-MCP puts the BestPracticeKey in the first line; writes fail without it."""
    guide = "Acknowledgment: dashboards-ack-7f3a\n" + "Best practice line.\n" * 1200
    envelope = {
        "content": [{"type": "text", "text": json.dumps({"file": "SKILL.md", "content": guide})}],
        "structuredContent": {"file": "SKILL.md", "content": guide},
        "isError": False,
    }
    text, kind = shorten_tool_result(envelope)
    assert kind == UNCHANGED
    assert json.loads(text) == envelope


def test_dashboard_config_is_never_rewritten() -> None:
    cards = [
        {"type": "custom:gauge", "entity": f"sensor.tank_{i}", "name": f"Tank {i}", "state": "on", "tap_action": {"action": "more-info"}}
        for i in range(120)
    ]
    long_markdown = "Template {{ states('sensor.tank_1') }} " * 300
    config = {"views": [{"title": "Technik", "cards": cards + [{"type": "markdown", "content": long_markdown}]}]}
    raw = json.dumps(config)
    assert len(raw) > PASS
    text, kind = shorten_tool_result(raw)
    assert kind == UNCHANGED
    assert text == raw


def test_long_automation_list_keeps_every_field() -> None:
    items = [{"id": f"automation-{index}", "alias": "water " * 40, "config": "z" * 2000} for index in range(30)]
    raw = json.dumps(items)
    text, kind = shorten_tool_result(raw)
    assert kind == UNCHANGED
    assert text == raw


def test_entity_rows_with_config_are_not_a_listing() -> None:
    items = [{"entity_id": f"light.n_{i}", "brightness": 40, "blob": "x" * 200} for i in range(100)]
    raw = json.dumps(items)
    assert shorten_tool_result(raw) == (raw, UNCHANGED)


def test_listing_keeps_the_id_for_edit_links() -> None:
    items = [
        {"entity_id": f"automation.a_{i}", "state": "on", "attributes": {"id": f"a{i}", "blob": "x" * 200}}
        for i in range(40)
    ]
    body = json.loads(shorten_tool_result(json.dumps(items))[0])
    assert body[3] == {"entity_id": "automation.a_3", "state": "on", "id": "a3"}


def test_huge_result_keeps_its_beginning_and_says_it_is_cut() -> None:
    raw = "Key on the first line\n" + "line of text\n" * 20000
    text, kind = shorten_tool_result(raw)
    assert kind == TRUNCATED
    assert text.startswith("Key on the first line")
    assert "do not write it back" in text
    assert len(text) < LIMIT + 400  # the beginning plus the note
    guide = "Key on the first line\n" + "line of text\n" * 20000
    envelope = {"content": [{"type": "text", "text": guide}], "structuredContent": {"content": guide}, "isError": False}
    body = json.loads(shorten_tool_result(envelope)[0])
    assert body["content"][0]["text"].startswith("Key on the first line")
    assert "do not write it back" in body["content"][0]["text"]
    assert "structuredContent" not in body and body["isError"] is False


def test_mcp_envelope_text_stays_json() -> None:
    fit = lambda raw: _component().shorten_tool_result(raw)[0]
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
        {"entity_id": f"light.n_{index}", "state": "on", "friendly_name": f"Light {index} with a long name", "attributes": {"blob": "m" * 400}}
        for index in range(500)
    ]
    result = {"content": [{"type": "text", "text": json.dumps(entities)}]}
    response = json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()
    call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}).encode()
    listed = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    compact, kind = shorten_mcp_response(call, response, "application/json")
    compact = json.loads(compact)
    inner = json.loads(compact["result"]["content"][0]["text"])
    assert "areas" in inner
    assert kind == AREA_MAP
    untouched, listed_kind = shorten_mcp_response(listed, response, "application/json")
    assert untouched == response
    assert listed_kind == UNCHANGED


def test_stream_with_nothing_to_shorten_stays_byte_identical() -> None:
    guide = "Ack key\n" + "Grüße line.\n" * 1000
    result = {"content": [{"type": "text", "text": json.dumps({"content": guide})}]}
    body = f'event: message\ndata:{json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})}\n\n'.encode()
    call = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call"}).encode()
    assert shorten_mcp_response(call, body, "text/event-stream") == (body, UNCHANGED)


def test_proxy_returns_a_fitted_tool_result(tmp_path: Path) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    entities = [
            {
                "entity_id": f"light.n_{index}",
                "state": "on",
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
        with TestClient(app, base_url="http://127.0.0.1") as client:
            registry = McpProxy()
            client.app.state.runtime = type("Runtime", (), {"proxy": registry})()
            wrapped = registry.wrap(
                {"mcp": {"type": "http", "url": f"http://127.0.0.1:{server.server_address[1]}/mcp", "headers": {"Authorization": "Bearer secret"}}},
                "http://test",
            )
            url = wrapped["mcp"]["url"].removeprefix("http://test")
            assert url.startswith("/api/mcp-proxy/")
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
