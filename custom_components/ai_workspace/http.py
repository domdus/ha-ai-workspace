from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse
from typing import Any, AsyncIterator

from aiohttp import ClientSession, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .assist_agents import assist_agent_ids, async_assist_events, list_assist_agents
from .const import (
    CLOUD_ONLY_MODELS,
    DEFAULT_SYSTEM_PROMPT,
    DOMAIN,
    MCP_COOLVER,
    MODE_API,
    MODE_CURSOR,
    format_ui_page,
    parse_ui_page,
    with_language_rule,
    with_ui_context,
)
from .chat_scope import other_chat_note
from .files import attach_files_to_message, file_events, parse_client_files
from .images import caption_for, image_events, parse_client_images

try:
    from homeassistant.components.http import KEY_HASS
except ImportError:
    KEY_HASS = "hass"
from .redact import redact
from .store import Session, Store
from .titles import clean_title

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


def _runtime_headers_for(user_id: str, accept: str = "application/json") -> dict[str, str]:
    uid = str(user_id or "anonymous")
    return {
        "Accept": accept,
        "Content-Type": "application/json",
        "X-Remote-User-Id": uid,
        "X-Hass-User-Id": uid,
    }


def _runtime_headers(request: web.Request) -> dict[str, str]:
    user = request["hass_user"]
    uid = str(user.id) if user else "anonymous"
    return _runtime_headers_for(uid, request.headers.get("Accept", "application/json"))


async def _create_runtime_session(hass: HomeAssistant, user_id: str, session_id: str | None = None) -> str | None:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        return None
    http: ClientSession = async_get_clientsession(hass)
    payload: dict[str, str] = {"provider": "cursor"}
    if session_id:
        payload["id"] = session_id
    try:
        resp = await http.post(
            f"{base}/api/sessions",
            json=payload,
            headers=_runtime_headers_for(user_id),
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


async def _ensure_runtime_session(hass: HomeAssistant, user_id: str, session: Session) -> None:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        return
    http: ClientSession = async_get_clientsession(hass)
    try:
        existing = await http.get(
            f"{base}/api/sessions/{session.id}",
            headers=_runtime_headers_for(user_id),
            timeout=ClientTimeout(total=8),
        )
        status = existing.status
        existing.release()
        if status == 200:
            return
    except Exception:
        logger.debug("runtime session lookup skipped", exc_info=True)
    await _create_runtime_session(hass, user_id, session.id)


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


def _runtime_agent_overrides(hass: HomeAssistant) -> dict[str, Any]:
    settings = _runtime(hass).get("settings")
    extra: dict[str, Any] = {}
    if settings is None:
        return extra
    servers = dict(getattr(settings, "mcp_servers", None) or {})
    kind = str(getattr(settings, "mcp_kind", "") or "")
    if kind == MCP_COOLVER:
        servers.pop("mcp", None)
    if servers:
        extra["mcp"] = {"servers": servers}
    model = str(getattr(settings, "model", "") or "").strip()
    if model in CLOUD_ONLY_MODELS:
        model = ""
    if model:
        extra["model"] = model
    return extra


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
) -> AsyncIterator[dict]:
    base = str((_runtime(hass).get("runtime_url") or "")).rstrip("/")
    if not base:
        yield {"type": "error", "message": "Cursor Runtime is not configured."}
        return
    await _ensure_runtime_session(hass, user_id, session)
    http: ClientSession = async_get_clientsession(hass)
    payload: dict[str, Any] = {
        "message": with_ui_context(attach_files_to_message(message, files or []), origin),
        "question": message,
        "origin": origin,
    }
    settings = _runtime(hass).get("settings")
    prompt = with_language_rule(
        str(getattr(settings, "system_prompt", "") or "").strip() or DEFAULT_SYSTEM_PROMPT,
        language,
    )
    if getattr(settings, "house_map", False):
        from .house_map import HOUSE_MAP_INSTRUCTIONS

        prompt = f"{prompt}\n\n{HOUSE_MAP_INSTRUCTIONS}".strip()
    if prompt:
        payload["message"] = f"{prompt}\n\n{payload['message']}"
    if images:
        payload["images"] = [
            {"name": item["name"], "mime": item["mime"], "data": item["data"]} for item in images
        ]
    payload.update(_runtime_agent_overrides(hass))
    if model:
        payload["model"] = model
    if effort:
        payload["effort"] = effort
    if api_key:
        payload["api_key"] = api_key
    try:
        resp = await http.post(
            f"{base}/api/sessions/{session.id}/chat",
            json=payload,
            headers={**(headers or _runtime_headers_for(user_id)), "Accept": "text/event-stream"},
            timeout=ClientTimeout(total=None, sock_read=600),
        )
    except Exception as exc:
        yield {"type": "error", "message": f"AI Workspace runtime is unreachable at {base}: {exc}"}
        return
    try:
        if resp.status >= 400:
            text = await resp.text()
            yield {"type": "error", "message": text[:400] or f"Runtime HTTP {resp.status}"}
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
) -> AsyncIterator[dict]:
    """Run one turn for Assist or any caller that is not an HTTP chat request."""
    store: Store = _runtime(hass)["store"]

    def on_agent_id(agent_id: str) -> None:
        store.set_agent_id(session.id, agent_id)
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
    ):
        yield event


async def _import_runtime_sessions(hass: HomeAssistant, request: web.Request, store: Store, user_id: str) -> None:
    data = _runtime(hass)
    base = str((data.get("runtime_url") or "")).rstrip("/")
    if not base:
        return
    http: ClientSession = async_get_clientsession(hass)
    try:
        resp = await http.get(
            f"{base}/api/sessions",
            headers=_runtime_headers(request),
            timeout=ClientTimeout(total=8),
        )
        if resp.status != 200:
            resp.release()
            return
        items = await resp.json()
        resp.release()
    except Exception:
        logger.debug("runtime session import skipped", exc_info=True)
        return
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("id")
        if raw is None:
            raw = item.get("session_id")
        if isinstance(raw, (int, float)):
            sid = str(int(raw)) if float(raw).is_integer() else ""
        elif isinstance(raw, str):
            sid = raw.strip()
        else:
            sid = ""
        if not sid or len(sid) > 128:
            continue
        try:
            added = await hass.async_add_executor_job(
                store.import_session,
                user_id,
                sid,
                str(item.get("provider") or "cursor"),
                str(item.get("title") or "New Chat"),
                str(item.get("agent_id") or "") or None,
                str(item.get("created_at") or ""),
                str(item.get("updated_at") or ""),
            )
        except Exception:
            logger.debug("runtime session import skipped", exc_info=True)
            continue
        if not added:
            existing = await hass.async_add_executor_job(store.list_messages, sid)
            if existing:
                continue
        try:
            detail = await http.get(
                f"{base}/api/sessions/{sid}",
                headers=_runtime_headers(request),
                timeout=ClientTimeout(total=8),
            )
        except Exception:
            continue
        if detail.status != 200:
            detail.release()
            continue
        body = await detail.json()
        detail.release()
        for message in body.get("messages") or []:
            if not isinstance(message, dict):
                continue
            events = message.get("events") or []
            blob = events if isinstance(events, str) else json.dumps(events, ensure_ascii=False)
            await hass.async_add_executor_job(
                store.add_message,
                sid,
                str(message.get("role") or "assistant"),
                str(message.get("content") or ""),
                blob,
            )


def _send_provider(data: dict[str, Any], session: Session):
    providers = data.get("providers") or {}
    ready = next((item for item in providers.values() if item.info.available), None)
    if ready is not None:
        return ready
    return providers.get(session.provider)


async def _title_from_task(task, timeout: float = 12) -> str:
    if task is None:
        return ""
    try:
        raw = await asyncio.wait_for(task, timeout)
    except Exception:
        logger.debug("title generation failed", exc_info=True)
        if not task.done():
            task.cancel()
        return ""
    return clean_title(raw or "")


_SKIP = {"content-length", "transfer-encoding", "connection", "host"}


async def _proxy(request: web.Request, path: str) -> web.StreamResponse | None:
    hass = _hass(request)
    data = hass.data.get(DOMAIN) or {}
    if data.get("mode") == MODE_API:
        return None
    base = str(data.get("runtime_url") or "").rstrip("/")
    if not base:
        return None
    target = f"{base}/api/{path}" if path else f"{base}/api"
    user = request["hass_user"]
    headers = {
        "Accept": request.headers.get("Accept", "application/json"),
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "X-Remote-User-Id": str(user.id) if user else "anonymous",
        "X-Hass-User-Id": str(user.id) if user else "anonymous",
    }
    body = await request.read()
    if request.query_string:
        target = f"{target}?{request.query_string}"
    session: ClientSession = async_get_clientsession(hass)
    try:
        resp = await session.request(
            request.method,
            target,
            headers=headers,
            data=body or None,
            timeout=ClientTimeout(total=None, sock_read=600),
        )
    except Exception as exc:
        raise web.HTTPBadGateway(text=f"AI Workspace runtime is unreachable at {base}: {exc}") from exc
    try:
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _SKIP}
        if "text/event-stream" in resp.headers.get("Content-Type", ""):
            stream = web.StreamResponse(status=resp.status, headers=out_headers)
            await stream.prepare(request)
            async for chunk in resp.content.iter_any():
                await stream.write(chunk)
            return stream
        payload = await resp.read()
        return web.Response(status=resp.status, body=payload, headers=out_headers)
    finally:
        resp.release()


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
        return self.json(
            {
                "dictate": bool(settings.enable_dictate),
                "allowed": bool(getattr(user, "is_admin", False) or settings.allow_users),
                "stt": settings.stt_engine,
                "tts": settings.tts_engine,
                "speak": bool(settings.speak_replies and settings.tts_engine and settings.tts_engine != "off"),
            }
        )


class HealthView(HomeAssistantView):
    url = "/api/ai_workspace/health"
    name = "api:ai_workspace:health"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        _user_id(request)
        proxied = await _proxy(request, "health")
        if proxied is not None:
            return proxied
        data = _runtime(_hass(request))
        settings = data["settings"]
        providers = data.get("providers") or {}
        ready = next((item.info for item in providers.values() if item.info.available), None)
        first = next(iter(providers.values())).info if providers else None
        info = ready or first
        return self.json(
            {
                "ok": True,
                "model": settings.model,
                "mode": settings.mode,
                "cursor": bool(info and info.id == "cursor" and info.available),
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
        try:
            await _import_runtime_sessions(hass, request, store, user_id)
        except Exception:
            logger.debug("runtime session import skipped", exc_info=True)
        sessions = await hass.async_add_executor_job(store.list_sessions, user_id)
        return self.json([_session_dict(item) for item in sessions])

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = _hass(request)
        body = await request.json()
        data = _runtime(hass)
        providers = data.get("providers") or {}
        known_assist = assist_agent_ids(hass)
        provider = str(body.get("provider") or body.get("agent") or "")
        if provider not in providers and provider not in known_assist:
            provider = next((item.info.id for item in providers.values() if item.info.available), "")
        if not provider and known_assist:
            provider = next(iter(list_assist_agents(hass)), {}).get("id", "")
        provider = provider or next(iter(providers), "") or "api"
        store: Store = data["store"]
        session_id = None
        chosen = providers.get(provider)
        if getattr(chosen, "kind", "") == "cursor":
            session_id = await _create_runtime_session(hass, _user_id(request))
        session = await hass.async_add_executor_job(
            store.create_session, _user_id(request), provider, session_id
        )
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
        body = await request.json()
        title = str(body.get("title") or "").strip()
        pinned = body.get("pinned")
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        if pinned is not None:
            session = await hass.async_add_executor_job(
                store.set_pinned, _user_id(request), session_id, bool(pinned)
            )
        if title:
            session = await hass.async_add_executor_job(store.rename_session, _user_id(request), session_id, title)
        return self.json(_session_dict(session))

    async def delete(self, request: web.Request, session_id: str) -> web.Response:
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        store: Store = data["store"]
        deleted = await hass.async_add_executor_job(store.delete_session, _user_id(request), session_id)
        if not deleted:
            raise web.HTTPNotFound(text="Chat not found.")
        runtime = data.get("runtime")
        if runtime:
            runtime.drop(session_id)
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


class ChatView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}/chat"
    name = "api:ai_workspace:chat"
    requires_auth = True

    async def post(self, request: web.Request, session_id: str) -> web.StreamResponse:
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        settings = data["settings"]
        store: Store = data["store"]
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        body = await request.json()
        requested = str(body.get("agent") or body.get("provider") or session.provider)
        providers = data.get("providers") or {}
        known_assist = assist_agent_ids(hass)
        if requested and (requested in providers or requested in known_assist):
            if requested != session.provider:
                await hass.async_add_executor_job(store.set_provider, _user_id(request), session.id, requested)
                session.provider = requested
        assist = session.provider in known_assist
        provider = None if assist else (providers.get(session.provider) or _send_provider(data, session))
        images = parse_client_images(body.get("images"))
        files = parse_client_files(body.get("files"))
        message = caption_for(str(body.get("message") or ""), len(images), len(files))
        if not message:
            raise web.HTTPBadRequest(text="Message is empty.")
        origin = _frontend_origin(request, body)
        page_note = format_ui_page(parse_ui_page(body.get("page")))
        lock: asyncio.Lock = data["locks"].setdefault(session.id, asyncio.Lock())
        if lock.locked():
            raise web.HTTPConflict(text="This chat is already waiting on the agent.")
        events_json = json.dumps(image_events(images) + file_events(files), ensure_ascii=False)
        await hass.async_add_executor_job(
            store.add_message,
            session.id,
            "user",
            message,
            events_json,
        )
        await hass.async_add_executor_job(store.rename_if_default, session.id, message.replace("\n", " ").strip())
        count = await hass.async_add_executor_job(lambda: len(store.list_messages(session.id)))
        suggest = getattr(provider, "suggest_title", None) if count <= 1 else None
        outbound = attach_files_to_message(message, files)
        if page_note:
            outbound = f"{page_note}\n\n{outbound}"

        language = str(body.get("language") or "").strip()
        user_id = _user_id(request)
        note = await hass.async_add_executor_job(other_chat_note, store, user_id, session.id, message)
        if note:
            outbound = f"{outbound}\n\n{note}"
        access_token = _bearer(request)
        runtime_headers = _runtime_headers(request)

        def on_agent_id(agent_id: str) -> None:
            store.set_agent_id(session.id, agent_id)
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

        async def produce() -> None:
            nonlocal client_gone
            parts: list[str] = []
            tools: list[dict] = []
            error: str | None = None
            final: str | None = None
            answer = ""
            held = False
            await lock.acquire()
            held = True
            try:
                try:
                    await response.prepare(request)
                except Exception:
                    client_gone = True
                try:
                    async for event in events():
                        if event.get("type") == "text":
                            parts.append(str(event.get("delta") or ""))
                        elif event.get("type") == "result":
                            final = str(event.get("text") or "")
                            continue
                        elif event.get("type") == "tool":
                            tools.append(
                                {
                                    "name": event.get("name"),
                                    "phase": event.get("phase"),
                                    "text": event.get("text"),
                                    **({"id": event["id"]} if event.get("id") else {}),
                                }
                            )
                        elif event.get("type") == "error":
                            error = str(event.get("message") or "The agent failed.")
                        elif event.get("type") == "title":
                            label = clean_title(str(event.get("title") or ""))
                            applied = None
                            if label:
                                applied = await hass.async_add_executor_job(
                                    store.apply_generated_title,
                                    user_id,
                                    session.id,
                                    message,
                                    label,
                                )
                            if not applied:
                                continue
                            event = {"type": "title", "title": applied}
                        if client_gone:
                            continue
                        try:
                            if request.transport is None or request.transport.is_closing():
                                client_gone = True
                                continue
                            await response.write(_sse(str(event["type"]), event))
                        except Exception:
                            client_gone = True
                except Exception as exc:
                    logger.exception("chat failed session=%s", session.id)
                    error = redact(str(exc), [settings.cursor_api_key, settings.api_key, settings.mcp_token])
                    if not client_gone:
                        try:
                            await response.write(_sse("error", {"type": "error", "message": error}))
                        except Exception:
                            client_gone = True
                answer = (final or "".join(parts)).strip()
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
                if error is None and not client_gone:
                    try:
                        await response.write(_sse("done", {"type": "done", "answer": answer}))
                        await response.write(_sse("status", {"type": "status", "text": "Done."}))
                    except Exception:
                        client_gone = True
            finally:
                if held:
                    lock.release()
            if error is None and callable(suggest):
                title = await _title_from_task(asyncio.create_task(suggest(message, "")))
                if title:
                    applied = await hass.async_add_executor_job(
                        store.apply_generated_title, user_id, session.id, message, title
                    )
                    if applied and not client_gone:
                        try:
                            await response.write(_sse("title", {"type": "title", "title": applied}))
                        except Exception:
                            logger.debug("title event skipped", exc_info=True)

        jobs: set[asyncio.Task] = data.setdefault("chat_jobs", set())
        task = asyncio.create_task(produce(), name=f"ai_workspace_chat_{session.id}")
        jobs.add(task)
        task.add_done_callback(jobs.discard)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            client_gone = True
            raise
        return response


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
        body = await request.json()
        language = str(body.get("language") or "")
        try:
            url = await async_speak(_hass(request), engine, str(body.get("text") or ""), language)
        except Exception as exc:
            raise web.HTTPBadGateway(text=str(exc)[:300]) from exc
        if not url:
            raise web.HTTPBadGateway(text="Text-to-speech returned no audio.")
        return self.json({"url": url})


class HouseMapMcpView(HomeAssistantView):
    """Minimal MCP HTTP endpoint for the local house map search tool."""

    url = "/api/ai_workspace/house_map/mcp"
    name = "api:ai_workspace:house_map:mcp"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        hass = _hass(request)
        _user_id(request)
        settings = _runtime(hass).get("settings")
        if not getattr(settings, "house_map", False):
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "House map cache is off."}},
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
                "serverInfo": {"name": "ai-workspace-house-map", "version": "1"},
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


def register_views(hass: HomeAssistant) -> None:
    hass.http.register_view(HealthView)
    hass.http.register_view(UiView)
    hass.http.register_view(ProvidersView)
    hass.http.register_view(SpeechView)
    hass.http.register_view(SpeakView)
    hass.http.register_view(SessionsView)
    hass.http.register_view(SessionView)
    hass.http.register_view(ChatView)
    hass.http.register_view(HouseMapMcpView)
