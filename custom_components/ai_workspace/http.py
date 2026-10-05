from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, MODE_API

try:
    from homeassistant.components.http import KEY_HASS
except ImportError:
    KEY_HASS = "hass"
from .redact import redact
from .store import Session, Store

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


def _user_id(request: web.Request) -> str:
    user = request["hass_user"]
    if user is None:
        raise web.HTTPUnauthorized(text="Sign in through Home Assistant.")
    return str(user.id)


class HealthView(HomeAssistantView):
    url = "/api/ai_workspace/health"
    name = "api:ai_workspace:health"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
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
            }
        )


class ProvidersView(HomeAssistantView):
    url = "/api/ai_workspace/providers"
    name = "api:ai_workspace:providers"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        proxied = await _proxy(request, "providers")
        if proxied is not None:
            return proxied
        data = _runtime(_hass(request))
        return self.json([item.info.as_dict() for item in data["providers"].values()])


class SessionsView(HomeAssistantView):
    url = "/api/ai_workspace/sessions"
    name = "api:ai_workspace:sessions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        proxied = await _proxy(request, "sessions")
        if proxied is not None:
            return proxied
        hass: HomeAssistant = _hass(request)
        store: Store = _runtime(hass)["store"]
        user_id = _user_id(request)
        sessions = await hass.async_add_executor_job(store.list_sessions, user_id)
        return self.json([_session_dict(item) for item in sessions])

    async def post(self, request: web.Request) -> web.Response:
        proxied = await _proxy(request, "sessions")
        if proxied is not None:
            return proxied
        hass: HomeAssistant = _hass(request)
        body = await request.json()
        data = _runtime(hass)
        providers = data.get("providers") or {}
        provider = str(body.get("provider") or "")
        if not provider:
            ready = next((item.info.id for item in providers.values() if item.info.available), "")
            provider = ready or next(iter(providers), "")
        if provider not in providers:
            raise web.HTTPBadRequest(text="Unknown provider.")
        store: Store = data["store"]
        session = await hass.async_add_executor_job(store.create_session, _user_id(request), provider)
        return self.json(_session_dict(session), status_code=201)


class SessionView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}"
    name = "api:ai_workspace:session"
    requires_auth = True

    async def get(self, request: web.Request, session_id: str) -> web.Response:
        proxied = await _proxy(request, f"sessions/{session_id}")
        if proxied is not None:
            return proxied
        hass: HomeAssistant = _hass(request)
        store: Store = _runtime(hass)["store"]
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        messages = await hass.async_add_executor_job(store.list_messages, session.id)
        return self.json({**_session_dict(session), "messages": [_message_dict(item) for item in messages]})

    async def delete(self, request: web.Request, session_id: str) -> web.Response:
        proxied = await _proxy(request, f"sessions/{session_id}")
        if proxied is not None:
            return proxied
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        store: Store = data["store"]
        deleted = await hass.async_add_executor_job(store.delete_session, _user_id(request), session_id)
        if not deleted:
            raise web.HTTPNotFound(text="Chat not found.")
        runtime = data.get("runtime")
        if runtime:
            runtime.drop(session_id)
        return web.Response(status=204)


class ChatView(HomeAssistantView):
    url = "/api/ai_workspace/sessions/{session_id}/chat"
    name = "api:ai_workspace:chat"
    requires_auth = True

    async def post(self, request: web.Request, session_id: str) -> web.StreamResponse:
        proxied = await _proxy(request, f"sessions/{session_id}/chat")
        if proxied is not None:
            return proxied
        hass: HomeAssistant = _hass(request)
        data = _runtime(hass)
        settings = data["settings"]
        store: Store = data["store"]
        session = await hass.async_add_executor_job(store.get_session, _user_id(request), session_id)
        if session is None:
            raise web.HTTPNotFound(text="Chat not found.")
        provider = data["providers"].get(session.provider)
        if provider is None:
            raise web.HTTPBadRequest(text="Unknown provider.")
        body = await request.json()
        message = str(body.get("message") or "").strip()
        if not message:
            raise web.HTTPBadRequest(text="Message is empty.")
        lock: asyncio.Lock = data["locks"].setdefault(session.id, asyncio.Lock())
        if lock.locked():
            raise web.HTTPConflict(text="This chat is already waiting on the agent.")
        await hass.async_add_executor_job(store.add_message, session.id, "user", message)
        await hass.async_add_executor_job(store.rename_if_default, session.id, message.replace("\n", " ").strip())

        def on_agent_id(agent_id: str) -> None:
            store.set_agent_id(session.id, agent_id)
            session.agent_id = agent_id

        await lock.acquire()
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        parts: list[str] = []
        tools: list[dict] = []
        error: str | None = None
        final: str | None = None
        try:
            try:
                async for event in provider.send(session, message, on_agent_id, access_token=_bearer(request)):
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
                            }
                        )
                    elif event.get("type") == "error":
                        error = str(event.get("message") or "The agent failed.")
                    await response.write(_sse(str(event["type"]), event))
                    if request.transport is None or request.transport.is_closing():
                        break
            except Exception as exc:
                logger.exception("chat failed session=%s", session.id)
                error = redact(str(exc), [settings.cursor_api_key, settings.api_key, settings.mcp_token])
                await response.write(_sse("error", {"type": "error", "message": error}))
            answer = (final or "".join(parts)).strip()
            if error and not answer:
                answer = error
            await hass.async_add_executor_job(
                store.add_message,
                session.id,
                "assistant",
                answer,
                json.dumps(tools, ensure_ascii=False),
            )
            if error is None:
                await response.write(_sse("done", {"type": "done", "answer": answer}))
                await response.write(_sse("status", {"type": "status", "text": "Done."}))
        finally:
            lock.release()
        return response


def register_views(hass: HomeAssistant) -> None:
    hass.http.register_view(HealthView)
    hass.http.register_view(ProvidersView)
    hass.http.register_view(SessionsView)
    hass.http.register_view(SessionView)
    hass.http.register_view(ChatView)
