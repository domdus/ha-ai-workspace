from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Callable, Protocol

from app.store import Session


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
        images: list | None = None,
        mcp: dict | None = None,
        model: str | None = None,
        effort: str = "",
        api_key: str = "",
        handoff: str = "",
        question: str = "",
        prompt: str = "",
        full_tools: bool = False,
    ) -> AsyncIterator[dict]: ...
