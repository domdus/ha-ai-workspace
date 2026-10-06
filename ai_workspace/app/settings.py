from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _read_options() -> dict:
    path = Path(os.environ.get("ADDON_OPTIONS", "/data/options.json"))
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _file_servers(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    block = data.get("mcpServers", data)
    return dict(block) if isinstance(block, dict) else {}


def _option_servers(options: dict) -> dict:
    raw = options.get("mcp_config")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            block = parsed.get("mcpServers", parsed)
            if isinstance(block, dict):
                return dict(block)
    return {}


def _url_server(options: dict) -> dict:
    mcp_url = str(options.get("mcp_url") or os.environ.get("MCP_URL") or "").strip()
    mcp_token = str(options.get("mcp_token") or os.environ.get("MCP_TOKEN") or "").strip()
    if not mcp_url:
        return {}
    entry: dict = {"type": "streamable-http", "url": mcp_url}
    if mcp_token:
        entry["headers"] = {"Authorization": f"Bearer {mcp_token}"}
    return {"home-assistant": entry}


def _write_servers(path: Path, servers: dict, fallback: Path) -> Path:
    payload = json.dumps({"mcpServers": servers}, ensure_ascii=False, indent=2) + "\n"
    for target in (path, fallback):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
            return target
        except OSError:
            continue
    return path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    workspace_dir: Path
    state_dir: Path
    mcp_config_path: Path
    cursor_api_key: str
    model: str
    auth_mode: str
    host: str
    port: int

    def ensure_dirs(self) -> None:
        from app.prompt import CURSOR_IDENTITY, CURSOR_RULE

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.workspace_dir / "AGENTS.md").write_text(CURSOR_IDENTITY, encoding="utf-8")
        rules = self.workspace_dir / ".cursor" / "rules"
        rules.mkdir(parents=True, exist_ok=True)
        (rules / "home-assistant.mdc").write_text(CURSOR_RULE, encoding="utf-8")

    @classmethod
    def from_env(cls) -> Settings:
        options = _read_options()
        data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
        workspace_dir = Path(os.environ.get("WORKSPACE_DIR", str(data_dir / "workspace"))).resolve()
        state_dir = Path(os.environ.get("CURSOR_STATE_DIR", str(data_dir / "cursor-state"))).resolve()
        key = os.environ.get("CURSOR_API_KEY", "").strip() or str(options.get("cursor_api_key") or "").strip()
        model = os.environ.get("CURSOR_MODEL", "").strip() or str(options.get("model") or "").strip() or "composer-2.5"
        auth_mode = os.environ.get("AUTH_MODE", "").strip()
        if not auth_mode:
            auth_mode = "ingress" if options else "dev"
        configured = os.environ.get("MCP_CONFIG_PATH", "").strip()
        mcp_path = Path(configured).resolve() if configured else data_dir / "mcp.json"
        servers = _file_servers(mcp_path)
        for name, entry in _option_servers(options).items():
            servers.setdefault(name, entry)
        for name, entry in _url_server(options).items():
            servers[name] = entry
        if servers:
            mcp_path = _write_servers(mcp_path, servers, fallback=data_dir / "mcp.json")
        return cls(
            data_dir=data_dir,
            workspace_dir=workspace_dir,
            state_dir=state_dir,
            mcp_config_path=mcp_path,
            cursor_api_key=key,
            model=model,
            auth_mode=auth_mode,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8090")),
        )
