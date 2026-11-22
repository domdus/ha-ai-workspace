"""Questions to the user from MCP tools, shown in the chat as cards: Allow / Deny.

Sources:

- MCP elicitation (``elicitation/create``) through the AI Workspace Runtime: a server asks the
  user while a tool call is open. The Runtime's MCP proxy keeps the request away from the agent
  and sends it here.
- agent-worker jobs that wait for an approval (status ``input_required``) with no open request.
  The Runtime sees them in job results; the answer goes to the worker's ``/jobs/<id>/approve``.
- MCP elicitation of cloud agents (OpenAI, Claude API, Gemini, Ollama, ...), whose MCP client is
  this integration's own (mcp_client.py): ``ask`` opens the card and waits here for the click.

Cards are stored per chat, so a closed panel or the companion app shows them again. Only a click
by the chat's own user answers one; the agent cannot, and chat text never does. The Runtime only
takes an answer with the card's key, which it gave to Home Assistant alone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any

from aiohttp import ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .callback_keys import caller as callback_caller
from .const import DOMAIN
from .elicitation_form import ACTIONS, card_of, check_answer
from .live_turn import live_turn

logger = logging.getLogger(__name__)

EVENT_TYPE = "approval"
BUS_EVENT = f"{DOMAIN}_approval"
KINDS = ("elicitation", "worker")
# Runtime close reasons -> stored status.
_CLOSED = {
    "accept": "accept",
    "decline": "decline",
    "cancel": "cancel",
    "timeout": "timeout",
    "ended": "ended",
    "resolved": "resolved",
}
_MAX_SECONDS = 24 * 3600
_WORKER_KEYS = ("job_id", "tool", "host", "hostname", "user", "command", "workspace")
# Answer key of a card that a cloud agent's call waits for here, not in the Runtime.
LOCAL_KEY = "local:"
_LOCAL = f"{DOMAIN}_local_elicitations"
_URL_CHARS = 2000


def _data(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data[DOMAIN]


def _short(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def card_from_runtime(body: dict[str, Any]) -> dict[str, Any] | None:
    """The card to store for a Runtime "open" callback, or None when it is not one."""
    kind = str(body.get("kind") or "").strip()
    item_id = _short(body.get("id"), 40)
    if kind not in KINDS or not item_id or not str(body.get("key") or "").strip():
        return None
    if kind == "elicitation":
        card = card_of({"message": body.get("message"), "requestedSchema": body.get("schema")})
        worker: dict[str, str] = {}
    else:
        raw = body.get("worker") if isinstance(body.get("worker"), dict) else {}
        worker = {key: _short(raw.get(key), 4000 if key == "command" else 255) for key in _WORKER_KEYS}
        if not worker["host"] or not worker["job_id"]:
            return None
        card = card_of({"message": body.get("message")})
        card["fields"], card["schema"], card["confirmation"], card["approval_field"] = [], {}, True, ""
    card["server"] = _short(body.get("server") or "MCP", 120)
    if worker:
        card["worker"] = worker
    try:
        timeout = int(float(body.get("timeout") or 0))
    except (TypeError, ValueError):
        timeout = 0
    card["timeout"] = max(0, min(timeout, _MAX_SECONDS))
    return card


def public(row: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """A stored card for the chat page: never the answer key."""
    try:
        card = json.loads(row.get("card") or "{}")
    except json.JSONDecodeError:
        card = {}
    stamp = time.time() if now is None else now
    expires = float(row.get("expires_at") or 0)
    return {
        **(card if isinstance(card, dict) else {}),
        "id": row["id"],
        "kind": row.get("kind") or "elicitation",
        "session_id": row.get("session_id") or "",
        "status": row.get("status") or "pending",
        "created_at": row.get("created_at") or "",
        "expires_at": expires,
        "expires_in": max(0, int(expires - stamp)) if expires else 0,
    }


def open_cards(store, session_id: str, now: float | None = None) -> list[dict[str, Any]]:
    """Open cards of one chat; overdue ones are marked timed out first. Executor job."""
    stamp = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    for row in store.list_approvals(session_id):
        expires = float(row.get("expires_at") or 0)
        if expires and expires <= stamp:
            store.close_approval(row["id"], "timeout")
            continue
        out.append(public(row, stamp))
    return out


def publish(hass: HomeAssistant, session_id: str, card: dict[str, Any]) -> None:
    """Show a new or closed card on every page that follows this chat's running reply."""
    event = {"type": EVENT_TYPE, "approval": card}
    turn = live_turn(hass, session_id)
    if turn is None:
        return
    turn.publish(event)
    direct = getattr(turn, "direct", None)
    if callable(direct):
        hass.async_create_task(direct(event))


def _hass(request: web.Request) -> HomeAssistant:
    try:
        from homeassistant.components.http import KEY_HASS
    except ImportError:  # pragma: no cover - older Home Assistant
        KEY_HASS = "hass"
    app = request.app
    return app[KEY_HASS] if KEY_HASS in app else app["hass"]


def _caller(request: web.Request):
    hass = _hass(request)
    found = callback_caller(hass, request.headers.get("Authorization"))
    if found is None:
        raise web.HTTPUnauthorized()
    return hass, found


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Invalid JSON.") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Invalid JSON.")
    return body


async def _announce(hass: HomeAssistant, store, item_id: str, user_id: str, session_id: str) -> dict[str, Any]:
    """Show a newly stored card in the chat and tell automations (event ai_workspace_approval)."""
    row = await hass.async_add_executor_job(store.get_approval, item_id)
    shown = public(row)
    publish(hass, session_id, shown)
    hass.bus.async_fire(
        BUS_EVENT,
        {
            "id": item_id,
            "user_id": user_id,
            "session_id": session_id,
            "kind": shown["kind"],
            "server": shown.get("server") or "",
            "message": str(shown.get("message") or "")[:300],
        },
    )
    logger.info("approval card %s (%s) for chat %s", item_id, shown["kind"], session_id)
    return shown


def link_of(value: Any) -> str:
    """An http(s) link of a URL-mode elicitation, or "" for anything else."""
    url = str(value or "").strip()
    if len(url) > _URL_CHARS or any(ch.isspace() for ch in url):
        return ""
    return url if url.lower().startswith(("https://", "http://")) else ""


def local_card(params: Any, server: str, timeout: int) -> dict[str, Any] | None:
    """The card for an elicitation/create of a cloud agent's call; None when it cannot be shown."""
    params = params if isinstance(params, dict) else {}
    if str(params.get("mode") or "form") == "url":
        url = link_of(params.get("url"))
        if not url:
            return None
        card = card_of({"message": params.get("message")})
        # Allow means: the user agrees to open the link (MCP 2025-11-25 URL mode).
        card.update({"fields": [], "schema": {}, "confirmation": True, "approval_field": "", "mode": "url", "url": url})
    else:
        card = card_of(params)
    card["server"] = _short(server or "MCP", 120)
    card["timeout"] = max(0, min(int(timeout), _MAX_SECONDS))
    return card


async def ask(
    hass: HomeAssistant,
    *,
    session_id: str,
    user_id: str,
    server: str,
    params: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    """Ask the chat's user an elicitation of a cloud agent's MCP call; the result for the server.

    Waits for the click on the card. No answer within timeout: cancel. The call is stopped
    meanwhile: the card closes as ended and the cancellation goes on to the MCP client.
    """
    store = _data(hass).get("store")
    if store is None or not session_id or not user_id:
        return {"action": "cancel"}
    seconds = max(1, min(int(timeout or 600), _MAX_SECONDS))
    card = local_card(params, server, seconds)
    if card is None:
        logger.warning("MCP elicitation from %s refused: not a form and no http(s) link", server)
        return {"action": "decline"}
    item_id = f"c{secrets.token_hex(10)}"
    waiting: dict[str, asyncio.Future] = hass.data.setdefault(_LOCAL, {})
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    waiting[item_id] = future
    status = "cancel"
    try:
        await hass.async_add_executor_job(
            store.save_approval,
            item_id,
            session_id,
            user_id,
            "elicitation",
            json.dumps(card, ensure_ascii=False),
            f"{LOCAL_KEY}{secrets.token_hex(16)}",
            time.time() + seconds,
        )
        await _announce(hass, store, item_id, user_id, session_id)
        try:
            result = await asyncio.wait_for(future, seconds)
        except TimeoutError:
            status = "timeout"
            logger.info("approval %s: no answer within %s s", item_id, seconds)
            return {"action": "cancel"}
        except asyncio.CancelledError:
            status = "ended"
            raise
        status = ""
        return result
    finally:
        waiting.pop(item_id, None)
        if status and await hass.async_add_executor_job(store.close_approval, item_id, status):
            publish(hass, session_id, {"id": item_id, "status": status, "session_id": session_id})


def answer_local(hass: HomeAssistant, item_id: str, card: dict[str, Any], result: dict[str, Any]) -> str:
    """Hand a click to the call that waits for it: "answered", or "gone" when none waits any more."""
    future = hass.data.get(_LOCAL, {}).get(item_id)
    if future is None or future.done():
        return "gone"
    answer = {"action": result["action"]}
    if result["action"] == "accept" and card.get("mode") != "url":
        answer["content"] = dict(result.get("content") or {})
    future.set_result(answer)
    return "answered"


class ApprovalCallbackView(HomeAssistantView):
    """Runtime callback: a card opens (a server asks the user) or closes (answered, timed out)."""

    url = "/api/ai_workspace/approval"
    name = "api:ai_workspace:approval"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        hass, who = _caller(request)
        body = await _body(request)
        store = _data(hass)["store"]
        event = str(body.get("event") or "")
        item_id = _short(body.get("id"), 40)
        if event == "open":
            card = card_from_runtime(body)
            if card is None:
                raise web.HTTPBadRequest(text="Not a card.")
            try:
                left = float(body.get("expires_in") or card.get("timeout") or 0)
            except (TypeError, ValueError):
                left = 0
            expires = time.time() + max(1.0, min(left or 600.0, float(_MAX_SECONDS)))
            # The chat and user come from the key Home Assistant issued, never from the body.
            fresh = await hass.async_add_executor_job(
                store.save_approval,
                item_id,
                who.session_id,
                who.user_id,
                str(body.get("kind")),
                json.dumps(card, ensure_ascii=False),
                str(body.get("key")),
                expires,
            )
            if fresh:
                await _announce(hass, store, item_id, who.user_id, who.session_id)
            return self.json({"ok": True, "new": fresh})
        if event == "close":
            row = await hass.async_add_executor_job(store.get_approval, item_id)
            if row is None or row.get("session_id") != who.session_id or row.get("user_id") != who.user_id:
                return self.json({"ok": False})
            status = _CLOSED.get(str(body.get("reason") or ""), "cancel")
            if await hass.async_add_executor_job(store.close_approval, item_id, status):
                publish(hass, who.session_id, {"id": item_id, "status": status, "session_id": who.session_id})
            return self.json({"ok": True})
        raise web.HTTPBadRequest(text="Unknown event.")


def _user_id(request: web.Request) -> str:
    user = request.get("hass_user")
    if user is None:
        raise web.HTTPUnauthorized()
    return str(user.id)


class SessionApprovalsView(HomeAssistantView):
    """Open cards of one chat, for a page that opens it (again)."""

    url = "/api/ai_workspace/sessions/{session_id}/approvals"
    name = "api:ai_workspace:session:approvals"
    requires_auth = True

    async def get(self, request: web.Request, session_id: str) -> web.Response:
        hass = _hass(request)
        store = _data(hass)["store"]
        user_id = _user_id(request)
        session = await hass.async_add_executor_job(store.get_session, user_id, session_id)
        if session is None:
            raise web.HTTPNotFound()
        return self.json(await hass.async_add_executor_job(open_cards, store, session.id))


async def answer_runtime(hass: HomeAssistant, user_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Hand the user's answer to the Runtime. {"status": "failed"} when it cannot be reached."""
    from .http import _runtime_headers_for

    base = str((_data(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        return {"status": "failed"}
    try:
        resp = await async_get_clientsession(hass).post(
            f"{base}/api/elicitations/{item_id}",
            json=payload,
            headers=_runtime_headers_for(hass, user_id),
            timeout=ClientTimeout(total=45),
        )
    except Exception:  # noqa: BLE001 - shown to the user as "could not send"
        logger.warning("approval %s did not reach the Runtime", item_id, exc_info=False)
        return {"status": "failed"}
    try:
        if resp.status == 404:
            # A Runtime older than 1.6.0b15 has no such endpoint; the request is gone either way.
            return {"status": "gone"}
        if resp.status >= 400:
            logger.warning("Runtime refused approval %s: HTTP %s", item_id, resp.status)
            return {"status": "failed"}
        body = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        return {"status": "failed"}
    finally:
        resp.release()
    return body if isinstance(body, dict) else {"status": "failed"}


class ApprovalAnswerView(HomeAssistantView):
    """The user's click on a card: accept (with the form's values), decline or cancel."""

    url = "/api/ai_workspace/approvals/{item_id}"
    name = "api:ai_workspace:approval:answer"
    requires_auth = True

    async def post(self, request: web.Request, item_id: str) -> web.Response:
        hass = _hass(request)
        store = _data(hass)["store"]
        user_id = _user_id(request)
        body = await _body(request)
        row = await hass.async_add_executor_job(store.get_approval, item_id)
        # Only the user whose chat asked; anyone else learns nothing about the card.
        if row is None or row.get("user_id") != user_id:
            raise web.HTTPNotFound()
        session = await hass.async_add_executor_job(store.get_session, user_id, row.get("session_id") or "")
        if session is None:
            raise web.HTTPNotFound()
        if row.get("status") != "pending":
            return self.json({"status": "closed", "approval": public(row)})
        if float(row.get("expires_at") or 0) <= time.time():
            await hass.async_add_executor_job(store.close_approval, item_id, "timeout")
            publish(hass, session.id, {"id": item_id, "status": "timeout", "session_id": session.id})
            return self.json({"status": "expired", "approval": {"id": item_id, "status": "timeout"}})
        action = str(body.get("action") or "").strip().lower()
        if action not in ACTIONS:
            raise web.HTTPBadRequest(text="Unknown action.")
        card = public(row)
        result, errors = check_answer(card.get("schema"), action, body.get("content"))
        if result is None:
            return self.json({"status": "invalid", "errors": errors}, status_code=400)
        key = str(row.get("answer_key") or "")
        if key.startswith(LOCAL_KEY):
            # A cloud agent's MCP call waits for this answer in Home Assistant itself.
            answer: dict[str, Any] = {"status": answer_local(hass, item_id, card, result)}
        else:
            answer = await answer_runtime(
                hass,
                user_id,
                item_id,
                {"key": key, "action": result["action"], "content": result.get("content")},
            )
        status = str(answer.get("status") or "failed")
        if status == "invalid":
            return self.json({"status": "invalid", "errors": answer.get("errors") or {}}, status_code=400)
        if status == "failed":
            # The card stays open: the user can try again.
            return self.json({"status": "failed"}, status_code=502)
        closed = {"answered": result["action"], "gone": "gone", "expired": "timeout"}.get(status, "gone")
        await hass.async_add_executor_job(store.close_approval, item_id, closed)
        shown = {"id": item_id, "status": closed, "session_id": session.id}
        publish(hass, session.id, shown)
        logger.info("approval %s answered by the user: %s", item_id, closed)
        return self.json({"status": status, "approval": shown})


def register_approval_views(hass: HomeAssistant) -> None:
    hass.http.register_view(ApprovalCallbackView)
    hass.http.register_view(SessionApprovalsView)
    hass.http.register_view(ApprovalAnswerView)
