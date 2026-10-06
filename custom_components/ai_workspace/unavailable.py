from __future__ import annotations

from typing import AsyncIterator, Callable

from .models import ProviderInfo
from .store import Session


class UnavailableProvider:
    def __init__(self, info: ProviderInfo) -> None:
        self.info = info

    async def send(
        self,
        session: Session,
        message: str,
        on_agent_id: Callable[[str], None],
        access_token: str | None = None,
        frontend_origin: str | None = None,
        images: list | None = None,
    ) -> AsyncIterator[dict]:
        del session, message, on_agent_id, access_token, frontend_origin, images
        yield {"type": "error", "message": self.info.reason or "This provider is not available."}
