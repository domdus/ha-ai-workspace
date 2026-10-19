from __future__ import annotations

from dataclasses import dataclass, field
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
        frontend_origin: str | None = None,
        images: list | None = None,
    ): ...


@dataclass
class Settings:
    data_dir: Path
    workspace_dir: Path
    state_dir: Path
    cursor_api_key: str
    model: str
    mcp_servers: dict[str, dict[str, Any]]
    mcp_rows: list[dict[str, Any]] = field(default_factory=list)
    enable_overlay: bool = True
    enable_sidebar: bool = True
    enable_dictate: bool = True
    allow_users: bool = False
    house_map: bool = False
    shorten_mcp_results: bool = True
    change_history: bool = True
    track_usage: bool = True
    show_chat_usage: bool = True
    ha_usage_sensors: bool = False
    ui_theme: str = "standard"
    cross_chat: bool = False
    token_mode: str = "off"
    prompt_cache: bool = True
    check_house: bool = True
    keep_chats: int = 30
    mode: str = "cursor"
    api_provider: str = "openai"
    api_key: str = ""
    api_base: str = ""
    system_prompt: str = ""
    mcp_kind: str = "ha_mcp"
    mcp_token: str = ""
    effort: str = ""
    azure_api_version: str = "2024-10-21"
    stt_engine: str = "browser"
    tts_engine: str = "off"
    speak_replies: bool = False
    tts_natural: bool = True
    agent_id: str = ""
    agent_title: str = ""

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        seed = Path(__file__).resolve().parent / "workspace_seed" / "AGENTS.md"
        target = self.workspace_dir / "AGENTS.md"
        if seed.is_file() and not target.exists():
            target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
