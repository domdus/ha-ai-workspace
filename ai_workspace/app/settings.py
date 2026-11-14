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


def _listen_host() -> str:
    return (os.environ.get("HOST") or "0.0.0.0").strip() or "0.0.0.0"


def _default_hass_url(options: dict | None = None) -> str:
    for key in ("HASS_URL", "HOMEASSISTANT_URL"):
        value = os.environ.get(key, "").strip()
        if value:
            return value.rstrip("/")
    saved = str((options or {}).get("hass_url") or "").strip()
    if saved:
        return saved.rstrip("/")
    # Host-network runtime (HOST 127.0.0.1) shares the machine with Core.
    # Bridge / add-on containers reach Core as hostname homeassistant.
    if _listen_host() in {"127.0.0.1", "localhost", "::1"}:
        return "http://127.0.0.1:8123"
    return "http://homeassistant:8123"


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


# How Codex chats are confined: "container" (the container is the sandbox, Codex runs with full access
# inside it) or "codex" (Codex's own bubblewrap sandbox; needs user namespaces in the container).
CODEX_SANDBOXES = ("container", "codex")


def _codex_sandbox(raw: str) -> str:
    value = (raw or "").strip().lower()
    return value if value in CODEX_SANDBOXES else "container"


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
    claude_oauth_token: str = ""
    anthropic_api_key: str = ""
    claude_model: str = ""
    runtime_token: str = ""
    hass_url: str = ""
    shorten_mcp_results: bool = True
    change_history: bool = True
    # OpenAI Codex (openai-codex SDK): "Sign in with ChatGPT" (auth.json in CODEX_HOME) first, then an
    # OpenAI API key. Empty model: Codex's own default for the account.
    openai_api_key: str = ""
    codex_model: str = ""
    codex_home_dir: Path | None = None
    # An auth.json to seed CODEX_HOME with once (path to a mounted file, or the JSON itself).
    codex_auth_json: str = ""
    codex_sandbox: str = "container"
    # Extra `--config key=value` lines for Codex (TOML values), for example a custom model provider.
    codex_config: tuple[str, ...] = ()

    @property
    def codex_home(self) -> Path:
        """CODEX_HOME: auth.json, threads for resume and Codex's own state. In the persistent data folder."""
        return self.codex_home_dir or self.data_dir / "codex"

    @property
    def codex_auth_path(self) -> Path:
        return self.codex_home / "auth.json"

    @property
    def claude_token_path(self) -> Path:
        """Claude Plan token from "Sign in with Claude" (owner-only file in the persistent data folder)."""
        return self.data_dir / "auth" / "claude-oauth-token"

    def open_without_token(self) -> bool:
        """Only a runtime bound to loopback may answer without the shared token."""
        return self.host in {"127.0.0.1", "localhost", "::1"}

    def ensure_dirs(self) -> None:
        from app.prompt import CURSOR_IDENTITY, CURSOR_RULE

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        agents = self.workspace_dir / "AGENTS.md"
        if not agents.exists():
            agents.write_text(CURSOR_IDENTITY, encoding="utf-8")
        rules = self.workspace_dir / ".cursor" / "rules"
        rule = rules / "home-assistant.mdc"
        if not rule.exists():
            rules.mkdir(parents=True, exist_ok=True)
            rule.write_text(CURSOR_RULE, encoding="utf-8")

    @classmethod
    def from_env(cls) -> Settings:
        options = _read_options()
        data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
        workspace_dir = Path(os.environ.get("WORKSPACE_DIR", str(data_dir / "workspace"))).resolve()
        state_dir = Path(os.environ.get("CURSOR_STATE_DIR", str(data_dir / "cursor-state"))).resolve()
        key = os.environ.get("CURSOR_API_KEY", "").strip() or str(options.get("cursor_api_key") or "").strip()
        model = os.environ.get("CURSOR_MODEL", "").strip() or str(options.get("model") or "").strip() or "composer-2.5"
        claude_oauth = (
            os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
            or str(options.get("claude_oauth_token") or "").strip()
        )
        anthropic_key = (
            os.environ.get("ANTHROPIC_API_KEY", "").strip()
            or str(options.get("anthropic_api_key") or "").strip()
        )
        claude_model = (
            os.environ.get("CLAUDE_MODEL", "").strip()
            or str(options.get("claude_model") or "").strip()
        )
        openai_key = (
            os.environ.get("OPENAI_API_KEY", "").strip()
            or os.environ.get("CODEX_API_KEY", "").strip()
            or str(options.get("openai_api_key") or "").strip()
        )
        codex_model = os.environ.get("CODEX_MODEL", "").strip() or str(options.get("codex_model") or "").strip()
        codex_home = os.environ.get("CODEX_HOME", "").strip()
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
            claude_oauth_token=claude_oauth,
            anthropic_api_key=anthropic_key,
            claude_model=claude_model,
            auth_mode=auth_mode,
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8090")),
            runtime_token=(
                os.environ.get("RUNTIME_TOKEN", "").strip() or str(options.get("runtime_token") or "").strip()
            ),
            hass_url=_default_hass_url(options),
            openai_api_key=openai_key,
            codex_model=codex_model,
            codex_home_dir=Path(codex_home).resolve() if codex_home else None,
            codex_auth_json=os.environ.get("CODEX_AUTH_JSON", "").strip(),
            codex_sandbox=_codex_sandbox(os.environ.get("CODEX_SANDBOX", "")),
            codex_config=tuple(
                line.strip() for line in os.environ.get("CODEX_CONFIG", "").splitlines() if "=" in line and line.strip()
            ),
        )
