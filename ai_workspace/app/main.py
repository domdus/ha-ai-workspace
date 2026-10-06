from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.files import attach_files_to_message, file_events, parse_client_files
from app.images import caption_for, image_events, parse_client_images
from app.redact import redact
from app.settings import Settings
from app.store import Session, Store
from app.titles import clean_title

logger = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent / "static"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:\t%(name)s: %(message)s",
        force=True,
    )
    logging.getLogger("app").setLevel(logging.INFO)
    logging.getLogger("app.providers.cursor").setLevel(logging.INFO)


class SessionCreate(BaseModel):
    provider: str = "cursor"
    id: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    pinned: bool | None = None


class ChatImage(BaseModel):
    name: str = "image.jpg"
    mime: str = "image/jpeg"
    data: str = ""


class ChatFile(BaseModel):
    name: str = "file.txt"
    mime: str = "text/plain"
    text: str = Field(default="", max_length=300000)


class ChatMcp(BaseModel):
    servers: dict[str, Any] = Field(default_factory=dict)
    url: str = ""
    token: str = ""


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=320000)
    origin: str = ""
    images: list[ChatImage] = Field(default_factory=list)
    files: list[ChatFile] = Field(default_factory=list)
    mcp: ChatMcp | None = None
    model: str = ""


def _with_ui_context(message: str, origin: str = "") -> str:
    origin = str(origin or "").strip().rstrip("/")
    if origin.startswith("http://") or origin.startswith("https://"):
        return f"This user's Home Assistant UI is {origin}.\n\n{message}"
    return message


router = APIRouter()


def create_app(settings: Settings | None = None, providers: dict | None = None) -> FastAPI:
    _configure_logging()
    app = FastAPI(title="AI Workspace", lifespan=lifespan)
    app.state.settings = settings or Settings.from_env()
    app.state.providers_override = providers
    app.include_router(router)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    settings.ensure_dirs()
    store = Store(settings.data_dir / "ai-workspace.sqlite")
    app.state.store = store
    app.state.locks = {}
    runtime = None
    if app.state.providers_override is not None:
        app.state.providers = app.state.providers_override
    else:
        from app.providers.cursor import CursorRuntime, build_providers

        runtime = CursorRuntime(settings)
        app.state.providers = build_providers(settings, runtime)
        logger.info("cursor runtime model=%s mcp_config=%s", settings.model, settings.mcp_config_path)
        if settings.cursor_api_key:
            app.state.warmup = asyncio.create_task(runtime.warm())
    app.state.runtime = runtime
    try:
        yield
    finally:
        warmup = getattr(app.state, "warmup", None)
        if warmup is not None:
            warmup.cancel()
        store.close()
        if runtime is not None:
            await runtime.aclose()


def _user_id(request: Request) -> str:
    settings: Settings = request.app.state.settings
    uid = request.headers.get("x-remote-user-id") or request.headers.get("x-hass-user-id")
    if settings.auth_mode == "ingress":
        if uid:
            return uid
        if request.headers.get("x-ingress-path"):
            return "ingress"
        raise HTTPException(status_code=401, detail="Sign in through Home Assistant.")
    return uid or "local"


def _session_or_404(store: Store, user_id: str, session_id: str) -> Session:
    session = store.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return session


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _public(settings: Settings, exc: BaseException) -> str:
    return redact(str(exc), [settings.cursor_api_key])


@router.get("/api/health")
def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    cursor = request.app.state.providers["cursor"].info
    return {
        "ok": True,
        "auth_mode": settings.auth_mode,
        "model": settings.model,
        "cursor": cursor.available,
    }


@router.get("/api/providers")
def providers(request: Request) -> list[dict]:
    return [item.info.as_dict() for item in request.app.state.providers.values()]


@router.get("/api/sessions")
def list_sessions(request: Request) -> list[dict]:
    store: Store = request.app.state.store
    return [_session_dict(item) for item in store.list_sessions(_user_id(request))]


@router.post("/api/sessions", status_code=201)
def create_session(request: Request, body: SessionCreate) -> dict:
    providers = request.app.state.providers
    provider = body.provider if body.provider in providers else next(iter(providers), "cursor")
    store: Store = request.app.state.store
    session = store.create_session(_user_id(request), provider, body.id)
    return _session_dict(session)


@router.get("/api/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict:
    store: Store = request.app.state.store
    session = _session_or_404(store, _user_id(request), session_id)
    return {
        **_session_dict(session),
        "messages": [_message_dict(item) for item in store.list_messages(session.id)],
    }


@router.patch("/api/sessions/{session_id}")
def rename_session(request: Request, session_id: str, body: SessionUpdate) -> dict:
    store: Store = request.app.state.store
    user_id = _user_id(request)
    session = store.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    if body.pinned is not None:
        session = store.set_pinned(user_id, session_id, body.pinned)
    if body.title:
        session = store.rename_session(user_id, session_id, body.title)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return _session_dict(session)


@router.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(request: Request, session_id: str) -> None:
    store: Store = request.app.state.store
    user_id = _user_id(request)
    if not store.delete_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="Chat not found.")
    runtime = request.app.state.runtime
    if runtime is not None:
        runtime.drop(session_id)


@router.post("/api/sessions/{session_id}/chat")
async def chat(request: Request, session_id: str, body: ChatRequest) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    store: Store = request.app.state.store
    session = _session_or_404(store, _user_id(request), session_id)
    provider = request.app.state.providers.get(session.provider)
    if provider is None:
        provider = next((item for item in request.app.state.providers.values() if item.info.available), None)
    if provider is None:
        raise HTTPException(status_code=400, detail="Unknown provider.")
    lock: asyncio.Lock = request.app.state.locks.setdefault(session.id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="This chat is already waiting on the agent.")
    images = parse_client_images([item.model_dump() for item in body.images])
    files = parse_client_files([item.model_dump() for item in body.files])
    message = caption_for(body.message, len(images), len(files))
    if not message:
        raise HTTPException(status_code=400, detail="Message is empty.")
    logger.info(
        "chat session=%s model=%s mcp=%s files=%s",
        session.id,
        body.model.strip() or settings.model,
        bool(body.mcp and (body.mcp.servers or body.mcp.url)),
        len(files),
    )
    store.add_message(
        session.id,
        "user",
        message,
        json.dumps(image_events(images) + file_events(files), ensure_ascii=False),
    )
    store.rename_if_default(session.id, message.replace("\n", " ").strip())
    outbound = _with_ui_context(attach_files_to_message(message, files), body.origin)
    suggest = getattr(provider, "suggest_title", None)
    want_title = len(store.list_messages(session.id)) <= 1 and callable(suggest)

    def on_agent_id(agent_id: str) -> None:
        store.set_agent_id(session.id, agent_id)
        session.agent_id = agent_id

    await lock.acquire()

    async def generate():
        parts: list[str] = []
        tools: list[dict] = []
        error: str | None = None
        final: str | None = None
        try:
            try:
                async for event in provider.send(
                    session,
                    outbound,
                    on_agent_id,
                    images=images,
                    mcp=body.mcp.model_dump() if body.mcp else None,
                    model=body.model.strip(),
                ):
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
                    yield _sse(str(event["type"]), event)
                    if await request.is_disconnected():
                        break
            except Exception as exc:
                logger.exception("chat failed session=%s", session.id)
                error = _public(settings, exc)
                yield _sse("error", {"type": "error", "message": error})
            answer = (final or "".join(parts)).strip()
            if error and not answer:
                answer = error
            store.add_message(session.id, "assistant", answer, json.dumps(tools, ensure_ascii=False))
            if error is None:
                yield _sse("done", {"type": "done", "answer": answer})
                yield _sse("status", {"type": "status", "text": "Done."})
        finally:
            lock.release()
        if error is None and want_title:
            try:
                raw = await asyncio.wait_for(suggest(message, ""), timeout=12)
            except Exception:
                logger.debug("title generation failed", exc_info=True)
                raw = None
            label = store.apply_generated_title(_user_id(request), session.id, message, clean_title(raw or ""))
            if label:
                yield _sse("title", {"type": "title", "title": label})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/app.js")
def script() -> FileResponse:
    return FileResponse(STATIC / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/app.css")
def styles() -> FileResponse:
    return FileResponse(STATIC / "app.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


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
    return {"id": item.id, "role": item.role, "content": item.content, "events": events, "created_at": item.created_at}


app = create_app()
