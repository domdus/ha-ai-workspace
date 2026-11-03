"""The guide's key reaches the agent's writes, and writes stop re-attaching the guide."""

import asyncio
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from custom_components.ai_workspace import bps_key
from custom_components.ai_workspace.bps_key import current_key, note_guide, prepare_write
from custom_components.ai_workspace.discovery import runtime_notice

_ROOT = Path(__file__).resolve().parents[1]
_KEY = "I-HAVE-READ-THE-BEST-PRACTICES-GUIDE-ffe08dca"
_OLD = "I-HAVE-READ-THE-BEST-PRACTICES-GUIDE-0badc0de"
_GUIDE = json.dumps({"success": True, "content": f"Acknowledgment key: {_KEY} — strict mode is ON.\n\n---\n" + "x" * 30000})


def setup_function() -> None:
    bps_key.forget()


def test_both_copies_are_the_same() -> None:
    home = (_ROOT / "custom_components/ai_workspace/bps_key.py").read_text()
    assert home == (_ROOT / "ai_workspace/app/bps_key.py").read_text()


def test_runtime_version_matches_the_release() -> None:
    from app.version import RUNTIME_VERSION

    config = re.search(r'^version: "([^"]+)"', (_ROOT / "ai_workspace/config.yaml").read_text(), re.M).group(1)
    manifest = json.loads((_ROOT / "custom_components/ai_workspace/manifest.json").read_text())["version"]
    assert RUNTIME_VERSION == config == manifest


def test_nothing_changes_before_the_guide_was_read() -> None:
    args = {"config": {"alias": "Hall"}}
    assert prepare_write("ha_config_set_automation", args) is args


def test_writes_get_the_key_and_skip_the_inline_guide() -> None:
    assert note_guide("ha_get_skill_guide", _GUIDE, now=100.0) == _KEY
    for given in ({}, {"BestPracticeKey": "wrong"}, {"BestPracticeKey": _KEY[:-2]}):
        out = prepare_write("ha_config_set_dashboard", {"url_path": "x", **given}, now=200.0)
        assert out["BestPracticeKey"] == _KEY
        assert out["MandatoryBPS"] is False
    kept = prepare_write("mcp_ha_config_set_script", {"MandatoryBPS": True}, now=200.0)
    assert kept["MandatoryBPS"] is True and kept["BestPracticeKey"] == _KEY
    assert prepare_write("ha_config_get_automation", {"identifier": "a"}, now=200.0) == {"identifier": "a"}
    assert note_guide("ha_search_entities", f"text with {_OLD}") == ""


def test_newest_key_wins_and_old_keys_expire() -> None:
    note_guide("ha_get_skill_guide", f"key {_OLD}", now=0.0)
    note_guide("ha_get_skill_guide", _GUIDE, now=3000.0)
    assert prepare_write("ha_config_set_scene", {"BestPracticeKey": _OLD}, now=3400.0)["BestPracticeKey"] == _KEY
    assert current_key(now=3000.0 + 56 * 60) == ""
    args = {"BestPracticeKey": _KEY}
    assert prepare_write("ha_config_set_scene", args, now=3000.0 + 56 * 60) is args


def test_cloud_agent_relays_the_key() -> None:
    from custom_components.ai_workspace.api_provider import ApiProvider
    from test_force_tools import _settings

    sent: list[tuple[str, dict]] = []

    class Bundle:
        def original_name(self, name):
            return name

        async def call_tool(self, name, args):
            sent.append((name, args))
            if name == "ha_get_skill_guide":
                return {"content": [{"type": "text", "text": _GUIDE}]}
            return {"content": [{"type": "text", "text": "ok"}]}

    provider = ApiProvider(None, _settings("openai"), None)

    async def turn():
        await provider._invoke_tool(Bundle(), "ha_get_skill_guide", {}, None)
        await provider._invoke_tool(Bundle(), "ha_config_set_automation", {"config": {"alias": "Hall light"}}, None)

    asyncio.run(turn())
    assert sent[1][1]["BestPracticeKey"] == _KEY
    assert sent[1][1]["MandatoryBPS"] is False


def test_runtime_proxy_relays_the_key(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app import bps_key as runtime_bps
    from app.main import create_app
    from app.mcp_proxy import McpProxy
    from app.settings import Settings

    runtime_bps.forget()
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            received.append(body)
            name = body["params"]["name"]
            text = _GUIDE if name == "ha_get_skill_guide" else "ok"
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": text}]}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            del fmt, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
            wrapped = registry.wrap({"mcp": {"type": "http", "url": f"http://127.0.0.1:{server.server_address[1]}/mcp"}}, "http://test")
            url = wrapped["mcp"]["url"].removeprefix("http://test")
            guide = client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ha_get_skill_guide", "arguments": {}}})
            assert _KEY in guide.text
            write = {"name": "ha_config_set_dashboard", "arguments": {"url_path": "x", "config": {}}}
            assert client.post(url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": write}).status_code == 200
        assert received[1]["params"]["arguments"]["BestPracticeKey"] == _KEY
        assert received[1]["params"]["arguments"]["MandatoryBPS"] is False
        assert received[1]["id"] == 2
    finally:
        server.shutdown()


def test_outdated_runtime_gets_a_notice() -> None:
    assert runtime_notice("1.4.2", "1.4.3b1") is not None
    assert "older than 1.4.3" in runtime_notice("", "1.4.3b1")
    assert runtime_notice("1.4.3b1", "1.4.3b1") is None
    assert runtime_notice("1.4.3", "1.4.3b1") is None
    assert runtime_notice("1.4.3b1", "1.4.3") is not None
    assert runtime_notice("1.5.0", "1.4.3") is None
