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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        seed = Path(__file__).resolve().parent / "workspace_seed" / "AGENTS.md"
        target = self.workspace_dir / "AGENTS.md"
        if seed.is_file() and not target.exists():
            target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")

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
        mcp_env = os.environ.get("MCP_CONFIG_PATH", "").strip()
        if mcp_env:
            mcp_path = Path(mcp_env).resolve()
        else:
            mcp_path = data_dir / "mcp.json"
            data_dir.mkdir(parents=True, exist_ok=True)
            servers: dict = {}
            raw = options.get("mcp_config")
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict):
                    block = parsed.get("mcpServers", parsed)
                    if isinstance(block, dict):
                        servers.update(block)
            mcp_url = str(options.get("mcp_url") or os.environ.get("MCP_URL") or "").strip()
            mcp_token = str(options.get("mcp_token") or os.environ.get("MCP_TOKEN") or "").strip()
            if mcp_url:
                entry: dict = {"url": mcp_url}
                if mcp_token:
                    entry["headers"] = {"Authorization": f"Bearer {mcp_token}"}
                servers.setdefault("mcp", entry)
            mcp_path.write_text(
                json.dumps({"mcpServers": servers}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
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
