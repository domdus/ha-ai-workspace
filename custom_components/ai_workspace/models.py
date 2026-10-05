from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .store import Session


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    available: bool
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "available": self.available,
            "reason": self.reason,
        }


class ChatProvider(Protocol):
    info: ProviderInfo

    def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
        access_token: str | None = None,
    ): ...


@dataclass
class Settings:
    data_dir: Path
    workspace_dir: Path
    state_dir: Path
    cursor_api_key: str
    model: str
    mcp_servers: dict[str, dict[str, Any]]
    enable_overlay: bool = True
    enable_sidebar: bool = True
    mode: str = "cursor"
    api_provider: str = "openai"
    api_key: str = ""
    api_base: str = ""
    system_prompt: str = ""
    mcp_kind: str = "ha_mcp"
    mcp_token: str = ""

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        seed = Path(__file__).resolve().parent / "workspace_seed" / "AGENTS.md"
        target = self.workspace_dir / "AGENTS.md"
        if seed.is_file() and not target.exists():
            target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
