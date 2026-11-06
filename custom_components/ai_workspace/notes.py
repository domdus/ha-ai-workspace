"""Remembered notes: a user-editable field the agent may update.

Stored separately from the system prompt so a write does not reload the integration.
The Configure switch (or YAML ``notes: false``) hides the field from chat
(neither read nor write). The text stays editable on the form.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_NOTES = "notes"
CONF_NOTES_TEXT = "notes_text"
NOTES_MAX_CHARS = 2000
NOTES_STORE_VERSION = 1
NOTES_STORE_KEY = f"{DOMAIN}_notes"
TOOL_NAME = "workspace_notes"
NOTES_SERVER = "notes"
NOTES_NUDGE = (
    "If this message asks you to remember something or complains about a habit you should stop, "
    "call workspace_notes this turn."
)

# User asked to remember, or complained about a habit, in the 15 chat UI languages.
_REMEMBER = re.compile(
    r"("
    r"remember(?:\s+(?:this|that|it))"
    r"|don'?t forget"
    r"|merk(?:e)?\s+dir(?:\s+(?:das|dass|dies))?"
    r"|behalte\s+(?:das|dir|dir\s+das)"
    r"|souviens[-\s]?toi"
    r"|retiens"
    r"|acu[eé]rdate"
    r"|recuerda(?:\s+(?:esto|eso))?"
    r"|ricordati"
    r"|ricorda(?:\s+(?:questo|che))?"
    r"|onthoud(?:\s+(?:dit|dat))?"
    r"|zapami[eę]taj"
    r"|zapamatuj(?:\s+si)?"
    r"|kom\s+ih[åa]g"
    r"|запомни"
    r"|기억(?:해|해줘)?"
    r"|记住"
    r"|記住"
    r"|yadda\s+saxla"
    r"|memoru"
    r")",
    re.IGNORECASE,
)
_COMPLAINT = re.compile(
    r"("
    r"stop doing"
    r"|don'?t(?:\s+ever)?\s+do\s+that"
    r"|never do(?:\s+that)?"
    r"|i don'?t want you to"
    r"|h[öo]r auf"
    r"|lass das"
    r"|mach das nicht"
    r"|unterlass"
    r"|nie wieder"
    r"|arr[eê]te"
    r"|ne fais plus"
    r"|no hagas"
    r"|non farlo"
    r"|hou daarmee op"
    r"|przesta[nń]"
    r"|p[řr]esta[nň]"
    r"|sluta"
    r"|перестань"
    r"|하지\s*마"
    r"|别再"
    r"|不要再"
    r"|別再"
    r"|etm[eə]"
    r"|ne faru"
    r")",
    re.IGNORECASE,
)

TOOL_DESCRIPTION = (
    "Update the user's remembered notes (English bullets, max "
    f"{NOTES_MAX_CHARS} characters). The user can see and edit the same field in "
    "Configure. Use add for one new fact, remove to drop a line, replace to rewrite "
    "the whole list when it is full or stale. Write English only. No live house state, "
    "no entity ids, no one-off tasks. Call this when the user asks you to remember "
    "something (any language: remember this, merke dir, souviens-toi, acuérdate, "
    "ricordati, onthoud, zapamiętaj, zapamatuj si, kom ihåg, запомни, 기억해, 记住, "
    "記住, yadda saxla, memoru) or complains about something you should stop doing."
)


def clip_notes(text: str, max_chars: int = NOTES_MAX_CHARS) -> str:
    """Keep notes within the cap. Prefer cutting on a line break so a bullet is not split."""
    clean = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    newline = cut.rfind("\n")
    if newline >= max_chars // 2:
        cut = cut[:newline]
    return cut.rstrip()


def as_bullet(text: str) -> str:
    line = " ".join(str(text or "").split())
    if not line:
        return ""
    if line.startswith(("- ", "* ")):
        return f"- {line[2:].strip()}"
    return f"- {line}"


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in str(text or "").split("\n") if line.strip()]


def apply_notes_action(current: str, action: str, text: str = "") -> dict[str, Any]:
    """Pure notes mutation. Does not read or write storage."""
    notes = clip_notes(current)
    used = len(notes)
    left = max(0, NOTES_MAX_CHARS - used)
    kind = str(action or "").strip().lower()
    if kind not in {"add", "remove", "replace"}:
        return {
            "ok": False,
            "error": "unknown_action",
            "used": used,
            "max": NOTES_MAX_CHARS,
            "left": left,
            "notes": notes,
        }
    if kind == "replace":
        raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(raw) > NOTES_MAX_CHARS:
            return {
                "ok": False,
                "error": "full",
                "used": used,
                "max": NOTES_MAX_CHARS,
                "left": left,
                "notes": notes,
                "hint": "The replacement is over the limit. Drop stale lines so it fits, then replace.",
            }
        return _ok(raw)
    if kind == "add":
        bullet = as_bullet(text)
        if not bullet:
            return {
                "ok": False,
                "error": "empty",
                "used": used,
                "max": NOTES_MAX_CHARS,
                "left": left,
                "notes": notes,
            }
        existing = {line.casefold() for line in _lines(notes)}
        if bullet.casefold() in existing:
            return _ok(notes)
        next_text = f"{notes}\n{bullet}".strip() if notes else bullet
        if len(next_text) > NOTES_MAX_CHARS:
            return {
                "ok": False,
                "error": "full",
                "used": used,
                "max": NOTES_MAX_CHARS,
                "left": left,
                "notes": notes,
                "hint": "Notes are full. Replace them: drop stale lines so the new fact fits.",
            }
        return _ok(next_text)
    needle = " ".join(str(text or "").split()).casefold()
    if not needle:
        return {
            "ok": False,
            "error": "empty",
            "used": used,
            "max": NOTES_MAX_CHARS,
            "left": left,
            "notes": notes,
        }
    kept = [line for line in _lines(notes) if needle not in line.casefold()]
    if len(kept) == len(_lines(notes)):
        return {
            "ok": False,
            "error": "not_found",
            "used": used,
            "max": NOTES_MAX_CHARS,
            "left": left,
            "notes": notes,
        }
    return _ok("\n".join(kept))


def _ok(text: str) -> dict[str, Any]:
    notes = clip_notes(text)
    return {
        "ok": True,
        "notes": notes,
        "used": len(notes),
        "max": NOTES_MAX_CHARS,
        "left": max(0, NOTES_MAX_CHARS - len(notes)),
    }


def wants_notes_write(message: str) -> bool:
    text = str(message or "")
    return bool(_REMEMBER.search(text) or _COMPLAINT.search(text))


def remember_nudge(settings, message: str, *, admin: bool) -> str:
    if not admin or not getattr(settings, "notes", False):
        return ""
    if not wants_notes_write(message):
        return ""
    return NOTES_NUDGE


def prompt_block(notes_text: str, *, admin: bool, write: bool) -> str:
    """Standing prompt fragment. Caller must skip this entirely when the option is off."""
    body = clip_notes(notes_text)
    parts: list[str] = []
    if body:
        parts.append(f"Remembered notes (English, user-editable):\n{body}")
    if write and admin:
        parts.append(
            "Remembered notes (Merknotizen) are a separate Configure field, not the system prompt. "
            "The system prompt is user-edited only; never write there. "
            "Write notes in English, one hyphen bullet per standing fact. "
            f"Maximum {NOTES_MAX_CHARS} characters. "
            "Call workspace_notes when the user asks you to remember something in any language "
            "(remember this, merke dir, souviens-toi, acuérdate, ricordati, onthoud, zapamiętaj, "
            "zapamatuj si, kom ihåg, запомни, 기억해, 记住, 記住, yadda saxla, memoru) "
            "or complains about something you should stop doing. "
            "Do not store live house state, entity ids, one-off tasks, or guesses. "
            "If the notes are full, replace them and drop stale lines so the new fact fits. "
            "Never delete a note the user did not imply."
        )
    elif body:
        parts.append("Follow the remembered notes. You cannot change them in this chat.")
    return "\n\n".join(part for part in parts if part.strip())


def notes_prompt(settings, *, admin: bool, write: bool = True) -> str:
    if not getattr(settings, "notes", False):
        return ""
    return prompt_block(str(getattr(settings, "notes_text", "") or ""), admin=admin, write=write)


def tool_definition() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "replace"],
                    "description": "add one bullet, remove matching lines, or replace the whole field.",
                },
                "text": {
                    "type": "string",
                    "description": "English note, or the full replacement list. For remove, words that match a line.",
                },
            },
            "required": ["action", "text"],
        },
    }


def publish_notes(hass, text: str) -> None:
    """Keep the live settings copy in sync so the next turn sees the write without a reload."""
    bucket = hass.data.get(DOMAIN) or {}
    saved = clip_notes(text)
    settings = bucket.get("settings")
    if settings is not None:
        settings.notes_text = saved
    for provider in (bucket.get("providers") or {}).values():
        inner = getattr(provider, "settings", None)
        if inner is not None:
            inner.notes_text = saved


async def async_load_notes(hass) -> str:
    from homeassistant.helpers.storage import Store

    data = await Store(hass, NOTES_STORE_VERSION, NOTES_STORE_KEY).async_load()
    return clip_notes(str((data or {}).get("text") or ""))


async def async_save_notes(hass, text: str) -> str:
    from homeassistant.helpers.storage import Store

    saved = clip_notes(text)
    await Store(hass, NOTES_STORE_VERSION, NOTES_STORE_KEY).async_save({"text": saved})
    publish_notes(hass, saved)
    return saved


class NotesClient:
    """In-process tool client with the same shape as McpHttpClient for the API loop."""

    def __init__(self, hass, *, admin: bool = True) -> None:
        self.hass = hass
        self.admin = admin

    async def initialize(self) -> dict[str, Any]:
        return {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return [tool_definition()]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name != TOOL_NAME:
            from .mcp_client import McpError

            raise McpError(f"Unknown notes tool: {name}")
        settings = (self.hass.data.get(DOMAIN) or {}).get("settings")
        if not getattr(settings, "notes", False) or not self.admin:
            return {"ok": False, "error": "disabled"}
        args = arguments or {}
        current = await async_load_notes(self.hass)
        result = apply_notes_action(current, str(args.get("action") or ""), str(args.get("text") or ""))
        if result.get("ok"):
            await async_save_notes(self.hass, str(result.get("notes") or ""))
        return result


def notes_mcp_url(hass) -> str:
    base = ""
    try:
        from homeassistant.helpers.network import get_url

        base = get_url(hass, prefer_external=False, allow_cloud=False)
    except Exception:
        base = ""
    if not base:
        base = str(getattr(hass.config, "internal_url", None) or "").strip()
    if not base:
        base = "http://127.0.0.1:8123"
    return f"{base.rstrip('/')}/api/ai_workspace/notes/mcp"


def mcp_server_config(hass, token: str = "") -> dict[str, Any]:
    server: dict[str, Any] = {"type": "http", "url": notes_mcp_url(hass)}
    secret = str(token or "").strip()
    if secret:
        server["headers"] = {"Authorization": f"Bearer {secret}"}
    return server
