from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
from urllib.parse import urlparse
from typing import Any, AsyncIterator

from aiohttp import ClientSession, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .assist_agents import assist_agent_ids, async_assist_events, list_assist_agents
from .discovery import async_bind_runtime
from .const import (
    ACTIVITY_ROLLBACK,
    activity_restore_flags,
    CLOUD_ONLY_MODELS,
    standing_chat_prompt,
    DOMAIN,
    MCP_COOLVER,
    format_ui_page,
    ha_mcp_is_connected,
    parse_ui_page,
    ui_theme_of,
    provider_token_mode,
    token_mode_allows_extras,
    token_mode_allows_files,
)
from .mcp_config import with_mcp_auth
from .mcp_observe import last_mcp_result, note_mcp_result
from .mcp_resolve import ha_hosts, hass_mcp_server_url
from .chat_scope import handoff_note, merge_reply_text, other_chat_note
from .files import attach_files_to_message, file_events, parse_client_files
from .images import caption_for, image_events, parse_client_images

try:
    from homeassistant.components.http import KEY_HASS
except ImportError:
    KEY_HASS = "hass"
from .redact import redact
from .small_talk import wants_house_tools
from .store import Session, Store
from .titles import accept_generated_title, needs_title_summary, title_from_prompt
from .usage_record import dashboard_payload, finalize_usage, record_usage_turn

logger = logging.getLogger(__name__)


def _sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _session_dict(session: Session) -> dict:
    return {
        "id": session.id,
        "provider": session.provider,
        "title": session.title,
        "agent_id": session.agent_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "pinned": bool(getattr(session, "pinned", False)),
    }


def _message_dict(item) -> dict:
    try:
        events = json.loads(item.events)
    except json.JSONDecodeError:
        events = []
    return {
        "id": item.id,
        "role": item.role,
        "content": item.content,
        "events": events,
        "created_at": item.created_at,
    }


def _hass(request: web.Request) -> HomeAssistant:
    app = request.app
    if KEY_HASS in app:
        return app[KEY_HASS]
    return app["hass"]


def _runtime(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data[DOMAIN]


def _runtime_headers_for(hass: HomeAssistant, user_id: str, accept: str = "application/json") -> dict[str, str]:
    uid = str(user_id or "anonymous")
    headers = {
        "Accept": accept,
        "Content-Type": "application/json",
        "X-Remote-User-Id": uid,
        "X-Hass-User-Id": uid,
    }
    token = str((hass.data.get(DOMAIN) or {}).get("runtime_token") or "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _runtime_headers(request: web.Request) -> dict[str, str]:
    user = request["hass_user"]
    uid = str(user.id) if user else "anonymous"
    return _runtime_headers_for(_hass(request), uid, request.headers.get("Accept", "application/json"))


def _runtime_error(status: int, text: str) -> str:
    try:
        detail = json.loads(text).get("detail")
    except (json.JSONDecodeError, AttributeError):
        detail = None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:400]
    if status == 401:
        return "The Cursor SDK Runtime refused the token. Set the same Runtime token on both sides."
    if status == 404:
        return (
            "This chat exists in Home Assistant but the Cursor Runtime did not have a matching session "
            "(often after a container rebuild). The integration retried once; if this persists, check the "
            "Runtime URL and token on the Cursor agent."
        )
    return f"The Cursor SDK Runtime answered HTTP {status}."


async def _create_runtime_session(
    hass: HomeAssistant,
    user_id: str,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> str | None:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        return None
    http: ClientSession = async_get_clientsession(hass)
    payload: dict[str, str] = {"provider": "cursor"}
    if session_id:
        payload["id"] = session_id
    if agent_id:
        payload["agent_id"] = agent_id
    try:
        resp = await http.post(
            f"{base}/api/sessions",
            json=payload,
            headers=_runtime_headers_for(hass, user_id),
            timeout=ClientTimeout(total=10),
        )
        if resp.status >= 400:
            resp.release()
            return None
        body = await resp.json()
        resp.release()
    except Exception:
        logger.debug("runtime session create skipped", exc_info=True)
        return None
    return str((body or {}).get("id") or "") or None


async def _ensure_runtime_session(hass: HomeAssistant, user_id: str, session: Session) -> bool:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        return False
    http: ClientSession = async_get_clientsession(hass)
    agent_id = str(session.agent_id or "").strip() or None
    try:
        existing = await http.get(
            f"{base}/api/sessions/{session.id}",
            headers=_runtime_headers_for(hass, user_id),
            timeout=ClientTimeout(total=8),
        )
        status = existing.status
        existing.release()
        if status == 200:
            return True
    except Exception:
        logger.debug("runtime session lookup skipped", exc_info=True)
    for _ in range(2):
        created = await _create_runtime_session(hass, user_id, session.id, agent_id)
        if created:
            return True
    logger.warning("runtime session sync failed session=%s", session.id)
    return False


async def _iter_sse(resp) -> AsyncIterator[tuple[str, dict]]:
    buffer = ""
    async for chunk in resp.content.iter_any():
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            event = "message"
            data_lines: list[str] = []
            for line in raw.split("\n"):
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if not data_lines:
                continue
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            yield event, payload if isinstance(payload, dict) else {"type": event}


def _runtime_agent_overrides(
    hass: HomeAssistant, access_token: str | None = None, admin: bool = True
) -> dict[str, Any]:
    settings = _runtime(hass).get("settings")
    extra: dict[str, Any] = {}
    if settings is None:
        return extra
    if admin:
        servers = dict(getattr(settings, "mcp_servers", None) or {})
        if str(getattr(settings, "mcp_kind", "") or "") == MCP_COOLVER:
            servers.pop("mcp", None)
    elif "mcp_server" in hass.config.components:
        servers = {"mcp": {"type": "http", "url": hass_mcp_server_url(hass)}}
    else:
        servers = {}
    servers = with_mcp_auth(servers, access_token=str(access_token or ""), ha_hosts=ha_hosts(hass))
    if servers or not admin:
        extra["mcp"] = {"servers": servers, "exclusive": not admin}
    model = str(getattr(settings, "model", "") or "").strip()
    if model in CLOUD_ONLY_MODELS:
        model = ""
    if model:
        extra["model"] = model
    extra["shorten_mcp_results"] = bool(getattr(settings, "shorten_mcp_results", True))
    extra["change_history"] = bool(getattr(settings, "change_history", True))
    return extra


def _full_tools(user_id: str, admin: bool) -> bool:
    """Shell and file tools only for a signed-in administrator, never for a voice satellite."""
    return bool(admin) and bool(user_id) and user_id != "assist"


async def _runtime_chat(
    hass: HomeAssistant,
    user_id: str,
    session: Session,
    message: str,
    origin: str = "",
    images: list[dict] | None = None,
    files: list[dict] | None = None,
    language: str = "",
    headers: dict[str, str] | None = None,
    model: str = "",
    effort: str = "",
    api_key: str = "",
    access_token: str | None = None,
    handoff: str = "",
    question: str = "",
    admin: bool = True,
    agent: str = "",
) -> AsyncIterator[dict]:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        yield {"type": "error", "message": "Cursor Runtime is not configured."}
        return
    if not await _ensure_runtime_session(hass, user_id, session):
        yield {
            "type": "error",
            "message": (
                "Home Assistant could not sync this chat to the Cursor Runtime. "
                "Check the Runtime URL and token on the Cursor agent, then try again."
            ),
        }
        return
    http: ClientSession = async_get_clientsession(hass)
    settings = _runtime(hass).get("settings")
    standing = standing_chat_prompt(settings, admin=admin, language=language, origin=origin)
    user_text = attach_files_to_message(message, files or [])
    payload: dict[str, Any] = {
        "message": f"{standing}\n\n{user_text}" if standing else user_text,
        "question": (question or message).strip(),
        "origin": origin,
        "history_in_ha": True,
        "full_tools": _full_tools(user_id, admin),
    }
    if standing:
        payload["prompt"] = standing
    if session.agent_id:
        payload["sync_agent_id"] = str(session.agent_id)
    if images:
        payload["images"] = [
            {"name": item["name"], "mime": item["mime"], "data": item["data"]} for item in images
        ]
    token = str(access_token or "").strip()
    if not token:
        from .conversation import _login_token

        token = str(await _login_token(hass, user_id) or "").strip()
    payload.update(_runtime_agent_overrides(hass, access_token=token, admin=admin))
    if model:
        payload["model"] = model
    if effort:
        payload["effort"] = effort
    if api_key:
        payload["api_key"] = api_key
    if handoff:
        payload["handoff"] = handoff
    sent = {**(headers or _runtime_headers_for(hass, user_id)), "Accept": "text/event-stream"}
    if agent:
        sent["X-Ai-Workspace-Agent"] = agent
    resp = None
    for attempt in range(2):
        try:
            resp = await http.post(
                f"{base}/api/sessions/{session.id}/chat",
                json=payload,
                headers=sent,
                timeout=ClientTimeout(total=None, sock_read=600),
            )
        except Exception as exc:
            yield {"type": "error", "message": f"AI Workspace runtime is unreachable at {base}: {exc}"}
            return
        if resp.status != 404 or attempt:
            break
        resp.release()
        resp = None
        logger.info("runtime chat 404, resyncing session=%s", session.id)
        if not await _ensure_runtime_session(hass, user_id, session):
            yield {
                "type": "error",
                "message": _runtime_error(404, ""),
            }
            return
    if resp is None:
        yield {"type": "error", "message": _runtime_error(404, "")}
        return
    try:
        if resp.status >= 400:
            yield {"type": "error", "message": _runtime_error(resp.status, await resp.text())}
            return
        async for name, payload in _iter_sse(resp):
            event = dict(payload)
            event.setdefault("type", name)
            yield event
    finally:
        resp.release()


async def async_agent_events(
    hass: HomeAssistant,
    user_id: str,
    session: Session,
    provider: Any,
    message: str,
    *,
    language: str = "",
    origin: str = "",
    access_token: str | None = None,
    handoff: str = "",
    question: str = "",
    tools: bool | None = None,
    admin: bool = True,
    force_tools: bool = False,
) -> AsyncIterator[dict]:
    """Run one turn for Assist or any caller that is not an HTTP chat request."""
    store: Store = _runtime(hass)["store"]

    def on_agent_id(agent_id: str) -> None:
        if session.agent_id != agent_id:
            hass.async_add_executor_job(store.set_agent_id, session.id, agent_id)
        session.agent_id = agent_id

    if getattr(provider, "kind", "") == "cursor":
        async for event in _runtime_chat(
            hass,
            user_id,
            session,
            message,
            origin,
            language=language,
            model=str(getattr(provider, "model", "") or ""),
            effort=str(getattr(provider, "effort", "") or ""),
            api_key=str(getattr(provider, "api_key", "") or ""),
            access_token=access_token,
            handoff=handoff,
            question=question,
            admin=admin,
            agent=_agent_label(provider),
        ):
            yield event
        return
    if provider is None:
        yield {"type": "error", "message": "Add an agent under AI Workspace in Devices & services."}
        return
    async for event in provider.send(
        session,
        message,
        on_agent_id,
        access_token=access_token,
        frontend_origin=origin,
        language=language,
        tools=tools,
        admin=admin,
        force_tools=force_tools,
        **(await _activity_kwargs(hass, provider, user_id, session.id)),
    ):
        yield event


def _send_provider(data: dict[str, Any], session: Session):
    providers = data.get("providers") or {}
    ready = next((item for item in providers.values() if item.info.available), None)
    if ready is not None:
        return ready
    return providers.get(session.provider)


async def _cleanup_pruned_sessions(
    hass: HomeAssistant,
    session_ids: list[str],
    request: web.Request | None = None,
) -> None:
    if not session_ids:
        return
    data = hass.data.get(DOMAIN) or {}
    base = str((data.get("runtime_url") or "")).rstrip("/")
    if not base or request is None:
        return
    http: ClientSession = async_get_clientsession(hass)
    headers = _runtime_headers(request)
    for session_id in session_ids:
        try:
            await http.delete(
                f"{base}/api/sessions/{session_id}",
                headers=headers,
                timeout=ClientTimeout(total=5),
            )
        except Exception:
            logger.debug("runtime prune delete skipped", exc_info=True)


async def _prune_user_chats(
    hass: HomeAssistant,
    store: Store,
    user_id: str,
    request: web.Request | None = None,
) -> None:
    settings = (hass.data.get(DOMAIN) or {}).get("settings")
    keep = int(getattr(settings, "keep_chats", 30) or 30)
    deleted = await hass.async_add_executor_job(store.prune_sessions, user_id, keep)
    await _cleanup_pruned_sessions(hass, deleted, request)


async def _prune_all_chats(hass: HomeAssistant, store: Store, keep: int) -> None:
    user_ids = await hass.async_add_executor_job(store.list_user_ids)
    for user_id in user_ids:
        deleted = await hass.async_add_executor_job(store.prune_sessions, user_id, keep)
        await _cleanup_pruned_sessions(hass, deleted, None)


def _bearer(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _signed_in(request: web.Request):
    user = request.get("hass_user")
    if user is None:
        raise web.HTTPUnauthorized(text="Sign in through Home Assistant.")
    return user


def _allow_users(request: web.Request) -> bool:
    settings = _runtime(_hass(request)).get("settings")
    return bool(getattr(settings, "allow_users", False))


def _user_id(request: web.Request) -> str:
    user = _signed_in(request)
    if not getattr(user, "is_admin", False) and not _allow_users(request):
        raise web.HTTPForbidden(text="Administrator only.")
    return str(user.id)


def _clean_origin(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _frontend_origin(request: web.Request, body: dict) -> str:
    host = (request.headers.get("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
    proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    fallback = f"{proto}://{host}" if host else ""
    for raw in (body.get("origin"), request.headers.get("Origin"), fallback):
        origin = _clean_origin(str(raw or ""))
        if origin:
            return origin
    return ""


class UiView(HomeAssistantView):
    url = "/api/ai_workspace/ui"
    name = "api:ai_workspace:ui"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        user = _signed_in(request)
        settings = _runtime(_hass(request))["settings"]
        from .voice import overlay_tts_heavy

        return self.json(
            {
                "dictate": bool(settings.enable_dictate),
                "allowed": bool(getattr(user, "is_admin", False) or settings.allow_users),
                "stt": settings.stt_engine,
                "tts": settings.tts_engine,
                "speak": bool(settings.speak_replies),
                "tts_heavy": overlay_tts_heavy(_hass(request), settings.tts_engine),
                "tts_natural": bool(getattr(settings, "tts_natural", True)),
                "change_history": bool(getattr(settings, "change_history", True)),
                "track_usage": bool(getattr(settings, "track_usage", True)),
                "show_chat_usage": bool(getattr(settings, "show_chat_usage", True)),
                "ui_theme": ui_theme_of(getattr(settings, "ui_theme", "standard")),
            }
        )


class HealthView(HomeAssistantView):
    url = "/api/ai_workspace/health"
    name = "api:ai_workspace:health"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        _user_id(request)
        data = _runtime(_hass(request))
        settings = data["settings"]
        providers = (data.get("providers") or {}).values()
        return self.json(
            {
                "ok": True,
                "runtime": bool(data.get("runtime_url")),
                "cursor": any(getattr(item, "kind", "") == "cursor" and item.info.available for item in providers),
                "overlay": settings.enable_overlay,
                "dictate": settings.enable_dictate,
            }
        )


class ProvidersView(HomeAssistantView):
    url = "/api/ai_workspace/providers"
    name = "api:ai_workspace:providers"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        _user_id(request)
        hass = _hass(request)
        data = _runtime(hass)
        if any(
            getattr(item, "kind", "") == "cursor" and not item.info.available
            for item in (data.get("providers") or {}).values()
        ):
            await async_bind_runtime(hass, data, force=True)
        rows = []
        for item in data["providers"].values():
            row = item.info.as_dict()
            row["kind"] = getattr(item, "kind", "api")
            rows.append(row)
        rows.extend(list_assist_agents(hass))
        return self.json(rows)


class SessionsView(HomeAssistantView):
    url = "/api/ai_workspace/sessions"
    name = "api:ai_workspace:sessions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = _hass(request)
        store: Store = _runtime(hass)["store"]
        user_id = _user_id(request)
        sessions = await hass.async_add_executor_job(store.list_sessions, user_id)
        return self.json([_session_dict(item) for item in sessions])

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = _hass(request)
        body = await _json_body(request)
        data = _runtime(hass)
        providers = data.get("providers") or {}
        known_assist = assist_agent_ids(hass)
        provider = str(body.get("provider") or body.get("agent") or "")
        if provider not in providers and provider not in known_assist:
            provider = next((item.info.id for item in providers.values() if item.info.available), "")
        if not provider:
            provider = next(iter(providers), "")
        if not provider and known_assist:
            provider = next(iter(list_assist_agents(hass)), {}).get("id", "")
        provider = provider or "api"
        store: Store = data["store"]
        user_id = _user_id(request)
        session_id = None
        chosen = providers.get(provider)
        if getattr(chosen, "kind", "") == "cursor":
            session_id = await _create_runtime_session(hass, user_id)
        session = await hass.async_add_executor_job(
            store.create_session, user_id, provider, session_id
        )
        await _prune_user_chats(hass, store, user_id, request)
        return self.json(_session_dict(session), status_code=201)


class SessionView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}"
    name = "api:ai_workspace:session"
    requires_auth = True

    async def get(self, request: web.Request, session_id: str) -> web.Response:
        hass: HomeAssistant = _hass(request)
        store: Store = _runtime(hass)["store"]
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        messages = await hass.async_add_executor_job(store.list_messages, session.id)
        pending = False
        lock = _runtime(hass).get("locks", {}).get(session.id)
        if lock is not None:
            pending = lock.locked()
        return self.json(
            {**_session_dict(session), "pending": pending, "messages": [_message_dict(item) for item in messages]}
        )

    async def patch(self, request: web.Request, session_id: str) -> web.Response:
        hass: HomeAssistant = _hass(request)
        store: Store = _runtime(hass)["store"]
        body = await _json_body(request)
        title = str(body.get("title") or "").strip()
        pinned = body.get("pinned")
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        user_id = _user_id(request)
        if pinned is not None:
            session = await hass.async_add_executor_job(
                store.set_pinned, user_id, session_id, bool(pinned)
            )
            if not bool(pinned):
                await _prune_user_chats(hass, store, user_id, request)
                session = await hass.async_add_executor_job(store.get_session, user_id, session_id) or session
        if title:
            session = await hass.async_add_executor_job(store.rename_session, user_id, session_id, title)
        return self.json(_session_dict(session))

    async def delete(self, request: web.Request, session_id: str) -> web.Response:
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        store: Store = data["store"]
        deleted = await hass.async_add_executor_job(store.delete_session, _user_id(request), session_id)
        if not deleted:
            raise web.HTTPNotFound(text="Chat not found.")
        base = str((data.get("runtime_url") or "")).rstrip("/")
        if base:
            try:
                http: ClientSession = async_get_clientsession(hass)
                await http.delete(
                    f"{base}/api/sessions/{session_id}",
                    headers=_runtime_headers(request),
                    timeout=ClientTimeout(total=5),
                )
            except Exception:
                logger.debug("runtime session delete skipped", exc_info=True)
        return web.Response(status=204)


def _release_lock(data: dict[str, Any], session_id: str, lock: asyncio.Lock) -> None:
    if lock.locked():
        lock.release()
    locks = data.get("locks") or {}
    if locks.get(session_id) is lock:
        locks.pop(session_id, None)


def chat_job_name(session_id: str) -> str:
    return f"ai_workspace_chat_{session_id}"


async def cancel_chat_job(data: dict[str, Any], session_id: str) -> bool:
    """Stop the in-flight turn so the next message can use the chat lock."""
    name = chat_job_name(session_id)
    jobs = [job for job in list(data.get("chat_jobs") or set()) if job.get_name() == name and not job.done()]
    for job in jobs:
        job.cancel()
    if not jobs:
        return False
    await asyncio.gather(*jobs, return_exceptions=True)
    return True


def _is_admin(request: web.Request) -> bool:
    return bool(getattr(request.get("hass_user"), "is_admin", False))


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Invalid JSON.") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Invalid JSON.")
    return body


class ChatView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}/chat"
    name = "api:ai_workspace:chat"
    requires_auth = True

    async def post(self, request: web.Request, session_id: str) -> web.StreamResponse:
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        settings = data["settings"]
        store: Store = data["store"]
        user_id = _user_id(request)
        admin = _is_admin(request)
        session = await hass.async_add_executor_job(store.get_session, user_id, session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        body = await _json_body(request)
        images = parse_client_images(body.get("images"))
        files = parse_client_files(body.get("files"))
        message = caption_for(str(body.get("message") or ""), len(images), len(files))
        if not message:
            raise web.HTTPBadRequest(text="Message is empty.")
        lock: asyncio.Lock = data["locks"].setdefault(session.id, asyncio.Lock())
        if lock.locked():
            raise web.HTTPConflict(text="This chat is already waiting on the agent.")
        await lock.acquire()
        try:
            task = await self._start(request, hass, data, settings, store, user_id, admin, session, body, images, files, message, lock)
        except BaseException:
            _release_lock(data, session.id, lock)
            raise
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        return task.result()

    async def _start(
        self,
        request: web.Request,
        hass: HomeAssistant,
        data: dict[str, Any],
        settings,
        store: Store,
        user_id: str,
        admin: bool,
        session: Session,
        body: dict,
        images: list[dict],
        files: list[dict],
        message: str,
        lock: asyncio.Lock,
    ) -> asyncio.Task:
        requested = str(body.get("agent") or body.get("provider") or session.provider)
        providers = data.get("providers") or {}
        known_assist = assist_agent_ids(hass)
        if requested and (requested in providers or requested in known_assist) and requested != session.provider:
            await hass.async_add_executor_job(store.set_provider, user_id, session.id, requested)
            session.provider = requested
        assist = session.provider in known_assist
        if not assist and any(
            getattr(item, "kind", "") == "cursor" and not item.info.available for item in providers.values()
        ):
            await async_bind_runtime(hass, data, force=True)
            providers = data.get("providers") or {}
        provider = None if assist else (providers.get(session.provider) or _send_provider(data, session))
        token_mode = provider_token_mode(provider)
        extras = token_mode_allows_extras(token_mode)
        origin = _frontend_origin(request, body)
        page_note = format_ui_page(parse_ui_page(body.get("page")))
        events_json = json.dumps(image_events(images) + file_events(files), ensure_ascii=False)
        await hass.async_add_executor_job(store.add_message, session.id, "user", message, events_json)
        await hass.async_add_executor_job(store.rename_if_default, session.id, title_from_prompt(message))
        count = await hass.async_add_executor_job(lambda: len(store.list_messages(session.id)))
        suggest = (
            getattr(provider, "suggest_title", None)
            if extras and count <= 1 and needs_title_summary(message)
            else None
        )
        outbound = attach_files_to_message(message, files) if token_mode_allows_files(token_mode) else message
        if page_note and extras:
            outbound = f"{page_note}\n\n{outbound}"
        language = str(body.get("language") or "").strip()
        cross = bool(getattr(settings, "cross_chat", False))
        note = (
            ""
            if not extras
            else await hass.async_add_executor_job(other_chat_note, store, user_id, session.id, message, cross)
        )
        if note:
            outbound = f"{outbound}\n\n{note}"
        handoff = ""
        if assist or getattr(provider, "kind", "") == "cursor":
            rows = await hass.async_add_executor_job(store.list_messages, session.id)
            handoff = handoff_note(rows, session.title)
            if getattr(provider, "kind", "") == "cursor":
                logger.info(
                    "cursor handoff session=%s prior=%s chars=%s",
                    session.id,
                    max(0, len(rows) - 1),
                    len(handoff),
                )
                if len(rows) > 1 and not handoff:
                    logger.warning("cursor handoff empty despite stored turns session=%s", session.id)
        access_token = _bearer(request)
        runtime_headers = _runtime_headers(request)

        def on_agent_id(agent_id: str) -> None:
            if session.agent_id != agent_id:
                hass.async_add_executor_job(store.set_agent_id, session.id, agent_id)
            session.agent_id = agent_id

        async def events():
            if assist:
                async for event in async_assist_events(
                    hass,
                    user_id,
                    session.provider,
                    session.id,
                    attach_files_to_message(message, files),
                    language,
                    page_note,
                ):
                    yield event
                return
            if getattr(provider, "kind", "") == "cursor":
                async for event in _runtime_chat(
                    hass,
                    user_id,
                    session,
                    outbound,
                    origin,
                    images,
                    files,
                    language,
                    runtime_headers,
                    model=str(getattr(provider, "model", "") or ""),
                    effort=str(getattr(provider, "effort", "") or ""),
                    api_key=str(getattr(provider, "api_key", "") or ""),
                    access_token=access_token,
                    handoff=handoff,
                    question=message,
                    admin=admin,
                    agent=_agent_label(provider),
                ):
                    yield event
                return
            if provider is None:
                yield {"type": "error", "message": "Add an agent under AI Workspace in Devices & services."}
                return
            async for event in provider.send(
                session,
                outbound,
                on_agent_id,
                access_token=access_token,
                frontend_origin=origin,
                images=images,
                language=language,
                tools=bool(images) or bool(files) or wants_house_tools(message),
                admin=admin,
                force_tools=not images and not files and wants_house_tools(message),
                **(await _activity_kwargs(hass, provider, user_id, session.id)),
            ):
                yield event

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        client_gone = False

        async def send(event: dict) -> None:
            nonlocal client_gone
            if client_gone:
                return
            try:
                if request.transport is None or request.transport.is_closing():
                    client_gone = True
                    return
                await response.write(_sse(str(event["type"]), event))
            except Exception:
                client_gone = True

        user = await hass.auth.async_get_user(user_id)
        user_name = str(getattr(user, "name", "") or "") if user else user_id
        agent_label = _agent_label(provider) if provider else "Agent"

        async def produce() -> web.StreamResponse:
            nonlocal client_gone
            parts: list[str] = []
            tools: list[dict] = []
            error: str | None = None
            final: str | None = None
            from .logical_commit import begin_logical_commit, flush_logical_commit

            if bool(getattr(settings, "change_history", True)):
                begin_logical_commit(
                    hass,
                    user_id,
                    user_name,
                    agent_label,
                    session.id,
                    session.title or "",
                )
                try:
                    from .activity_ha import attach_turn_watch

                    await attach_turn_watch(hass, user_id, session.id)
                except Exception:
                    logger.debug("change history turn watch skipped", exc_info=True)
            try:
                try:
                    await response.prepare(request)
                except Exception:
                    client_gone = True
                try:
                    async for event in events():
                        kind = event.get("type")
                        if kind == "text":
                            parts.append(str(event.get("delta") or ""))
                        elif kind == "result":
                            final = str(event.get("text") or "")
                            continue
                        elif kind == "done":
                            final = final or str(event.get("answer") or "")
                            continue
                        elif kind == "tool":
                            tools.append(
                                {
                                    "name": event.get("name"),
                                    "phase": event.get("phase"),
                                    "text": event.get("text"),
                                    **({"id": event["id"]} if event.get("id") else {}),
                                }
                            )
                        elif kind == "error":
                            error = str(event.get("message") or "The agent failed.")
                        elif kind == "usage":
                            billed = finalize_usage(
                                event,
                                model=str(event.get("model") or getattr(provider, "model", "") or ""),
                                run_id=str(event.get("run_id") or ""),
                            )
                            if billed is None:
                                continue
                            event = await record_usage_turn(
                                hass,
                                store=store,
                                user_id=user_id,
                                session_id=session.id,
                                provider=provider,
                                usage=billed,
                                origin="chat",
                            )
                        elif kind == "title":
                            label = accept_generated_title(message, str(event.get("title") or ""))
                            applied = None
                            if label:
                                applied = await hass.async_add_executor_job(
                                    store.apply_generated_title, user_id, session.id, title_from_prompt(message), label
                                )
                            if not applied:
                                continue
                            event = {"type": "title", "title": applied}
                        await send(event)
                except asyncio.CancelledError:
                    answer = merge_reply_text("".join(parts), final)
                    if answer or tools:
                        try:
                            await asyncio.shield(
                                hass.async_add_executor_job(
                                    store.add_message,
                                    session.id,
                                    "assistant",
                                    answer,
                                    json.dumps(list(tools), ensure_ascii=False),
                                )
                            )
                        except Exception:
                            logger.debug("stopped turn not stored", exc_info=True)
                    raise
                except Exception as exc:
                    logger.exception("chat failed session=%s", session.id)
                    error = redact(str(exc), [settings.cursor_api_key, settings.api_key, settings.mcp_token])
                    await send({"type": "error", "message": error})
                answer = merge_reply_text("".join(parts), final)
                if error and not answer:
                    answer = error
                stored_events = list(tools)
                if error:
                    stored_events.append({"type": "error", "message": error})
                await hass.async_add_executor_job(
                    store.add_message,
                    session.id,
                    "assistant",
                    answer,
                    json.dumps(stored_events, ensure_ascii=False),
                )
                if error is None:
                    await send({"type": "done", "answer": answer})
            finally:
                if bool(getattr(settings, "change_history", True)):
                    await flush_logical_commit(hass, store, user_id, session.id)
                _release_lock(data, session.id, lock)
            if error is None and callable(suggest):
                try:
                    raw = await asyncio.wait_for(suggest(message, ""), timeout=12)
                except Exception:
                    logger.debug("title generation failed", exc_info=True)
                    raw = None
                title = accept_generated_title(message, raw or "")
                if title:
                    applied = await hass.async_add_executor_job(
                        store.apply_generated_title, user_id, session.id, title_from_prompt(message), title
                    )
                    if applied:
                        await send({"type": "title", "title": applied})
            return response

        jobs: set[asyncio.Task] = data.setdefault("chat_jobs", set())
        task = asyncio.create_task(produce(), name=chat_job_name(session.id))
        jobs.add(task)
        task.add_done_callback(jobs.discard)
        return task


class ChatStopView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}/stop"
    name = "api:ai_workspace:chat_stop"
    requires_auth = True

    async def post(self, request: web.Request, session_id: str) -> web.Response:
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        store: Store = data["store"]
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        stopped = await cancel_chat_job(data, session.id)
        return self.json({"ok": True, "stopped": stopped})


class SpeechView(HomeAssistantView):
    url = "/api/ai_workspace/stt"
    name = "api:ai_workspace:stt"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _user_id(request)
        from .const import STT_BROWSER
        from .voice import async_transcribe

        settings = _runtime(_hass(request))["settings"]
        engine = str(settings.stt_engine or "")
        if not engine or engine == STT_BROWSER:
            raise web.HTTPBadRequest(text="Speech-to-text is set to the browser.")
        audio = await request.read()
        if not audio:
            raise web.HTTPBadRequest(text="No audio.")
        language = str(request.headers.get("X-Speech-Language") or "")
        try:
            text = await async_transcribe(_hass(request), engine, audio, language)
        except Exception as exc:
            raise web.HTTPBadGateway(text=str(exc)[:300]) from exc
        return self.json({"text": text})


class SpeakView(HomeAssistantView):
    url = "/api/ai_workspace/tts"
    name = "api:ai_workspace:tts"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        _user_id(request)
        from .const import TTS_OFF
        from .voice import async_speak

        settings = _runtime(_hass(request))["settings"]
        engine = str(settings.tts_engine or "")
        if not engine or engine == TTS_OFF:
            raise web.HTTPBadRequest(text="Text-to-speech is off.")
        body = await _json_body(request)
        language = str(body.get("language") or "")
        from .usage_record import tts_usage_scope

        try:
            with tts_usage_scope(
                user_id=_user_id(request),
                session_id=str(body.get("session_id") or ""),
            ):
                data, mime = await async_speak(
                    _hass(request),
                    engine,
                    str(body.get("text") or ""),
                    language,
                    natural=bool(getattr(settings, "tts_natural", True)),
                )
        except Exception as exc:
            raise web.HTTPBadGateway(text=str(exc)[:300]) from exc
        if not data:
            raise web.HTTPBadGateway(text="Text-to-speech returned no audio.")
        return web.Response(body=data, content_type=mime or "audio/mpeg")


class HouseMapMcpView(HomeAssistantView):
    """Minimal MCP HTTP endpoint for the local config catalog search tool."""

    url = "/api/ai_workspace/house_map/mcp"
    name = "api:ai_workspace:house_map:mcp"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = _hass(request)
        _user_id(request)
        if not _is_admin(request):
            raise web.HTTPForbidden(text="The config catalog is for administrators.")
        settings = _runtime(hass).get("settings")
        if not getattr(settings, "house_map", False):
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Config catalog is off."}},
                status=404,
            )
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status=400,
            )
        if not isinstance(body, dict):
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}},
                status=400,
            )
        req_id = body.get("id")
        method = str(body.get("method") or "")
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        from .house_map import TOOL_NAME, HouseMapClient

        store: Store = _runtime(hass)["store"]
        client = HouseMapClient(hass, store)

        if method == "notifications/initialized" or method.startswith("notifications/"):
            return web.Response(status=202)

        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-workspace-catalog", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": await client.list_tools()}
        elif method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                payload = await client.call_tool(name or TOOL_NAME, arguments)
            except Exception as exc:
                return web.json_response(
                    {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)[:300]}},
                    status=200,
                )
            text = json.dumps(payload, ensure_ascii=False)
            result = {"content": [{"type": "text", "text": text}], "structuredContent": payload}
        elif method == "ping":
            result = {}
        else:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                },
                status=200,
            )
        if req_id is None:
            return web.Response(status=202)
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result})


class CatalogMcpView(HouseMapMcpView):
    url = "/api/ai_workspace/catalog/mcp"
    name = "api:ai_workspace:catalog:mcp"


def _agent_label(provider: Any) -> str:
    info = getattr(provider, "info", None)
    return str(getattr(info, "label", "") or "Cursor")


async def _activity_kwargs(
    hass: HomeAssistant, provider: Any, user_id: str, session_id: str = ""
) -> dict[str, Any]:
    from .api_provider import ApiProvider

    if not isinstance(provider, ApiProvider):
        return {}
    settings = _runtime(hass).get("settings")
    if not bool(getattr(settings, "change_history", True)):
        return {}
    from .activity_ha import track_tool

    user = await hass.auth.async_get_user(user_id)
    user_name = str(getattr(user, "name", "") or "") if user else ""
    store: Store = _runtime(hass)["store"]
    label = _agent_label(provider)

    async def on_tool(tool: str, args: dict, call) -> Any:
        return await track_tool(
            hass, store, user_id, user_name or user_id, label, tool, args, call, session_id
        )

    return {"on_tool": on_tool}


def _runtime_token_ok(request: web.Request) -> bool:
    expected = str((_runtime(_hass(request)).get("runtime_token") or "")).strip()
    scheme, _, value = str(request.headers.get("Authorization") or "").partition(" ")
    provided = value.strip() if scheme.lower() == "bearer" else ""
    if expected:
        return bool(provided) and hmac.compare_digest(provided.encode(), expected.encode())
    # Without a token only a Runtime on this host (bound to loopback) may call in.
    return _loopback_remote(request)


def _loopback_remote(request: web.Request) -> bool:
    try:
        return ipaddress.ip_address(str(request.remote or "").split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _activity_dict(row, chat: str = "", *, admin: bool = False, ha_mcp: bool = False) -> dict:
    undone = bool(row.undone_at)
    can_rollback, ask = activity_restore_flags(
        snapshot=bool(row.can_rollback),
        undone=undone,
        admin=admin,
        ha_mcp=ha_mcp,
    )
    return {
        "id": row.id,
        "created_at": row.created_at,
        "user_id": row.user_id,
        "user_name": row.user_name,
        "agent": row.agent,
        "chat": chat or row.chat,
        "session_id": row.session_id or "",
        "summary": row.summary,
        "tool": row.tool,
        "can_rollback": can_rollback,
        "undone_at": row.undone_at or "",
        "ask_restore": ask,
        "logical_commit": bool(getattr(row, "logical_commit", False)),
        "change_count": int(getattr(row, "change_count", 0) or 0),
        "restore_kind": getattr(row, "restore_kind", "") or "",
        "restore_id": getattr(row, "restore_id", "") or "",
        "restore_label": getattr(row, "restore_label", "") or "",
        "restore_targets": list(getattr(row, "restore_targets", None) or []),
    }


class ActivityView(HomeAssistantView):
    url = "/api/ai_workspace/activity"
    name = "api:ai_workspace:activity"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = _hass(request)
        store: Store = _runtime(hass)["store"]
        user_id = _user_id(request)
        admin = _is_admin(request)
        rows = await hass.async_add_executor_job(lambda: store.list_activity(user_id, admin=admin))
        titles = await hass.async_add_executor_job(store.session_titles, [row.session_id for row in rows])
        settings = _runtime(hass).get("settings")
        ha_mcp = ha_mcp_is_connected(
            str(getattr(settings, "mcp_kind", "") or "") if settings else "",
            list(getattr(settings, "mcp_rows", None) or []) if settings else None,
        )
        return self.json(
            [
                _activity_dict(row, titles.get(row.session_id) or "", admin=admin, ha_mcp=ha_mcp)
                for row in rows
            ]
        )


class ActivityRollbackView(HomeAssistantView):
    url = "/api/ai_workspace/activity/{activity_id}/rollback"
    name = "api:ai_workspace:activity:rollback"
    requires_auth = True

    async def post(self, request: web.Request, activity_id: str) -> web.Response:
        from .activity_ha import ActivityError, rollback

        hass = _hass(request)
        store: Store = _runtime(hass)["store"]
        try:
            row_id = int(activity_id)
        except (TypeError, ValueError):
            raise web.HTTPNotFound() from None
        row = await hass.async_add_executor_job(store.get_activity, row_id)
        if row is None:
            raise web.HTTPNotFound()
        if not _is_admin(request) and row.user_id != _user_id(request):
            raise web.HTTPNotFound()
        if not ACTIVITY_ROLLBACK or not row.can_rollback:
            logger.warning("Change History rollback refused: no restorable snapshot for %s", row_id)
            raise web.HTTPBadRequest(text="This change cannot be rolled back.")
        raw = await hass.async_add_executor_job(store.activity_document, row_id)
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            document = None
        if not isinstance(document, dict):
            logger.warning("Change History rollback refused: missing document for %s", row_id)
            raise web.HTTPBadRequest(text="This change cannot be rolled back.")
        try:
            await rollback(hass, document)
        except ActivityError as exc:
            logger.warning("Change History rollback failed: %s", exc)
            raise web.HTTPBadRequest(text=str(exc)) from exc
        updated = await hass.async_add_executor_job(store.mark_activity_undone, row_id)
        shown = updated or row
        live = await hass.async_add_executor_job(store.session_title, shown.session_id)
        return self.json(_activity_dict(shown, live))


class McpProxyView(HomeAssistantView):
    """Last MCP proxy result. GET is admin-only; POST is the Runtime note."""

    url = "/api/ai_workspace/mcp_proxy"
    name = "api:ai_workspace:mcp_proxy"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        if not _signed_in(request) or not _is_admin(request):
            raise web.HTTPUnauthorized()
        return self.json(last_mcp_result(_hass(request)) or {})

    async def post(self, request: web.Request) -> web.Response:
        if not _runtime_token_ok(request):
            raise web.HTTPUnauthorized()
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="Invalid JSON.") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid JSON.")
        return self.json(
            note_mcp_result(
                _hass(request),
                tool=str(body.get("tool") or ""),
                kind=str(body.get("kind") or ""),
                agent=str(body.get("agent") or ""),
            )
        )


class ActivityPrepareView(HomeAssistantView):
    """Runtime callback. Snapshots a config document before Cursor forwards a tool."""

    url = "/api/ai_workspace/activity/prepare"
    name = "api:ai_workspace:activity:prepare"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        from .activity_ha import prepare

        if not _runtime_token_ok(request):
            raise web.HTTPUnauthorized()
        hass = _hass(request)
        settings = _runtime(hass).get("settings")
        if not bool(getattr(settings, "change_history", True)):
            return self.json({"token": None})
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="Invalid JSON.") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid JSON.")
        user_id = str(body.get("user_id") or "").strip()
        if not user_id:
            return self.json({"token": None})
        user = await hass.auth.async_get_user(user_id)
        user_name = str(getattr(user, "name", "") or "") if user else ""
        arguments = body.get("arguments") if isinstance(body.get("arguments"), dict) else {}
        token = await prepare(
            hass,
            user_id,
            user_name or user_id,
            str(body.get("agent") or "Cursor"),
            str(body.get("tool") or ""),
            arguments,
            str(body.get("session_id") or ""),
        )
        return self.json({"token": token})


class ActivityCommitView(HomeAssistantView):
    url = "/api/ai_workspace/activity/commit"
    name = "api:ai_workspace:activity:commit"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        from .activity_ha import commit

        if not _runtime_token_ok(request):
            raise web.HTTPUnauthorized()
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="Invalid JSON.") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Invalid JSON.")
        hass = _hass(request)
        store: Store = _runtime(hass)["store"]
        await commit(hass, store, str(body.get("token") or ""), ok=bool(body.get("ok")))
        return self.json({"ok": True})


class UsageView(HomeAssistantView):
    url = "/api/ai_workspace/usage"
    name = "api:ai_workspace:usage"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        owner = "" if _is_admin(request) else _user_id(request)
        hass = _hass(request)
        store: Store = _runtime(hass)["store"]
        session_id = str(request.query.get("session_id") or "").strip()
        range_key = str(request.query.get("range") or "month").strip()
        agent_id = str(request.query.get("agent_id") or "").strip()
        model = str(request.query.get("model") or "").strip()
        since = str(request.query.get("since") or "").strip()
        until = str(request.query.get("until") or "").strip()
        payload = await hass.async_add_executor_job(
            lambda: dashboard_payload(
                hass,
                store,
                session_id=session_id,
                range_key=range_key,
                agent_id=agent_id,
                model=model,
                since=since,
                until=until,
                user_id=owner,
            )
        )
        return self.json(payload)


def register_views(hass: HomeAssistant) -> None:
    hass.http.register_view(HealthView)
    hass.http.register_view(UiView)
    hass.http.register_view(UsageView)
    hass.http.register_view(ProvidersView)
    hass.http.register_view(SpeechView)
    hass.http.register_view(SpeakView)
    hass.http.register_view(SessionsView)
    hass.http.register_view(SessionView)
    hass.http.register_view(ChatView)
    hass.http.register_view(ChatStopView)
    hass.http.register_view(HouseMapMcpView)
    hass.http.register_view(CatalogMcpView)
    hass.http.register_view(ActivityView)
    hass.http.register_view(ActivityRollbackView)
    hass.http.register_view(McpProxyView)
    hass.http.register_view(ActivityPrepareView)
    hass.http.register_view(ActivityCommitView)
