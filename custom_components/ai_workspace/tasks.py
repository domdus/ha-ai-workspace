"""Agent tasks: the ``ai_workspace.run_task`` action and the automations the Tasks page writes.

A task is a normal Home Assistant automation (time trigger + ``ai_workspace.run_task``) with the
"AI Workspace" label. There is no scheduler of our own: Home Assistant runs the automation, the
action runs one agent turn.

Every run starts fresh. Only a task that keeps a task chat sees that chat's earlier runs, so the
prompt must say everything the agent needs (what to check, how to answer).

Loop protection and read-only mode are tool rules (task_guard): cloud agents apply them in their
tool loop, Runtime agents (Claude, Cursor, Codex) in the Runtime's MCP proxy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_RUN_TASK = "run_task"
TASK_ACTION = f"{DOMAIN}.{SERVICE_RUN_TASK}"
TASK_LABEL = "AI Workspace"
TASK_LABEL_ICON = "mdi:robot"
TASK_ORIGIN = "task"
CHAT_NONE = "none"
CHAT_TASK = "task"
DEFAULT_TIMEOUT = 600
MIN_TIMEOUT = 10
MAX_TIMEOUT = 7200
# At most this many tasks run at once; one more waits for nobody and is refused.
MAX_PARALLEL = 3
# The oldest Runtime whose MCP proxy applies task_guard. Older ones get no tasks.
TASK_RUNTIME_MIN = "1.6.1b6"
# Phones show a few lines and expand to about this much; FCM/APNs allow ~4 KB.
NOTIFY_CHARS = 1000
_RUNTIME_KINDS = frozenset({"cursor", "claude", "codex"})
_STATE_KEY = f"{DOMAIN}_tasks"
_STORE_KEY = f"{DOMAIN}.tasks"

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_BUSY = "busy"
STATUS_RUNNING = "running"


def _task_fields(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("chat") == CHAT_TASK and not str(value.get("task_name") or "").strip():
        raise vol.Invalid("A task chat needs a task name.")
    if not str(value.get("prompt") or "").strip():
        raise vol.Invalid("The prompt is empty.")
    return value


RUN_TASK_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("prompt"): cv.string,
            vol.Optional("task_name", default=""): cv.string,
            vol.Optional("agent", default=""): cv.string,
            vol.Optional("chat", default=CHAT_NONE): vol.In([CHAT_NONE, CHAT_TASK]),
            vol.Optional("notify", default=""): cv.string,
            vol.Optional("allow_changes", default=False): cv.boolean,
            vol.Optional("timeout", default=DEFAULT_TIMEOUT): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT)
            ),
        }
    ),
    _task_fields,
)


def task_key(name: str) -> str:
    """Stable key for a task name: its chat and its last run are stored under it."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().casefold()).strip("_")
    return slug[:80] or "task"


def tool_policy(allow_changes: bool) -> dict[str, Any]:
    """What task_guard enforces for this run."""
    return {"task": True, "read_only": not allow_changes}


def task_preamble(name: str, allow_changes: bool, keeps_chat: bool) -> str:
    """Standing note in front of the task's prompt."""
    label = f" “{name.strip()}”" if str(name or "").strip() else ""
    lines = [
        f"This is an unattended AI Workspace task{label}, started by a Home Assistant automation or script. "
        "Nobody reads along and nobody can answer questions: do not ask, finish the task yourself and end with "
        "a short, self-contained answer (what you checked, what you found, what needs attention).",
        "Your reply is delivered as is (push message, chat, automation variable): write no status or progress "
        "sentences (such as “Reading the weather data.”) before or between tool calls, no preamble; "
        "output only the result.",
    ]
    if allow_changes:
        lines.append("You may control devices and change things when the task asks for it.")
    else:
        lines.append(
            "Read-only: only read Home Assistant. Do not try to change anything; say what you would change instead."
        )
    lines.append("Never create, edit or delete automations or scripts, and never start AI Workspace tasks.")
    if keeps_chat:
        lines.append("Earlier runs of this task are in this chat; compare with them when it helps.")
    else:
        lines.append("You have no memory of earlier runs.")
    return "\n".join(lines)


def _squash(text: str) -> str:
    return "".join(str(text or "").split())


def final_answer(segments: list[str], final: str | None = None) -> str:
    """The task result: only the agent's final answer, never the status lines before tool calls.

    `segments` is the streamed reply text split at tool calls (the last one came after the last
    tool call); `final` is the engine's own result text, which some engines send as the whole
    reply including the text from before the tools.
    """
    parts = [str(seg or "").strip() for seg in segments or []]
    parts = [seg for seg in parts if seg]
    tail = parts[-1] if parts else ""
    before = parts[:-1]
    answer = str(final or "").strip()
    if not answer:
        return tail
    # Drop the status lines the final text starts with (whitespace may differ).
    for seg in before:
        want = _squash(seg)
        if not want or not _squash(answer).startswith(want):
            continue
        seen, cut = 0, 0
        for cut, char in enumerate(answer, start=1):
            if not char.isspace():
                seen += 1
            if seen == len(want):
                break
        answer = answer[cut:].strip()
    if not answer:
        return tail
    if tail and tail != answer and _squash(answer).endswith(_squash(tail)) and before:
        # Final text = intro we could not match + the part after the last tool call.
        return tail
    return answer


# Markdown to plain text for push notifications (they show the markers literally).
_MD_FENCE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)")
_MD_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_MD_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_MD_QUOTE = re.compile(r"^\s{0,3}>\s?")
_MD_BULLET = re.compile(r"^(\s*)[-*+]\s+(\[[ xX]\]\s+)?")
_MD_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_MD_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_MD_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_MD_EM_STAR = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_MD_EM_UNDER = re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])")
_MD_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_MD_CODE = re.compile(r"`+([^`]*)`+")


def _plain_inline(text: str) -> str:
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_REF_LINK.sub(r"\1", text)
    text = _MD_AUTOLINK.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    for _ in range(2):  # nested **_x_**
        text = _MD_STRONG.sub(r"\2", text)
        text = _MD_STRIKE.sub(r"\1", text)
        text = _MD_EM_STAR.sub(r"\1", text)
        text = _MD_EM_UNDER.sub(r"\1", text)
    return text


def markdown_to_plain(text: str) -> str:
    """Readable plain text from the agent's Markdown: no **, _, `, #, link syntax; bullets as "• "."""
    lines: list[str] = []
    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _MD_FENCE.match(raw) or ("|" in raw and _MD_TABLE_RULE.match(raw)):
            continue
        if _MD_RULE.match(raw):
            lines.append("")
            continue
        line = _MD_QUOTE.sub("", raw)
        heading = _MD_HEADING.match(line)
        if heading:
            line = heading.group(1)
        bullet = _MD_BULLET.match(line)
        if bullet:
            indent = "  " if len(bullet.group(1).expandtabs(4)) >= 2 else ""
            line = f"{indent}• {line[bullet.end():]}"
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            line = " · ".join(cell for cell in cells if cell)
        lines.append(_plain_inline(line).rstrip())
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def short_result(text: str, limit: int = NOTIFY_CHARS) -> str:
    """Cut to `limit` characters at a line break (or else a word) and end with "…"."""
    text = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    line_cut = head.rfind("\n")
    if line_cut >= limit // 2:
        cut = head[:line_cut].rstrip()
    else:
        cut = head.rsplit(" ", 1)[0].rstrip() if " " in head else head
    return f"{cut.rstrip(' ,;:-–')}…"


def push_text(text: str, limit: int = NOTIFY_CHARS) -> str:
    """The task result as a push message: plain text, cut to a length phones show."""
    return short_result(markdown_to_plain(text), limit)


@dataclass
class RunResult:
    status: str = STATUS_ERROR
    response: str = ""
    agent: str = ""
    agent_id: str = ""
    chat_id: str = ""
    duration: float = 0.0
    error: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """The action's response."""
        return {
            "status": self.status,
            "response": self.response if self.response else self.error,
            "agent": self.agent,
            "chat_id": self.chat_id or None,
            "duration": round(self.duration, 1),
            "usage": usage_summary(self.usage),
        }


def usage_summary(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    cost = usage.get("cost_usd")
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "cost_usd": round(float(cost), 6) if isinstance(cost, (int, float)) else None,
    }


def add_usage(total: dict[str, Any], payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = int(total.get(key) or 0) + int(payload.get(key) or 0)
    cost = payload.get("cost_usd")
    if isinstance(cost, (int, float)):
        total["cost_usd"] = float(total.get("cost_usd") or 0) + float(cost)


# --- Agent choice ------------------------------------------------------------------------------


def _version_ok(have: str, want: str = TASK_RUNTIME_MIN) -> bool:
    from .discovery import _version_key

    have_key, want_key = _version_key(have), _version_key(want)
    if have_key is None or want_key is None:
        return False
    return have_key >= want_key


def _agent_from_entity(hass: HomeAssistant, wanted: str) -> str:
    """conversation.xyz of an AI Workspace agent -> the agent id."""
    if not wanted.startswith("conversation."):
        return wanted
    from homeassistant.helpers import entity_registry as er

    row = er.async_get(hass).async_get(wanted)
    if row is not None and row.platform == DOMAIN and row.unique_id:
        return str(row.unique_id)
    return wanted


def _find_provider(providers: dict[str, Any], wanted: str) -> Any | None:
    if wanted in providers:
        return providers[wanted]
    folded = wanted.casefold()
    for provider in providers.values():
        info = getattr(provider, "info", None)
        names = {str(getattr(info, "title", "") or ""), str(getattr(info, "label", "") or "")}
        if folded in {name.casefold() for name in names if name}:
            return provider
    return None


# Runtime agents a task without an agent prefers when the Default agent is "Last used" (an automation
# has no browser that last picked one). Fixed, documented order: Claude, Cursor, Codex.
RUNTIME_ORDER = ("claude", "cursor", "codex")


def _is_ready(provider: Any) -> bool:
    return bool(getattr(getattr(provider, "info", None), "available", False))


def task_default_agent(hass: HomeAssistant, data: dict[str, Any]) -> Any | None:
    """The one agent a task without `agent` starts with (Fallback list aside).

    The Default agent from the options when it is set. With "Last used" (stored as ""): the first
    signed-in Runtime agent in RUNTIME_ORDER (Runtime new enough for tasks), else the first agent that
    can take a task, else the first agent.
    """
    providers: dict[str, Any] = dict(data.get("providers") or {})
    if not providers:
        return None
    wanted = str(getattr(data.get("settings"), "default_agent", "") or "").strip()
    if wanted:
        found = _find_provider(providers, _agent_from_entity(hass, wanted))
        if found is not None:
            return found
    rows = list(providers.values())
    for kind in RUNTIME_ORDER:
        for provider in rows:
            if str(getattr(provider, "kind", "") or "") == kind and not _not_ready(data, provider):
                return provider
    return next((provider for provider in rows if not _not_ready(data, provider)), rows[0])


def task_fallback_on(data: dict[str, Any]) -> bool:
    """Fallback for tasks: only when it is switched on and a list was saved (fallback_ha.fallback_chain)."""
    from .fallback_ha import fallback_chain

    return bool(fallback_chain(data))


def task_agent_chain(hass: HomeAssistant, data: dict[str, Any], wanted: str = "") -> list[Any]:
    """The agents a task tries, in order. THE single place that picks agents for a task.

    Fallback off (or never saved): exactly one agent, no switching. That is the named agent, else
    task_default_agent. Fallback on: the saved Fallback list in its order, agents waiting out a limit
    or backoff last; a named agent goes first and the rest of the list follows (as in a chat).
    """
    providers: dict[str, Any] = dict(data.get("providers") or {})
    wanted = _agent_from_entity(hass, str(wanted or "").strip())
    named: Any | None = None
    if wanted:
        named = _find_provider(providers, wanted)
        if named is None:
            raise ServiceValidationError(
                f"AI Workspace has no agent named {wanted!r}.",
                translation_domain=DOMAIN,
                translation_key="unknown_agent",
                translation_placeholders={"agent": repr(wanted)},
            )
    from .fallback_ha import book_of, fallback_chain

    ordered = fallback_chain(data)
    if not ordered:
        one = named or task_default_agent(hass, data)
        return [one] if one is not None else []
    book = book_of(hass, data)
    now = book.clock()
    ready = [agent for agent in ordered if not book.blocked(agent, now)]
    waiting = [agent for agent in ordered if agent not in ready]
    listed = [providers[agent] for agent in ready + waiting if agent in providers]
    if named is not None:
        return [named] + [provider for provider in listed if provider is not named and _is_ready(provider)]
    available = [provider for provider in listed if _is_ready(provider)]
    return available or listed[:1]


def _runtime_kind(provider: Any) -> bool:
    return str(getattr(provider, "kind", "") or "") in _RUNTIME_KINDS


def _agent_label(provider: Any) -> str:
    info = getattr(provider, "info", None)
    return str(getattr(info, "title", "") or getattr(info, "label", "") or getattr(info, "id", "") or "")


def _not_ready(data: dict[str, Any], provider: Any) -> str:
    """Why this agent cannot take a task, or empty when it can."""
    info = getattr(provider, "info", None)
    if not getattr(info, "available", False):
        return str(getattr(info, "reason", "") or "This agent is not available.")
    if _runtime_kind(provider) and not _version_ok(str(data.get("runtime_version") or "")):
        return (
            f"Update the AI Workspace Runtime app to {TASK_RUNTIME_MIN} or newer: older Runtimes cannot keep "
            "tasks read-only or stop them from starting tasks."
        )
    return ""


# --- Task state (last run, task chat) ----------------------------------------------------------


class TaskState:
    """Last run and task chat per task name, kept across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store as HaStore

        self._store = HaStore(hass, 1, _STORE_KEY)
        self.tasks: dict[str, dict[str, Any]] = {}
        self.running: set[str] = set()
        self.loaded = False

    async def load(self) -> None:
        if self.loaded:
            return
        raw = await self._store.async_load() or {}
        tasks = raw.get("tasks") if isinstance(raw, dict) else None
        self.tasks = {str(key): dict(value) for key, value in (tasks or {}).items() if isinstance(value, dict)}
        self.loaded = True

    def get(self, key: str) -> dict[str, Any]:
        return dict(self.tasks.get(key) or {})

    async def update(self, key: str, **values: Any) -> None:
        row = self.tasks.setdefault(key, {})
        row.update(values)
        await self._store.async_save({"tasks": self.tasks})


def task_state(hass: HomeAssistant) -> TaskState:
    state = hass.data.get(_STATE_KEY)
    if state is None:
        state = hass.data[_STATE_KEY] = TaskState(hass)
    return state


async def _task_user(hass: HomeAssistant, user_id: str | None) -> str:
    """Whose chats and login a task uses: the admin who called it, else the owner, else any admin."""
    if user_id:
        user = await hass.auth.async_get_user(user_id)
        if user is not None and user.is_admin and not user.system_generated:
            return user.id
    owner = await hass.auth.async_get_owner()
    if owner is not None:
        return owner.id
    for user in await hass.auth.async_get_users():
        if user.is_admin and not user.system_generated and user.is_active:
            return user.id
    raise HomeAssistantError(
        "AI Workspace tasks need an administrator account in Home Assistant.",
        translation_domain=DOMAIN,
        translation_key="tasks_need_admin",
    )


# --- One run -----------------------------------------------------------------------------------


@dataclass
class _Turn:
    answer: str = ""
    error: str = ""
    connection: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    # Provider-side failure (fallback.classify_failure) and the raw tool events for the handoff journal.
    failure: Any = None
    events: list[dict[str, Any]] = field(default_factory=list)


async def _one_turn(
    hass: HomeAssistant,
    data: dict[str, Any],
    provider: Any,
    session: Any,
    user_id: str,
    outbound: str,
    question: str,
    handoff: str,
    policy: dict[str, Any],
    usage: dict[str, Any],
) -> _Turn:
    from .conversation import _login_token
    from .error_text import public_error
    from .fallback import classify_failure
    from .http import async_agent_events
    from .usage_record import finalize_usage, record_usage_turn, record_worker_usage

    store = data["store"]
    turn = _Turn()
    # Text split at tool calls: what the agent writes before a tool call is a status line
    # ("Reading the weather data."), not part of the result.
    segments: list[str] = [""]
    final: str | None = None
    origin = str(hass.config.external_url or hass.config.internal_url or "").rstrip("/")
    async for event in async_agent_events(
        hass,
        user_id,
        session,
        provider,
        outbound,
        language=str(hass.config.language or ""),
        origin=origin,
        access_token=await _login_token(hass, user_id),
        handoff=handoff,
        question=question,
        tools=True,
        admin=True,
        force_tools=True,
        tool_policy=policy,
    ):
        kind = event.get("type")
        if kind == "text":
            segments[-1] += str(event.get("delta") or "")
        elif kind == "result":
            final = str(event.get("text") or "")
        elif kind == "tool":
            if segments[-1].strip():
                segments.append("")
            turn.tools.append({key: event.get(key) for key in ("name", "phase", "text") if key in event})
            turn.events.append(dict(event))
        elif kind == "error":
            turn.error = public_error(event.get("message"))
            turn.connection = bool(event.get("connection"))
            turn.failure = turn.failure or classify_failure(event)
        elif kind == "usage" and event.get("worker"):
            add_usage(
                usage,
                await record_worker_usage(
                    hass, store=store, user_id=user_id, session_id=session.id, event=event, origin=TASK_ORIGIN
                ),
            )
        elif kind == "usage":
            billed = finalize_usage(
                event,
                model=str(event.get("model") or getattr(provider, "model", "") or ""),
                run_id=str(event.get("run_id") or ""),
            )
            if billed is not None:
                add_usage(
                    usage,
                    await record_usage_turn(
                        hass,
                        store=store,
                        user_id=user_id,
                        session_id=session.id,
                        provider=provider,
                        usage=billed,
                        origin=TASK_ORIGIN,
                    ),
                )
    turn.answer = final_answer(segments, final)
    return turn


async def _open_session(hass: HomeAssistant, data: dict[str, Any], provider: Any, user_id: str, chat_id: str, title: str):
    from .http import _create_runtime_session

    store = data["store"]
    session = await hass.async_add_executor_job(store.get_session, user_id, chat_id) if chat_id else None
    agent_id = str(getattr(getattr(provider, "info", None), "id", "") or "")
    if session is None:
        new_id = uuid.uuid4().hex
        if _runtime_kind(provider):
            await _create_runtime_session(hass, user_id, new_id, provider=str(getattr(provider, "kind", "")))
        session = await hass.async_add_executor_job(store.create_session, user_id, agent_id, new_id)
        await hass.async_add_executor_job(store.rename_session, user_id, session.id, title)
        session.title = title
    elif session.provider != agent_id:
        await hass.async_add_executor_job(store.set_provider, user_id, session.id, agent_id)
        session.provider = agent_id
    return session


async def _drop_session(hass: HomeAssistant, data: dict[str, Any], user_id: str, session_id: str) -> None:
    from aiohttp import ClientTimeout
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .http import _runtime_headers_for

    store = data["store"]
    await hass.async_add_executor_job(store.delete_session, user_id, session_id)
    base = str(data.get("runtime_url") or "").rstrip("/")
    if not base:
        return
    try:
        resp = await async_get_clientsession(hass).delete(
            f"{base}/api/sessions/{session_id}",
            headers=_runtime_headers_for(hass, user_id),
            timeout=ClientTimeout(total=5),
        )
        resp.release()
    except Exception:  # noqa: BLE001 - the Runtime forgets idle chats on its own.
        _LOGGER.debug("runtime task chat delete skipped", exc_info=True)


async def async_notify(hass: HomeAssistant, target: str, title: str, message: str) -> None:
    """notify.mobile_app_x (service) or notify.x (notify entity)."""
    target = str(target or "").strip()
    if not target or not message:
        return
    name = target.split(".", 1)[1] if target.startswith("notify.") else target
    try:
        if hass.services.has_service("notify", name):
            await hass.services.async_call("notify", name, {"title": title, "message": message}, blocking=True)
        elif hass.states.get(f"notify.{name}") is not None:
            await hass.services.async_call(
                "notify", "send_message", {"entity_id": f"notify.{name}", "title": title, "message": message},
                blocking=True,
            )
        else:
            _LOGGER.warning("AI Workspace task: notify target %s does not exist", target)
    except HomeAssistantError as exc:
        _LOGGER.warning("AI Workspace task: notify %s failed: %s", target, exc)


async def async_run_task(hass: HomeAssistant, params: dict[str, Any], caller: str | None = None) -> RunResult:
    """Run one task turn and return its result. Never raises for agent failures."""
    data = hass.data.get(DOMAIN)
    if not isinstance(data, dict) or "store" not in data:
        raise HomeAssistantError("AI Workspace is not set up.", translation_domain=DOMAIN, translation_key="not_set_up")
    state = task_state(hass)
    await state.load()
    name = str(params.get("task_name") or "").strip()
    key = task_key(name) if name else ""
    keeps_chat = params.get("chat") == CHAT_TASK and bool(name)
    allow_changes = bool(params.get("allow_changes"))
    started = time.monotonic()
    result = RunResult()
    if key and key in state.running:
        result.status, result.error = STATUS_BUSY, "This task is still running."
        return result
    if len(state.running) >= MAX_PARALLEL:
        result.status, result.error = STATUS_BUSY, f"{MAX_PARALLEL} tasks are running already."
        return result
    run_key = key or f"_anon_{uuid.uuid4().hex}"
    state.running.add(run_key)
    job = asyncio.current_task()
    jobs: set = data.setdefault("chat_jobs", set())
    if job is not None:
        jobs.add(job)
    try:
        user_id = await _task_user(hass, caller)
        chain = task_agent_chain(hass, data, str(params.get("agent") or ""))
        _LOGGER.info(
            "AI Workspace task %s: agent %s (fallback %s)",
            name or "(unnamed)",
            _agent_label(chain[0]) if chain else "-",
            "on" if task_fallback_on(data) else "off",
        )
        prompt = str(params.get("prompt") or "").strip()
        outbound = f"{task_preamble(name, allow_changes, keeps_chat)}\n\n{prompt}"
        policy = tool_policy(allow_changes)
        chat_id = str(state.get(key).get("chat_id") or "") if keeps_chat else ""
        title = name or "Task"
        try:
            async with asyncio.timeout(int(params.get("timeout") or DEFAULT_TIMEOUT)):
                await _run_chain(hass, data, chain, user_id, prompt, outbound, policy, keeps_chat, chat_id, title, result)
            result.status = STATUS_OK if result.response and not result.error else STATUS_ERROR
        except TimeoutError:
            result.status = STATUS_TIMEOUT
            result.error = result.error or "The task ran out of time."
    except (HomeAssistantError, vol.Invalid) as exc:
        result.status, result.error = STATUS_ERROR, str(exc)
    finally:
        state.running.discard(run_key)
        if job is not None:
            jobs.discard(job)
    result.duration = time.monotonic() - started
    if key:
        values: dict[str, Any] = {
            "name": name,
            "last_run": time.time(),
            "last_status": result.status,
            "last_error": result.error if result.status != STATUS_OK else "",
            "last_duration": round(result.duration, 1),
            "last_agent": result.agent,
        }
        if keeps_chat and result.chat_id:
            values["chat_id"] = result.chat_id
        await state.update(key, **values)
    _LOGGER.log(
        logging.INFO if result.status == STATUS_OK else logging.WARNING,
        "AI Workspace task %s: %s in %.1fs (%s)%s",
        name or "(unnamed)",
        result.status,
        result.duration,
        result.agent or "-",
        f": {result.error}" if result.status != STATUS_OK and result.error else "",
    )
    notify = str(params.get("notify") or "").strip()
    if notify:
        text = push_text(result.response) if result.status == STATUS_OK else f"⚠ {result.error or result.status}"
        await async_notify(hass, notify, name or "AI Workspace", text)
    return result


async def _run_chain(
    hass: HomeAssistant,
    data: dict[str, Any],
    chain: list[Any],
    user_id: str,
    prompt: str,
    outbound: str,
    policy: dict[str, Any],
    keeps_chat: bool,
    chat_id: str,
    title: str,
    result: RunResult,
) -> None:
    from .chat_scope import handoff_note
    from .const import provider_token_mode
    from .fallback import KIND_CONNECTION, Failure, TurnJournal, handoff_prompt
    from .fallback_ha import async_load_book, fallback_chain, known_reset
    from .local_time import house_zone

    store = data["store"]
    reasons: list[str] = []
    # With Fallback on, task runs feed the same agent health as chats (limits, backoff).
    book = await async_load_book(hass, data) if fallback_chain(data) else None
    journal = TurnJournal()
    sent = outbound
    # Agent that failed before this one, and why: the HA log shows who took over.
    failed: tuple[str, str] | None = None
    for provider in chain:
        reason = _not_ready(data, provider)
        if reason:
            reasons.append(f"{_agent_label(provider)}: {reason}")
            continue
        result.agent = _agent_label(provider)
        result.agent_id = str(getattr(getattr(provider, "info", None), "id", "") or "")
        if failed is not None:
            _LOGGER.warning(
                "AI Workspace task %s: fallback switched from %s (%s) to %s", title, failed[0], failed[1], result.agent
            )
        session = await _open_session(hass, data, provider, user_id, chat_id if keeps_chat else "", title)
        if keeps_chat:
            # Kept even when this run times out, so the next run continues the same chat.
            result.chat_id = chat_id = session.id
        locks: dict[str, asyncio.Lock] = data.setdefault("locks", {})
        lock = locks.setdefault(session.id, asyncio.Lock())
        try:
            async with lock:
                handoff = ""
                if keeps_chat and _runtime_kind(provider):
                    rows = await hass.async_add_executor_job(store.list_messages, session.id)
                    handoff = handoff_note(
                        rows,
                        session.title,
                        mode=provider_token_mode(provider),
                        model=str(getattr(provider, "model", "") or ""),
                        manual_window=int(getattr(data.get("settings"), "context_window", 0) or 0),
                        zone=house_zone(hass),
                    )
                await hass.async_add_executor_job(store.add_message, session.id, "user", prompt, "[]")
                turn = await _one_turn(
                    hass, data, provider, session, user_id, sent, prompt, handoff, policy, result.usage
                )
                stored = list(turn.tools)
                if turn.error:
                    stored.append({"type": "error", "message": turn.error})
                await hass.async_add_executor_job(
                    store.add_message,
                    session.id,
                    "assistant",
                    turn.answer or turn.error,
                    json.dumps(stored, ensure_ascii=False),
                )
        finally:
            if locks.get(session.id) is lock and not lock.locked():
                locks.pop(session.id, None)
            if not keeps_chat:
                await _drop_session(hass, data, user_id, session.id)
        failure = turn.failure or (Failure(KIND_CONNECTION) if turn.connection else None)
        if failure is None:
            if book is not None and not turn.error:
                book.mark_ok(result.agent_id)
            result.response = turn.answer
            result.error = "" if turn.answer else (turn.error or "The agent returned nothing.")
            if failed is not None:
                _LOGGER.warning(
                    "AI Workspace task %s: finished with fallback agent %s (%s)",
                    title,
                    result.agent,
                    "ok" if turn.answer else "no answer",
                )
            return
        # Provider-side failure (limit, sign-in, timeout, connection, overloaded): the next agent
        # takes over with the task and a journal of the tool calls already made in this run.
        if book is not None and result.agent_id:
            book.mark_failed(result.agent_id, known_reset(hass, provider, failure))
        for event in turn.events:
            journal.note(event, result.agent)
        reasons.append(f"{result.agent}: {turn.error}")
        failed = (result.agent, str(getattr(failure, "kind", "") or "error"))
        # No partial reply text: nobody watched it, so the next agent writes the whole result again.
        sent = handoff_prompt(outbound, journal, failed_agent=result.agent, reason=failure.kind)
    result.error = "; ".join(reasons) or "AI Workspace has no agent that can run tasks."


# --- Service -----------------------------------------------------------------------------------


async def _handle_run_task(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    params = dict(call.data)
    caller = call.context.user_id
    if call.return_response:
        result = await async_run_task(hass, params, caller)
        return result.payload()

    async def _background() -> None:
        try:
            await async_run_task(hass, params, caller)
        except Exception:  # noqa: BLE001 - nobody waits for this run; log it.
            _LOGGER.exception("AI Workspace task failed")

    if not isinstance(hass.data.get(DOMAIN), dict):
        raise HomeAssistantError("AI Workspace is not set up.", translation_domain=DOMAIN, translation_key="not_set_up")
    hass.async_create_background_task(_background(), f"ai_workspace_task_{task_key(params.get('task_name') or '')}")
    return None


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_RUN_TASK):
        return

    async def _run(call: ServiceCall) -> ServiceResponse:
        return await _handle_run_task(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_RUN_TASK, _run, schema=RUN_TASK_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )


# --- Automations for the Tasks page ------------------------------------------------------------

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCHEDULE_DAILY = "daily"
SCHEDULE_WEEKLY = "weekly"
SCHEDULE_INTERVAL = "interval"
SCHEDULE_CUSTOM = "custom"
TARGET_CHAT = "chat"
TARGET_PUSH = "push"
TARGET_BOTH = "both"
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
TASK_DESCRIPTION = "AI Workspace task. Edit it on the Tasks page in AI Workspace or here."


def _clock(value: Any) -> str:
    found = _TIME.match(str(value or "").strip())
    if not found:
        raise ValueError("Time must look like 07:30.")
    return f"{int(found.group(1)):02d}:{found.group(2)}:00"


def schedule_trigger(schedule: dict[str, Any]) -> dict[str, Any]:
    kind = str(schedule.get("kind") or SCHEDULE_DAILY)
    if kind == SCHEDULE_DAILY:
        return {"trigger": "time", "at": _clock(schedule.get("time"))}
    if kind == SCHEDULE_WEEKLY:
        days = [day for day in WEEKDAYS if day in set(schedule.get("weekdays") or [])]
        if not days:
            raise ValueError("Pick at least one weekday.")
        return {"trigger": "time", "at": _clock(schedule.get("time")), "weekday": days}
    if kind == SCHEDULE_INTERVAL:
        try:
            every = int(schedule.get("every") or 0)
        except (TypeError, ValueError):
            every = 0
        unit = "minutes" if schedule.get("unit") == "minutes" else "hours"
        top = 59 if unit == "minutes" else 23
        if not 1 <= every <= top:
            raise ValueError(f"Repeat every 1 to {top} {unit}.")
        trigger: dict[str, Any] = {"trigger": "time_pattern", unit: f"/{every}"}
        if unit == "hours":
            trigger["minutes"] = 0
        return trigger
    raise ValueError("Unknown schedule.")


def parse_schedule(triggers: Any) -> dict[str, Any]:
    """The page's schedule for these triggers, or kind=custom when it is anything else."""
    if isinstance(triggers, dict):
        triggers = [triggers]
    if not isinstance(triggers, list) or len(triggers) != 1 or not isinstance(triggers[0], dict):
        return {"kind": SCHEDULE_CUSTOM}
    trigger = triggers[0]
    kind = str(trigger.get("trigger") or trigger.get("platform") or "")
    if kind == "time":
        at = trigger.get("at")
        if isinstance(at, list) and len(at) == 1:
            at = at[0]
        found = _TIME.match(str(at or ""))
        if not found:
            return {"kind": SCHEDULE_CUSTOM}
        clock = f"{int(found.group(1)):02d}:{found.group(2)}"
        days = trigger.get("weekday")
        if days:
            days = [days] if isinstance(days, str) else list(days)
            if set(days) != set(WEEKDAYS):
                return {"kind": SCHEDULE_WEEKLY, "time": clock, "weekdays": [day for day in WEEKDAYS if day in days]}
        return {"kind": SCHEDULE_DAILY, "time": clock}
    if kind == "time_pattern":
        for unit in ("minutes", "hours"):
            raw = str(trigger.get(unit) or "")
            other = "hours" if unit == "minutes" else "minutes"
            if raw.startswith("/") and raw[1:].isdigit():
                if unit == "minutes" and trigger.get("hours") not in (None, "", "*"):
                    break
                if unit == "hours" and str(trigger.get(other, 0)) not in ("0", "00"):
                    break
                return {"kind": SCHEDULE_INTERVAL, "every": int(raw[1:]), "unit": unit}
    return {"kind": SCHEDULE_CUSTOM}


def new_automation_id() -> str:
    return f"ai_workspace_task_{uuid.uuid4().hex[:12]}"


def build_automation(form: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Automation config for a task form. Keeps what the editor added when the page cannot show it.

    existing: the automation's current config. A custom schedule (edited in the automation editor)
    stays as it is unless the form sends a new one.
    """
    name = str(form.get("name") or "").strip()
    prompt = str(form.get("prompt") or "").strip()
    if not name:
        raise ValueError("Give the task a name.")
    if not prompt:
        raise ValueError("The prompt is empty.")
    target = str(form.get("target") or TARGET_CHAT)
    notify = str(form.get("notify") or "").strip()
    if target in {TARGET_PUSH, TARGET_BOTH} and not notify:
        raise ValueError("Pick where the push message goes.")
    data: dict[str, Any] = {"task_name": name, "prompt": prompt}
    agent = str(form.get("agent") or "").strip()
    if agent:
        data["agent"] = agent
    data["chat"] = CHAT_TASK if target in {TARGET_CHAT, TARGET_BOTH} else CHAT_NONE
    if target in {TARGET_PUSH, TARGET_BOTH}:
        data["notify"] = notify
    data["allow_changes"] = bool(form.get("allow_changes"))
    timeout = form.get("timeout")
    if timeout not in (None, ""):
        data["timeout"] = max(MIN_TIMEOUT, min(int(timeout), MAX_TIMEOUT))
    config: dict[str, Any] = dict(existing or {})
    config.pop("id", None)
    config["alias"] = name
    config.setdefault("description", TASK_DESCRIPTION)
    schedule = form.get("schedule") if isinstance(form.get("schedule"), dict) else {}
    if schedule.get("kind", SCHEDULE_DAILY) != SCHEDULE_CUSTOM or not existing:
        config.pop("trigger", None)
        config["triggers"] = [schedule_trigger(schedule)]
    config.setdefault("conditions", config.pop("condition", []) if "condition" in config else [])
    step = {"action": TASK_ACTION, "data": data}
    actions = config.pop("actions", config.pop("action", None))
    actions = [actions] if isinstance(actions, dict) else list(actions or [])
    index = next((i for i, item in enumerate(actions) if _is_task_step(item)), None)
    if index is None:
        actions.insert(0, step)
    else:
        actions[index] = step
    config["actions"] = actions
    config.setdefault("mode", "single")
    return config


def _is_task_step(step: Any) -> bool:
    return isinstance(step, dict) and str(step.get("action") or step.get("service") or "") == TASK_ACTION


def has_task_step(config: dict[str, Any] | None) -> bool:
    """True when an automation config runs ai_workspace.run_task among its top-level actions."""
    if not isinstance(config, dict):
        return False
    actions = config.get("actions", config.get("action"))
    actions = [actions] if isinstance(actions, dict) else list(actions or [])
    return any(_is_task_step(item) for item in actions)


def parse_automation(config: dict[str, Any] | None) -> dict[str, Any]:
    """What the Tasks page shows for an automation. editable=False: open it in the editor."""
    config = config if isinstance(config, dict) else {}
    actions = config.get("actions", config.get("action"))
    actions = [actions] if isinstance(actions, dict) else list(actions or [])
    steps = [item for item in actions if _is_task_step(item)]
    schedule = parse_schedule(config.get("triggers", config.get("trigger")))
    found: dict[str, Any] = {
        "name": str(config.get("alias") or ""),
        "schedule": schedule,
        "editable": False,
        "has_task": bool(steps),
    }
    if not steps:
        return found
    data = steps[0].get("data") or steps[0].get("data_template") or {}
    data = data if isinstance(data, dict) else {}
    chat = data.get("chat") == CHAT_TASK
    notify = str(data.get("notify") or "")
    found.update(
        {
            "task_name": str(data.get("task_name") or config.get("alias") or ""),
            "prompt": str(data.get("prompt") or ""),
            "agent": str(data.get("agent") or ""),
            "target": TARGET_BOTH if chat and notify else (TARGET_PUSH if notify else TARGET_CHAT),
            "notify": notify,
            "allow_changes": bool(data.get("allow_changes")),
            "timeout": data.get("timeout"),
        }
    )
    found["editable"] = len(steps) == 1 and isinstance(data.get("prompt"), str)
    return found
