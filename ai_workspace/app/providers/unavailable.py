from __future__ import annotations

from typing import AsyncIterator, Callable

from app.providers.base import ProviderInfo
from app.store import Session


class UnavailableProvider:
    def __init__(self, info: ProviderInfo) -> None:
        self.info = info

    async def send(
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
) -> AsyncIterator[dict]:
        del session, message, on_agent_id, images, mcp, model, effort, api_key, handoff
        yield {"type": "error", "message": self.info.reason or "This provider is not available."}
