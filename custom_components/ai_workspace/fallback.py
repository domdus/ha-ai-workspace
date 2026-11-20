"""Agent fallback chain: when the agent's provider fails, the next agent in the list goes on.

Only provider-side failures move a turn to the next agent: a plan or token limit, HTTP 429, an
expired or invalid sign-in, a timeout, a connection error, an overloaded or failing server (5xx).
A stopped turn, a failing tool, a refusal or a bad request never do: another agent would not
fix those, and repeating the turn could repeat what it already did.

Sessions are not portable between engines, so the next agent gets the original task, the chat
transcript (as on every engine switch) and a journal of the tool calls this turn already made,
with the instruction not to repeat side effects.

Everything here is plain Python (no Home Assistant imports) so it can be tested on its own;
http.py wires it into the chat turn.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping

# Why an agent failed. Anything else is not a reason to fall back.
KIND_LIMIT = "limit"
KIND_AUTH = "auth"
KIND_TIMEOUT = "timeout"
KIND_CONNECTION = "connection"
KIND_OVERLOADED = "overloaded"
KINDS = (KIND_LIMIT, KIND_AUTH, KIND_TIMEOUT, KIND_CONNECTION, KIND_OVERLOADED)

# "Back to the preferred agent".
RETURN_OFF = "off"
RETURN_NEW_MESSAGE = "new_message"
RETURN_AFTER_RESET = "after_reset"
RETURN_MODES = (RETURN_OFF, RETURN_NEW_MESSAGE, RETURN_AFTER_RESET)
DEFAULT_RETURN = RETURN_NEW_MESSAGE

# Wait before an agent is tried again after a failure without a known reset: 5, 15, then 60 minutes.
BACKOFF_SECONDS = (300, 900, 3600)
# After a promotion the chat stays put for a while, so two agents do not take turns failing.
PROMOTION_LOCK_SECONDS = 600
# A paused turn looks again at least this often, and gives up after a day.
PAUSE_MIN_SECONDS = 30
PAUSE_MAX_SECONDS = 3600
PAUSE_GIVE_UP_SECONDS = 24 * 3600

CAP_CHAT = "chat"
CAP_WORKSPACE = "workspace"
RUNTIME_KINDS = frozenset({"cursor", "claude", "codex"})

_AUTH_CODES = frozenset({"claude_auth_failed", "codex_auth_failed", "cursor_auth_failed"})


@dataclass(frozen=True)
class Failure:
    kind: str
    reset_at: int | None = None
    engine: str = ""
    window: str = ""


# --- Classifier -------------------------------------------------------------------------------

# Never a provider failure, whatever else the text says: tools and MCP servers, refusals, bad input.
_NOT_PROVIDER = re.compile(
    r"\bmcp\b|\btools?\b|tool call|tool result|function call"
    r"|refus(?:ed|es|al)? to (?:answer|help|comply|do)|model refused|refusal|content (?:filter|policy)"
    r"|safety|policy violation|cannot help with|can't help with"
    r"|context (?:length|window)|too long|maximum context|prompt is too long|too many tokens in"
    r"|invalid[_ ]request|bad request|unprocessable|not supported|unsupported"
    r"|does not offer the model|model (?:not found|does not exist)|no such model|unknown model"
    r"|message is empty|stopped by the user|cancell?ed by the user|interrupted by the user",
    re.IGNORECASE,
)
_LIMIT_TEXT = re.compile(
    r"rate[\s_-]?limit|usage limit|limit (?:reached|exceeded|is full)|hit (?:its|a|the) (?:usage|rate)"
    r"|quota|too many requests|\b429\b|billing|insufficient[_ ](?:credit|quota|funds)|credit balance"
    r"|out of credits|plan limit|session is full|weekly limit|resource[_ ]exhausted",
    re.IGNORECASE,
)
_AUTH_TEXT = re.compile(
    r"unauthori[sz]ed|\b401\b|\b403\b|forbidden|invalid[\s_-]*(?:x-)?api[\s_-]*key|incorrect api key"
    r"|authentication|invalid bearer|no longer accepts|(?:token|sign-in|credential|key|login|session)"
    r" (?:has )?(?:expired|been revoked)|not logged in|sign in (?:again|with)|please run /login|invalid_grant",
    re.IGNORECASE,
)
_TIMEOUT_TEXT = re.compile(
    r"timed? ?out|timeout|deadline exceeded|did not answer in time|\b408\b|\b504\b|gateway time",
    re.IGNORECASE,
)
_OVERLOADED_TEXT = re.compile(
    r"overloaded|\b5(?:00|02|03|29)\b|service unavailable|internal server error|bad gateway"
    r"|server error|temporarily unavailable|capacity|try again later",
    re.IGNORECASE,
)
_CONNECTION_TEXT = re.compile(
    r"unreachable|connection (?:refused|reset|error|closed|aborted|failed)|cannot connect|could not connect"
    r"|network (?:error|is unreachable)|econnreset|econnrefused|name resolution|getaddrinfo"
    r"|server disconnected|failed to establish|no route to host|ssl(?:error| handshake)",
    re.IGNORECASE,
)


def _int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number


def classify_status(status: object) -> str | None:
    code = _int(status)
    if code is None:
        return None
    if code == 429:
        return KIND_LIMIT
    if code in (401, 403):
        return KIND_AUTH
    if code in (408, 504, 524):
        return KIND_TIMEOUT
    if code == 529 or 500 <= code <= 599:
        return KIND_OVERLOADED
    return None


def classify_text(text: object) -> str | None:
    raw = str(text or "")
    if not raw.strip() or _NOT_PROVIDER.search(raw):
        return None
    for kind, pattern in (
        (KIND_LIMIT, _LIMIT_TEXT),
        (KIND_AUTH, _AUTH_TEXT),
        (KIND_TIMEOUT, _TIMEOUT_TEXT),
        (KIND_CONNECTION, _CONNECTION_TEXT),
        (KIND_OVERLOADED, _OVERLOADED_TEXT),
    ):
        if pattern.search(raw):
            return kind
    return None


def classify_failure(event: Mapping[str, Any] | None) -> Failure | None:
    """A chat error event -> the provider failure behind it, or None when no other agent should try."""
    if not isinstance(event, Mapping) or event.get("type") != "error":
        return None
    if event.get("cancelled") or event.get("user_cancel") or event.get("tool_error"):
        return None
    code = str(event.get("code") or "").strip().lower()
    engine = str(event.get("engine") or "").strip().lower()
    reset = _int(event.get("reset_at"))
    if code.endswith("_plan_rejected"):
        return Failure(KIND_LIMIT, reset, engine or code.split("_", 1)[0], str(event.get("window") or ""))
    if code in _AUTH_CODES:
        return Failure(KIND_AUTH, None, engine or code.split("_", 1)[0])
    if event.get("status") not in (None, ""):
        # The HTTP status is the provider's own answer: a 400 or 404 is the request, not the provider.
        kind = classify_status(event.get("status"))
        return Failure(kind, reset, engine) if kind else None
    if event.get("timeout"):
        return Failure(KIND_TIMEOUT, None, engine)
    if event.get("connection"):
        return Failure(KIND_CONNECTION, None, engine)
    kind = classify_text(event.get("message"))
    return Failure(kind, reset if kind == KIND_LIMIT else None, engine) if kind else None


def classify_exception(exc: BaseException) -> Failure | None:
    """An exception out of an agent's turn. A cancelled turn is never a failure."""
    if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, GeneratorExit)):
        return None
    status = getattr(exc, "status", None)
    if status is not None:
        kind = classify_status(status)
        return Failure(kind) if kind else None
    if isinstance(exc, TimeoutError):
        return Failure(KIND_TIMEOUT)
    try:
        from aiohttp import ClientConnectionError, ServerTimeoutError
    except ImportError:  # pragma: no cover - aiohttp ships with Home Assistant
        ClientConnectionError = ServerTimeoutError = ()  # type: ignore[assignment]
    if ServerTimeoutError and isinstance(exc, ServerTimeoutError):
        return Failure(KIND_TIMEOUT)
    if (ClientConnectionError and isinstance(exc, ClientConnectionError)) or isinstance(exc, ConnectionError):
        return Failure(KIND_CONNECTION)
    kind = classify_text(str(exc))
    return Failure(kind) if kind else None


# --- Capabilities -----------------------------------------------------------------------------


def agent_caps(kind: str) -> frozenset[str]:
    """Runtime agents (Claude SDK, Cursor, Codex) have a workspace and a shell; cloud agents only chat."""
    if str(kind or "") in RUNTIME_KINDS:
        return frozenset({CAP_CHAT, CAP_WORKSPACE})
    return frozenset({CAP_CHAT})


# Tools that only exist on the Runtime: a turn that used them needs a workspace to go on.
_WORKSPACE_TOOL = re.compile(
    r"^(?:bash|shell|sh|terminal|run_terminal_cmd|command|commandexecution|write|edit|multiedit|notebookedit"
    r"|apply_patch|filechange|file_change|edit_file|create_file|delete_file|str_replace\w*|read|glob|grep|ls"
    r"|git\w*)$",
    re.IGNORECASE,
)


def is_workspace_tool(name: object) -> bool:
    return bool(_WORKSPACE_TOOL.match(str(name or "").strip()))


# Words that mark a tool as only looking. Everything else may change something, and its calls are
# what the next agent must not repeat.
_READ_WORDS = frozenset(
    {
        "get", "list", "read", "search", "find", "fetch", "lookup", "query", "show", "describe", "status",
        "history", "log", "logs", "glob", "grep", "ls", "load", "catalog", "map", "overview", "info", "view",
        "check", "live", "context",
    }
)
_WORD = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def has_side_effect(name: object) -> bool:
    raw = str(name or "").strip()
    if not raw:
        return False
    # mcp__server__tool: only the tool part says what it does.
    raw = raw.rsplit("__", 1)[-1]
    if is_workspace_tool(raw):
        return raw.lower() not in {"read", "glob", "grep", "ls"}
    words = {word.lower() for word in _WORD.findall(raw)}
    return not (words & _READ_WORDS)


# --- Health of each agent ---------------------------------------------------------------------


@dataclass
class AgentHealth:
    kind: str = ""
    failed_at: float = 0.0
    until: float = 0.0
    failures: int = 0
    reset_known: bool = False
    probes: int = 0


@dataclass
class ChatFallback:
    """Per chat: the agent it runs on now and whether it got there by falling back."""

    active: str = ""
    preferred: str = ""
    fell_back: bool = False
    reason: str = ""
    switched_at: float = 0.0
    promoted_at: float = 0.0


class FallbackBook:
    """Which agents failed and until when, and the fallback state of each chat."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.health: dict[str, AgentHealth] = {}
        self.chats: dict[str, ChatFallback] = {}
        self.on_change: Callable[[], None] | None = None

    # Agents
    def mark_failed(self, agent_id: str, failure: Failure, *, probe: bool = False) -> AgentHealth:
        now = self.clock()
        item = self.health.setdefault(agent_id, AgentHealth())
        item.kind = failure.kind
        item.failed_at = now
        item.failures += 1
        if probe:
            item.probes += 1
        if failure.kind == KIND_LIMIT and failure.reset_at and failure.reset_at > now:
            item.until = float(failure.reset_at)
            item.reset_known = True
        else:
            item.until = now + BACKOFF_SECONDS[min(item.failures, len(BACKOFF_SECONDS)) - 1]
            item.reset_known = False
        self._changed()
        return item

    def mark_ok(self, agent_id: str) -> None:
        if self.health.pop(agent_id, None) is not None:
            self._changed()

    def blocked(self, agent_id: str, now: float | None = None) -> bool:
        item = self.health.get(agent_id)
        return item is not None and item.until > (self.clock() if now is None else now)

    def until(self, agent_id: str) -> float:
        item = self.health.get(agent_id)
        return item.until if item is not None else 0.0

    def may_probe(self, agent_id: str, mode: str, now: float | None = None) -> bool:
        """Whether a promotion check may ask this agent now.

        A known limit reset is never probed early. Otherwise "On new message" asks once at the
        next message, and after a failed check waits 5, 15, then 60 minutes; "After reset or
        wait time" always waits that time first.
        """
        item = self.health.get(agent_id)
        if item is None:
            return True
        now = self.clock() if now is None else now
        if item.reset_known or mode != RETURN_NEW_MESSAGE or item.probes:
            return now >= item.until
        return True

    # Chats
    def chat(self, session_id: str) -> ChatFallback | None:
        return self.chats.get(session_id)

    def set_chat(self, session_id: str, state: ChatFallback) -> None:
        self.chats[session_id] = state
        self._changed()

    def drop_chat(self, session_id: str) -> None:
        if self.chats.pop(session_id, None) is not None:
            self._changed()

    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - saving is best effort
                pass

    # Saved between restarts
    def dump(self) -> dict[str, Any]:
        return {
            "health": {key: asdict(value) for key, value in self.health.items()},
            "chats": {key: asdict(value) for key, value in self.chats.items()},
        }

    def load(self, data: Mapping[str, Any] | None) -> None:
        data = data if isinstance(data, Mapping) else {}
        now = self.clock()
        for key, value in (data.get("health") or {}).items():
            try:
                item = AgentHealth(**value)
            except TypeError:
                continue
            # Old failures without a pending wait mean nothing after a restart.
            if item.until > now:
                self.health[str(key)] = item
        for key, value in (data.get("chats") or {}).items():
            try:
                self.chats[str(key)] = ChatFallback(**value)
            except TypeError:
                continue


# --- Walking the list -------------------------------------------------------------------------


def clean_chain(chain: Iterable[str], known: Iterable[str]) -> list[str]:
    """The configured order, without duplicates and agents that no longer exist."""
    seen: set[str] = set()
    valid = set(known)
    out: list[str] = []
    for item in chain or ():
        key = str(item or "").strip()
        if key and key in valid and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def capable(chain: Iterable[str], needs: Iterable[str], caps_of: Callable[[str], Iterable[str]]) -> list[str]:
    wanted = set(needs)
    return [agent for agent in chain if wanted <= set(caps_of(agent))]


def next_agent(
    chain: list[str],
    *,
    tried: Iterable[str],
    needs: Iterable[str],
    caps_of: Callable[[str], Iterable[str]],
    book: FallbackBook,
    available: Callable[[str], bool] = lambda _agent: True,
) -> str | None:
    """The first agent from the top that was not tried in this turn, can do the task and is not waiting."""
    done = set(tried)
    now = book.clock()
    for agent in capable(chain, needs, caps_of):
        if agent in done or book.blocked(agent, now) or not available(agent):
            continue
        return agent
    return None


def first_ready(chain: list[str], book: FallbackBook, available: Callable[[str], bool] = lambda _a: True) -> str:
    """The agent a new chat starts with: the preferred one unless it is known to be waiting."""
    now = book.clock()
    for agent in chain:
        if not book.blocked(agent, now) and available(agent):
            return agent
    return chain[0] if chain else ""


Probe = Callable[[str], Awaitable[Failure | None]]


async def promotion_target(
    chain: list[str],
    state: ChatFallback | None,
    *,
    mode: str,
    needs: Iterable[str],
    caps_of: Callable[[str], Iterable[str]],
    book: FallbackBook,
    probe: Probe,
) -> str | None:
    """At the start of a turn: an agent above the current one that is back, checked cheaply, or None.

    Only chats that fell back move up; a chat the user moved by hand stays where it is.
    Agents are checked from the top. Never mid-turn: http.py only calls this before a turn.
    """
    if mode not in (RETURN_NEW_MESSAGE, RETURN_AFTER_RESET) or state is None or not state.fell_back:
        return None
    now = book.clock()
    if state.promoted_at and now - state.promoted_at < PROMOTION_LOCK_SECONDS:
        return None
    above = chain[: chain.index(state.active)] if state.active in chain else list(chain)
    for agent in capable(above, needs, caps_of):
        if not book.may_probe(agent, mode, now):
            continue
        failure = await probe(agent)
        if failure is None:
            book.mark_ok(agent)
            return agent
        book.mark_failed(agent, failure, probe=True)
    return None


async def wait_for_agent(
    chain: list[str],
    *,
    needs: Iterable[str],
    caps_of: Callable[[str], Iterable[str]],
    book: FallbackBook,
    probe: Probe,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    on_wait: Callable[[float], Awaitable[Any]] | None = None,
    give_up: float = PAUSE_GIVE_UP_SECONDS,
) -> str | None:
    """Pause until an agent that can do the task is back (checked cheaply, from the top).

    None when no agent in the list can do it at all, or after ``give_up`` seconds.
    """
    pool = capable(chain, needs, caps_of)
    if not pool:
        return None
    started = book.clock()
    while True:
        now = book.clock()
        for agent in pool:
            if book.until(agent) > now:
                continue
            failure = await probe(agent)
            if failure is None:
                book.mark_ok(agent)
                return agent
            book.mark_failed(agent, failure, probe=True)
        now = book.clock()
        if now - started >= give_up:
            return None
        wake = min(book.until(agent) for agent in pool)
        delay = max(PAUSE_MIN_SECONDS, min(PAUSE_MAX_SECONDS, wake - now))
        if on_wait is not None:
            await on_wait(wake)
        await sleep(delay)


# --- Journal and handoff ----------------------------------------------------------------------

_JOURNAL_ENTRIES = 60
_ENTRY_CHARS = 400
_TASK_CHARS = 20000
_PARTIAL_CHARS = 4000


def _clip(text: object, limit: int) -> str:
    raw = " ".join(str(text or "").split()) if limit <= _ENTRY_CHARS else str(text or "").strip()
    return raw if len(raw) <= limit else raw[: limit - 1].rstrip() + "…"


def _summary(value: object) -> str:
    if value in (None, "", {}, []):
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


@dataclass
class JournalEntry:
    agent: str
    name: str
    call_id: str = ""
    args: str = ""
    result: str = ""
    finished: bool = False
    failed: bool = False


@dataclass
class TurnJournal:
    """Tool calls one chat turn (or job) made, across every agent that worked on it."""

    entries: list[JournalEntry] = field(default_factory=list)

    def note(self, event: Mapping[str, Any], agent: str) -> None:
        if event.get("type") != "tool":
            return
        name = str(event.get("name") or "tool")
        phase = str(event.get("phase") or "")
        call_id = str(event.get("id") or "")
        detail = _summary(event.get("detail"))
        if phase == "start" or not phase:
            self.entries.append(JournalEntry(agent, name, call_id, _clip(detail or event.get("text"), _ENTRY_CHARS)))
            if phase:
                return
        entry = self._open(call_id, name, agent)
        if entry is None:
            entry = JournalEntry(agent, name, call_id)
            self.entries.append(entry)
        text = str(event.get("text") or "")
        entry.finished = phase == "end" or not phase
        entry.failed = bool(event.get("failed")) or bool(re.search(r"\bfailed\b", text, re.IGNORECASE))
        entry.result = _clip(event.get("note") or detail or text, _ENTRY_CHARS)
        if name and name != "tool" and entry.name == "tool":
            entry.name = name

    def _open(self, call_id: str, name: str, agent: str) -> JournalEntry | None:
        for entry in reversed(self.entries):
            if entry.finished or entry.agent != agent:
                continue
            if call_id and entry.call_id == call_id:
                return entry
        if call_id:
            return None
        for entry in reversed(self.entries):
            if not entry.finished and entry.agent == agent and (name in {"", "tool"} or entry.name == name):
                return entry
        return None

    def needs_workspace(self) -> bool:
        return any(is_workspace_tool(entry.name) for entry in self.entries)

    def lines(self) -> list[str]:
        rows = self.entries[-_JOURNAL_ENTRIES:]
        out: list[str] = []
        skipped = len(self.entries) - len(rows)
        if skipped:
            out.append(f"(… {skipped} earlier calls not shown)")
        for number, entry in enumerate(rows, start=skipped + 1):
            if not entry.finished:
                state = "STARTED, RESULT UNKNOWN (it may or may not have happened; check before redoing)"
            elif entry.failed:
                state = "failed"
            else:
                state = "done"
            effect = " [changes something]" if has_side_effect(entry.name) else ""
            bits = [f"{number}. [{entry.agent}] {entry.name}{effect} — {state}"]
            if entry.args:
                bits.append(f"   call: {entry.args}")
            if entry.result:
                bits.append(f"   result: {entry.result}")
            out.append("\n".join(bits))
        return out


_REASON_EN = {
    KIND_LIMIT: "hit its plan or rate limit",
    KIND_AUTH: "lost its sign-in",
    KIND_TIMEOUT: "did not answer in time",
    KIND_CONNECTION: "could not be reached",
    KIND_OVERLOADED: "was overloaded",
}


def handoff_prompt(
    task: str,
    journal: TurnJournal,
    *,
    failed_agent: str,
    reason: str,
    partial: str = "",
) -> str:
    """The message the next agent gets instead of the original one."""
    lines = journal.lines()
    done = "\n".join(lines) if lines else "(no tool calls yet)"
    said = _clip(partial, _PARTIAL_CHARS)
    parts = [
        "[Agent handoff] You are taking over a task that another agent started in this same turn. "
        f"The agent {failed_agent} {_REASON_EN.get(reason, 'stopped')} and could not finish. "
        "Its session does not carry over, so everything that already happened is listed below.",
        f"Original task from the user:\n<<<\n{_clip(task, _TASK_CHARS)}\n>>>",
        f"Journal of tool calls already executed in this turn (oldest first):\n{done}",
    ]
    if said:
        parts.append(f"Reply text the user has already seen:\n<<<\n{said}\n>>>")
    parts.append(
        "Rules for taking over:\n"
        "- Do NOT repeat side-effecting steps that are listed as done: device actions and service calls, "
        "automation or dashboard changes, file writes and edits, shell commands that change state, git "
        "commits, pushes, sent messages or notifications. They already happened.\n"
        "- A step marked STARTED, RESULT UNKNOWN may have happened: check the current state with a "
        "read-only tool before you do it again.\n"
        "- Read-only checks are fine whenever you need the current state.\n"
        "- Continue from where the previous agent stopped and finish the task. Do not start over, and do "
        "not repeat reply text the user has already seen; just continue it."
    )
    return "\n\n".join(parts)
