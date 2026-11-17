"""MCP elicitation for chat agents: the user answers in the Home Assistant chat, never the model.

Every MCP call of a Cursor or Claude SDK chat goes through the Runtime's MCP proxy (app.mcp_proxy).
The proxy says the client can elicit (``initialize`` gets ``capabilities.elicitation``), and when a
server asks the user something (``elicitation/create`` on the answer stream of a call), the proxy
keeps that request away from the agent. It goes to Home Assistant instead, which shows it in the chat
as a card. Only a click on that card answers it: Home Assistant sends the answer with a key that only
it got. After the timeout the server gets ``cancel``.

agent-worker jobs that wait for an approval with no open request (status ``input_required`` in a job
result) get the same card; the click goes to the worker's ``POST /jobs/<id>/approve``.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from app.elicitation_form import card_of, check_answer
from app.worker_usage import bare_tool_name

logger = logging.getLogger(__name__)

ELICIT_METHOD = "elicitation/create"
DEFAULT_TIMEOUT = 600
MIN_TIMEOUT = 30
MAX_TIMEOUT = 3600
# A worker job waits for its approval for APPROVAL_TIMEOUT_SECONDS (agent-worker default 30 minutes).
WORKER_CARD_SECONDS = 1800
_MAX_ITEMS = 256
# Tools whose results carry agent-worker jobs (agent_jobs: a list of them).
_JOB_TOOLS = frozenset({"agent_run", "agent_job", "agent_jobs", "agent_approve", "agent_cancel"})
_WAITING = frozenset({"input_required", "needs_approval"})


def clamp_timeout(value: Any) -> int:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if seconds <= 0:
        return DEFAULT_TIMEOUT
    return max(MIN_TIMEOUT, min(seconds, MAX_TIMEOUT))


# --- JSON-RPC helpers ---------------------------------------------------------------------------


def _messages(raw: bytes | str) -> tuple[list[Any], bool] | None:
    """The messages of one JSON-RPC body (and whether it was a batch), or None."""
    try:
        payload = json.loads(raw or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(payload, list):
        return payload, True
    return [payload], False


def with_elicitation_capability(body: bytes) -> bytes | None:
    """The same body with ``capabilities.elicitation`` on its initialize request; None if unchanged."""
    found = _messages((body or b"").strip())
    if found is None:
        return None
    messages, batch = found
    changed = False
    for message in messages:
        if not isinstance(message, dict) or message.get("method") != "initialize":
            continue
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        caps = params.get("capabilities") if isinstance(params.get("capabilities"), dict) else {}
        if isinstance(caps.get("elicitation"), dict):
            continue
        # {} is form mode (2025-06-18; 2025-11-25 reads it the same). URL mode is not offered.
        message["params"] = {**params, "capabilities": {**caps, "elicitation": {}}}
        changed = True
    if not changed:
        return None
    return json.dumps(messages if batch else messages[0], ensure_ascii=False).encode()


def is_server_request(message: Any) -> bool:
    return (
        isinstance(message, dict)
        and isinstance(message.get("method"), str)
        and message.get("id") is not None
        and "result" not in message
        and "error" not in message
    )


def forged_answer(body: bytes, intercepted: set[str]) -> bool:
    """True when a client body answers an elicitation: only the user may, through Home Assistant.

    The agent never sees those requests, but it must not guess their ids either.
    """
    found = _messages((body or b"").strip())
    if found is None:
        return False
    for message in found[0]:
        if not isinstance(message, dict) or "method" in message:
            continue
        if "result" not in message and "error" not in message:
            continue
        if json.dumps(message.get("id")) in intercepted:
            return True
        result = message.get("result")
        if isinstance(result, dict) and str(result.get("action") or "") in {"accept", "decline", "cancel"}:
            return True
    return False


# --- Home Assistant callbacks --------------------------------------------------------------------


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 15) -> tuple[int, bytes]:
    sent = {"Content-Type": "application/json", "Accept": "application/json", **headers}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=sent, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass
class Target:
    """Where a card goes: Home Assistant's callback URL and this chat's callback key."""

    base: str
    key: str

    def send(self, payload: dict[str, Any]) -> bool:
        if not self.base or not self.key:
            return False
        try:
            status, _raw = _post_json(
                f"{self.base}/api/ai_workspace/approval", payload, {"Authorization": f"Bearer {self.key}"}
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            logger.warning("approval card did not reach Home Assistant", exc_info=False)
            return False
        if status >= 400:
            logger.warning("approval card refused by Home Assistant: HTTP %s", status)
            return False
        return True


# --- Pending requests ----------------------------------------------------------------------------


@dataclass
class Pending:
    id: str
    key: str
    kind: str  # elicitation | worker
    session_id: str
    server: str
    card: dict[str, Any]
    timeout: int
    target: Target
    created: float = field(default_factory=time.monotonic)
    future: concurrent.futures.Future = field(default_factory=concurrent.futures.Future)
    worker: dict[str, Any] = field(default_factory=dict)
    # Worker endpoint and its headers (the worker token); never sent to Home Assistant.
    worker_url: str = ""
    worker_headers: dict[str, str] = field(default_factory=dict, repr=False)
    status: str = "pending"

    def public(self) -> dict[str, Any]:
        left = max(0, int(self.timeout - (time.monotonic() - self.created)))
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "server": self.server,
            "expires_in": left,
            "timeout": self.timeout,
            **self.card,
        }
        if self.worker:
            out["worker"] = dict(self.worker)
        return out


def worker_base(url: str) -> str:
    """http://worker:8080/mcp -> http://worker:8080 (the worker's HTTP API sits next to /mcp)."""
    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")]
    elif "/" in path:
        path = path.rsplit("/", 1)[0]
    return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


def _worker_card(job: dict[str, Any], approval: dict[str, Any]) -> dict[str, Any]:
    def text(key: str, limit: int = 4000) -> str:
        return str(approval.get(key) or "").strip()[:limit]

    return {
        "job_id": str(job.get("job_id") or job.get("id") or "").strip()[:80],
        "tool": text("tool", 20) or "ssh",
        "host": text("host", 255),
        "hostname": text("hostname", 255),
        "user": text("user", 255),
        "command": text("command"),
        "workspace": str(job.get("workspace") or "").strip()[:120],
    }


def _job_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("jobs"), list):
        return [item for item in value["jobs"] if isinstance(item, dict)]
    if isinstance(value.get("cancelled"), list):
        return [item for item in value["cancelled"] if isinstance(item, dict)]
    if "job_id" in value or "status" in value:
        return [value]
    if isinstance(value.get("result"), dict):
        return _job_dicts(value["result"])
    return []


def worker_jobs(tool: str, raw: bytes | str) -> list[dict[str, Any]]:
    """agent-worker jobs in a raw tools/call answer (JSON or event stream)."""
    if bare_tool_name(tool) not in _JOB_TOOLS:
        return []
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    chunks = [text.strip()] if text.strip()[:1] in {"{", "["} else [
        line.strip()[5:].strip() for line in text.splitlines() if line.strip().startswith("data:")
    ]
    jobs: list[dict[str, Any]] = []
    for chunk in chunks:
        found = _messages(chunk)
        if found is None:
            continue
        for message in found[0]:
            result = message.get("result") if isinstance(message, dict) else None
            if not isinstance(result, dict):
                continue
            structured = result.get("structuredContent")
            got = _job_dicts(structured) if isinstance(structured, dict) else []
            if not got:
                for block in result.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        try:
                            got = _job_dicts(json.loads(block.get("text") or ""))
                        except (json.JSONDecodeError, TypeError):
                            got = []
                        if got:
                            break
            jobs.extend(got)
    return jobs


def _waiting_approval(job: dict[str, Any]) -> dict[str, Any] | None:
    status = str(job.get("status") or "").strip().lower()
    legacy = str(job.get("legacy_status") or "").strip().lower()
    approval = job.get("approval")
    if (status in _WAITING or legacy in _WAITING) and isinstance(approval, dict) and approval.get("host"):
        return approval
    return None


class ElicitationBroker:
    """Open questions to the user, by id. Thread-safe: the proxy waits in its forward threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: OrderedDict[str, Pending] = OrderedDict()
        # JSON-RPC ids (json.dumps) of server requests the proxy answered, per upstream.
        self.intercepted: dict[str, set[str]] = {}

    # Book-keeping ---------------------------------------------------------------------------

    def _add(self, item: Pending) -> None:
        with self._lock:
            self.items[item.id] = item
            self.items.move_to_end(item.id)
            while len(self.items) > _MAX_ITEMS:
                old_id, old = self.items.popitem(last=False)
                if not old.future.done():
                    old.future.set_result({"action": "cancel"})

    def get(self, item_id: str) -> Pending | None:
        with self._lock:
            return self.items.get(str(item_id or ""))

    def pending(self, session_id: str = "") -> list[Pending]:
        with self._lock:
            return [
                item
                for item in self.items.values()
                if item.status == "pending" and (not session_id or item.session_id == session_id)
            ]

    def note_intercepted(self, upstream: str, request_id: Any) -> None:
        with self._lock:
            seen = self.intercepted.setdefault(upstream, set())
            seen.add(json.dumps(request_id))
            if len(seen) > 512:
                seen.clear()

    def was_intercepted(self, upstream: str) -> set[str]:
        with self._lock:
            return set(self.intercepted.get(upstream, set()))

    def _close(self, item: Pending, reason: str, notify: bool = True) -> None:
        with self._lock:
            if item.status != "pending":
                return
            item.status = reason
        if notify:
            item.target.send({"event": "close", "id": item.id, "reason": reason})

    # MCP elicitation --------------------------------------------------------------------------

    def ask(
        self,
        message: dict[str, Any],
        *,
        session_id: str,
        server: str,
        target: Target,
        timeout: int = DEFAULT_TIMEOUT,
        upstream: str = "",
    ) -> dict[str, Any]:
        """The JSON-RPC answer to one server request. Blocks until the user answers or the timeout.

        Runs in a proxy forward thread.
        """
        request_id = message.get("id")
        if upstream:
            self.note_intercepted(upstream, request_id)
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if str(params.get("mode") or "form") != "form":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "This client supports form elicitation only."},
            }
        if not session_id or not target.base or not target.key:
            # Nobody can see a card (no chat behind this call): the server hears "dismissed".
            logger.info("elicitation from %s cancelled: no chat to ask in", server or "MCP server")
            return {"jsonrpc": "2.0", "id": request_id, "result": {"action": "cancel"}}
        timeout = clamp_timeout(timeout)
        item = Pending(
            id=secrets.token_hex(8),
            key=secrets.token_urlsafe(24),
            kind="elicitation",
            session_id=session_id,
            server=server,
            card=card_of(params),
            timeout=timeout,
            target=target,
        )
        self._add(item)
        if not target.send({"event": "open", "key": item.key, "session_id": session_id, **item.public()}):
            self._close(item, "cancel", notify=False)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"action": "cancel"}}
        logger.info("elicitation %s from %s waits for the user (session=%s)", item.id, server, session_id)
        try:
            result = item.future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.info("elicitation %s: no answer in %ss, cancelled", item.id, timeout)
            self._close(item, "timeout")
            result = {"action": "cancel"}
        else:
            self._close(item, str(result.get("action") or "cancel"))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def end_session(self, session_id: str) -> None:
        """The chat turn ended (stopped, failed): its open MCP questions are cancelled."""
        for item in self.pending(session_id):
            if item.kind != "elicitation":
                continue
            if not item.future.done():
                item.future.set_result({"action": "cancel"})
            self._close(item, "ended")

    # agent-worker fallback --------------------------------------------------------------------

    def note_worker_jobs(
        self,
        jobs: list[dict[str, Any]],
        *,
        session_id: str,
        server: str,
        upstream_url: str,
        upstream_headers: dict[str, str],
        target: Target,
    ) -> list[Pending]:
        """Cards for worker jobs waiting for an approval; close cards of jobs that moved on."""
        opened: list[Pending] = []
        base = worker_base(upstream_url)
        for job in jobs:
            job_id = str(job.get("job_id") or job.get("id") or "").strip()
            if not job_id:
                continue
            approval = _waiting_approval(job)
            if approval is None:
                for item in self.pending():
                    if item.kind == "worker" and item.worker.get("job_id") == job_id and item.worker_url.startswith(base):
                        self._close(item, "resolved")
                continue
            if not session_id or not target.base or not target.key or not base:
                continue
            marker = approval.get("id") or approval.get("requested_at") or approval.get("command") or ""
            card_id = "w" + hashlib.sha256(f"{base}|{job_id}|{marker}".encode()).hexdigest()[:15]
            if self.get(card_id) is not None:
                continue
            worker = _worker_card(job, approval)
            target_text = f"{worker['user']}@{worker['host']}" if worker["user"] else worker["host"]
            item = Pending(
                id=card_id,
                key=secrets.token_urlsafe(24),
                kind="worker",
                session_id=session_id,
                server=server,
                card={
                    "message": f"{worker['tool']} {target_text}",
                    "schema": {},
                    "fields": [],
                    "approval_field": "",
                    "confirmation": True,
                },
                timeout=WORKER_CARD_SECONDS,
                target=target,
                worker=worker,
                worker_url=f"{base}/jobs/{job_id}/approve",
                worker_headers=dict(upstream_headers or {}),
            )
            self._add(item)
            if target.send({"event": "open", "key": item.key, "session_id": session_id, **item.public()}):
                logger.info("worker job %s waits for approval: card %s", job_id, card_id)
                opened.append(item)
            else:
                self._close(item, "cancel", notify=False)
        return opened

    # Answers from Home Assistant ----------------------------------------------------------------

    def answer(
        self,
        item_id: str,
        key: str,
        action: Any,
        content: Any = None,
        post: Callable[[str, dict[str, Any], dict[str, str]], tuple[int, bytes]] | None = None,
    ) -> dict[str, Any]:
        """Apply the user's click. Blocking for worker cards (an HTTP call), so run it in a thread."""
        item = self.get(item_id)
        if item is None or not hmac.compare_digest(str(key or ""), item.key):
            return {"status": "gone"}
        if item.status != "pending" or item.future.done():
            return {"status": "gone"}
        if item.created + item.timeout < time.monotonic():
            self._close(item, "timeout", notify=False)
            return {"status": "expired"}
        result, errors = check_answer(item.card.get("schema"), action, content)
        if result is None:
            return {"status": "invalid", "errors": errors}
        if item.kind == "elicitation":
            item.future.set_result(result)
            # Closed by ask() once the server has its answer; mark it here so a second click is "gone".
            with self._lock:
                item.status = result["action"]
            return {"status": "answered", "action": result["action"]}
        # Worker card: dismissing only hides it, the job keeps waiting until the worker's own timeout.
        if result["action"] == "cancel":
            item.future.set_result(result)
            self._close(item, "cancel", notify=False)
            return {"status": "answered", "action": "cancel"}
        allow = result["action"] == "accept"
        send = post or (lambda url, payload, headers: _post_json(url, payload, headers, timeout=30))
        try:
            status, _raw = send(item.worker_url, {"approve": allow, "note": ""}, dict(item.worker_headers))
        except (urllib.error.URLError, TimeoutError, OSError):
            logger.warning("worker approval for job %s did not reach the worker", item.worker.get("job_id"))
            return {"status": "failed"}
        if status in {404, 409}:
            self._close(item, "resolved", notify=False)
            return {"status": "gone"}
        if status >= 400:
            logger.warning("worker approval for job %s: HTTP %s", item.worker.get("job_id"), status)
            return {"status": "failed"}
        item.future.set_result(result)
        self._close(item, result["action"], notify=False)
        logger.info("worker job %s %s by the user", item.worker.get("job_id"), "approved" if allow else "denied")
        return {"status": "answered", "action": result["action"]}
