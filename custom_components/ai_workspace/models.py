from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .store import Session


# sha256 of earlier workspace_seed/AGENTS.md versions. A copy that still matches one was never edited,
# so it gets the current seed. An edited AGENTS.md is left alone.
_OLD_SEED_SHA256 = frozenset(
    {
        "0c90ff77d90b754e29f68e36df7cf0fe310588822542e68ca3d6b3167127f0f6",
        "170f2a05d99019e8283fc0d05fe7320f1a5a7db267587f10939cb6c35708d71c",
        "2ea00c0d45fbe89987f40452b53cc99634730d980a61766e990b795a1bc03d9c",
        "498270a578d59f1839ef23f7ba139ac8ee152cbdc27ac11d376f3f65dccc6bd9",
        "4de7eaba3b359fd117e12f71bb5268175eb064ed68cbf6cd893fb33b5faf4f8d",
        "68f521b69ee7d8fb6595a5eeb336238c51c74a6a84ba4305a7feea9f5a4d9c58",
        "6f00493d83e8e048bdbaa70cee5e0a7aed5d7f1371335b1d48fd065a078ac5ce",
        "7859da77d476b6494e449790c3017dab8c8ca5b3bcb90808a30e30afd80508ac",
        "d9c94b7bce1162344f7fdf1556cfa3d42c9f7ed290640c4a408aebe39819e3e7",
        "deeae0addb9584c99325ed1a1ca8d6a1d4d6bfddef9bcb613b90ac9a6200f045",
        "e6a53e651fe21eba9b3454c716475bf75ae2d113bb3d8605e0124c6458670751",
    }
)


def _unedited_seed(target: Path) -> bool:
    if not target.exists():
        return True
    try:
        data = target.read_bytes()
    except OSError:
        return False
    return hashlib.sha256(data).hexdigest() in _OLD_SEED_SHA256


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    available: bool
    reason: str | None = None
    # Usable, but something needs the user's attention (an outdated runtime).
    notice: str | None = None
    notice_key: str | None = None
    notice_params: dict[str, str] | None = None
    title: str = ""
    model: str = ""
    provider: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "available": self.available,
            "reason": self.reason,
            "notice": self.notice,
            "notice_key": self.notice_key,
            "notice_params": self.notice_params,
            "title": self.title or self.label,
            "model": self.model,
            "provider": self.provider,
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
    notes: bool = False
    notes_text: str = ""
    shorten_mcp_results: bool = True
    change_history: bool = True
    change_history_ttl_days: int = 7
    approval_timeout_minutes: int = 10
    track_usage: bool = True
    show_chat_usage: bool = True
    ha_usage_sensors: bool = False
    ui_theme: str = "standard"
    cross_chat: bool = False
    default_agent: str = ""
    model_switcher: bool = False
    fallback_enabled: bool = False
    fallback_agents: tuple[str, ...] = ()
    fallback_return: str = "new_message"
    token_mode: str = "off"
    prompt_cache: bool = True
    cache_1h: bool = False
    context_window: int = 0
    tools_on_demand: bool = True
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
    allow_internet: bool = False

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        seed = Path(__file__).resolve().parent / "workspace_seed" / "AGENTS.md"
        target = self.workspace_dir / "AGENTS.md"
        if seed.is_file() and _unedited_seed(target):
            target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
