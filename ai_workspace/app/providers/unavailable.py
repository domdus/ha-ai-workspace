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
    ) -> AsyncIterator[dict]:
        del session, message, on_agent_id
        yield {"type": "error", "message": self.info.reason or "This provider is not available."}
