"""Last MCP proxy tool-result note, shared by API agents and the Runtime proxy."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

logger = logging.getLogger(__name__)

_KEY = "last_mcp_result"
_KINDS = frozenset({"unchanged", "area-map", "truncated", "off"})


def note_mcp_result(
    hass: HomeAssistant | None,
    *,
    tool: str,
    kind: str,
    agent: str = "",
) -> dict[str, str]:
    label = str(kind or "unchanged").strip() or "unchanged"
    if label not in _KINDS:
        label = "truncated"
    payload = {
        "tool": str(tool or "").strip()[:160],
        "kind": label,
        "agent": str(agent or "").strip()[:120],
    }
    if hass is not None:
        bucket = hass.data.setdefault(DOMAIN, {})
        bucket[_KEY] = payload
    if label in {"unchanged", "off"}:
        logger.debug("mcp proxy last tool result: %s %s", payload["tool"] or "?", label)
    else:
        logger.info("mcp proxy last tool result: %s %s", payload["tool"] or "?", label)
    return payload


def last_mcp_result(hass: HomeAssistant | None) -> dict[str, Any] | None:
    if hass is None:
        return None
    found = (hass.data.get(DOMAIN) or {}).get(_KEY)
    return dict(found) if isinstance(found, dict) else None
