"""Sign-in per engine: one API shape for Claude, OpenAI Codex and any engine that gets a plan login later.

    GET    /api/auth                       every engine's status
    GET    /api/auth/{engine}              status: where the credential comes from, never the secret
    POST   /api/auth/{engine}/login        start; returns the link to open (and a user code for
                                           device-code flows)
    GET    /api/auth/{engine}/login/{id}   state of that sign-in (?wait=N long-polls device flows)
    POST   /api/auth/{engine}/login/{id}   {"code": "..."} for paste-back flows
    DELETE /api/auth/{engine}/login/{id}   cancel
    DELETE /api/auth/{engine}              sign out (forget the stored credential)

`flow` says what the UI must do: "paste_code" (Claude: open url, paste the code shown there back) or
"device_code" (Codex: open url, enter user_code there, then poll). Engines without a plan login
(Cursor: API key only) answer the status calls and refuse login with 501 not_supported.

A login is: {id, engine, flow, status, url, user_code?, expires_in?, error?}. status is one of
starting, awaiting_code, verifying, succeeded, failed, cancelled, expired.

Stored credentials live in the runtime's data folder (owner-only files), not in Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.settings import Settings

logger = logging.getLogger(__name__)

# What each LoginError key means over HTTP.
_STATUS = {
    "not_supported": 501,
    "cli_missing": 501,
    "no_link": 502,
    "no_code": 502,
    "login_failed": 502,
    "bad_code": 400,
    "code_rejected": 400,
    "too_many_attempts": 400,
    "busy": 409,
    "expired": 410,
    "timeout": 504,
}


class LoginCode(BaseModel):
    code: str = Field(default="", max_length=600)


class EngineAuth:
    """No plan login: status only."""

    name = ""
    flow = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def offers_login(self) -> bool:
        """Listed under "login" in /api/health: the agent form then offers the plan sign-in."""
        return bool(self.flow)

    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    async def start(self) -> dict[str, Any]:
        raise _error("not_supported")

    def get(self, login_id: str, wait: int = 0) -> dict[str, Any]:
        del login_id, wait
        raise _error("not_supported")

    async def submit(self, login_id: str, code: str) -> dict[str, Any]:
        del login_id, code
        raise _error("not_supported")

    def cancel(self, login_id: str) -> bool:
        del login_id
        return False

    def logout(self) -> bool:
        return False

    def close(self) -> None:
        return None


class CursorAuth(EngineAuth):
    """The Cursor SDK has no plan sign-in; the agent or the add-on carries an API key."""

    name = "cursor"

    def status(self) -> dict[str, Any]:
        has_key = bool((self.settings.cursor_api_key or "").strip())
        return {
            "engine": self.name,
            "ready": has_key,
            "credential": "settings" if has_key else "none",
            "kind": "api" if has_key else None,
            "signed_in": None,
            "overridden": False,
            "login": {"supported": False, "reason": "api_key_only"},
        }


class ClaudeAuth(EngineAuth):
    """Claude Code's plan OAuth through `claude setup-token`, headless (paste-back code)."""

    name = "claude"
    flow = "paste_code"

    def __init__(self, settings: Settings, manager=None) -> None:
        super().__init__(settings)
        if manager is None:
            from app.claude_login import LoginManager

            manager = LoginManager()
        self.manager = manager

    def _login(self, login) -> dict[str, Any]:
        return {**login.as_dict(), "engine": self.name, "flow": self.flow}

    def status(self) -> dict[str, Any]:
        from app.claude_login import token_info
        from app.providers.claude import auth_mode, credential_source, runtime_credential

        credential = runtime_credential(self.settings)
        source = credential_source(self.settings)
        signed_in = token_info(self.settings.claude_token_path)
        pending = self.manager.current()
        return {
            "engine": self.name,
            "ready": bool(credential),
            "credential": source,
            # plan | api: how the runtime bills Claude with its own credential.
            "kind": auth_mode(credential) if credential else None,
            "signed_in": signed_in,
            # Up to 1.6.0b11 a Plan token in the App options won over a sign-in. Now a sign-in always
            # wins over the runtime's environment, so nothing overrides it. Kept for older integrations.
            "overridden": False,
            "login": {
                "supported": True,
                "flow": self.flow,
                "available": self.manager.available(),
                "pending": self._login(pending) if pending else None,
            },
        }

    async def start(self) -> dict[str, Any]:
        from app.claude_login import LoginError

        try:
            login = await self.manager.start()
        except LoginError as exc:
            raise _error(exc.key) from None
        logger.info("Claude sign-in started")
        return self._login(login)

    def get(self, login_id: str, wait: int = 0) -> dict[str, Any]:
        # Paste-back: nothing happens until the code arrives, so there is nothing to wait for.
        del wait
        from app.claude_login import LoginError

        try:
            login = self.manager.get(login_id)
        except LoginError as exc:
            raise _error(exc.key) from None
        return self._login(login)

    async def submit(self, login_id: str, code: str) -> dict[str, Any]:
        from app.claude_login import LoginError, save_token

        try:
            token = await self.manager.finish(login_id, code)
        except LoginError as exc:
            raise _error(exc.key) from None
        try:
            save_token(self.settings.claude_token_path, token)
        except (LoginError, OSError):
            logger.error("Claude sign-in finished but the token could not be saved")
            raise _error("login_failed") from None
        logger.info("Claude sign-in finished; Plan token saved")
        login = self.manager.get(login_id)
        return {**self._login(login), "auth": self.status()}

    def cancel(self, login_id: str) -> bool:
        return self.manager.cancel(login_id)

    def logout(self) -> bool:
        from app.claude_login import forget_token

        self.manager.close()
        removed = forget_token(self.settings.claude_token_path)
        if removed:
            logger.info("Claude sign-in removed")
        return removed

    def close(self) -> None:
        self.manager.close()


class CodexAuth(EngineAuth):
    """OpenAI Codex: "Sign in with ChatGPT" through the device-code flow; auth.json in CODEX_HOME."""

    name = "codex"
    flow = "device_code"

    def __init__(self, settings: Settings, manager=None) -> None:
        super().__init__(settings)
        if manager is None:
            from app.codex_login import CodexLoginManager

            manager = CodexLoginManager(settings)
        self.manager = manager

    def _login(self, login) -> dict[str, Any]:
        return {**login.as_dict(), "engine": self.name, "flow": self.flow}

    def offers_login(self) -> bool:
        # Only when the Codex SDK and its CLI are in this image: otherwise the sign-in could not run.
        return self.manager.available()

    def status(self) -> dict[str, Any]:
        from app.codex_login import credential_source, signed_in_info

        source = credential_source(self.settings)
        signed = signed_in_info(self.settings)
        pending = self.manager.current()
        return {
            "engine": self.name,
            "ready": source != "none",
            # signed-in: auth.json in the runtime's data folder; settings: an OpenAI API key option.
            "credential": {"chatgpt": "signed-in", "api-key": "signed-in", "env-api": "settings"}.get(source, "none"),
            "kind": {"chatgpt": "plan", "api-key": "api", "env-api": "api"}.get(source),
            "plan": (signed or {}).get("plan"),
            "signed_in": signed,
            # auth.json always wins over an API key option, so nothing in the options hides a sign-in.
            "overridden": False,
            "login": {
                "supported": True,
                "flow": self.flow,
                "available": self.manager.available(),
                "pending": self._login(pending) if pending else None,
            },
        }

    async def start(self) -> dict[str, Any]:
        from app.codex_login import CodexLoginError

        try:
            login = await self.manager.start()
        except CodexLoginError as exc:
            raise _error(exc.key) from None
        logger.info("Codex sign-in started (device code)")
        return self._login(login)

    async def get(self, login_id: str, wait: int = 0) -> dict[str, Any]:
        from app.codex_login import CodexLoginError

        try:
            login = await self.manager.wait(login_id, wait)
        except CodexLoginError as exc:
            raise _error(exc.key) from None
        out = self._login(login)
        if login.status == "succeeded":
            out["auth"] = self.status()
        return out

    async def submit(self, login_id: str, code: str) -> dict[str, Any]:
        # Device code: the code is typed at OpenAI, nothing comes back here. Poll the state instead.
        del login_id, code
        raise _error("not_supported")

    async def cancel(self, login_id: str) -> bool:
        return await self.manager.cancel(login_id)

    async def logout(self) -> bool:
        from app.codex_login import forget_auth

        await self.manager.aclose()
        removed = forget_auth(self.settings)
        if removed:
            logger.info("Codex sign-in removed")
        return removed

    async def aclose(self) -> None:
        await self.manager.aclose()


def _error(key: str) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(key, 502), detail=key)


def build_engines(settings: Settings) -> dict[str, EngineAuth]:
    return {"claude": ClaudeAuth(settings), "codex": CodexAuth(settings), "cursor": CursorAuth(settings)}


def login_engines(engines: dict[str, EngineAuth]) -> list[str]:
    """Engines with a plan sign-in, for /api/health."""
    return [name for name, item in engines.items() if item.offers_login()]


def close_engines(engines: dict[str, EngineAuth] | None) -> None:
    for item in (engines or {}).values():
        try:
            item.close()
        except Exception:  # noqa: BLE001 - shutting down
            logger.debug("closing %s sign-in failed", item.name, exc_info=True)


async def aclose_engines(engines: dict[str, EngineAuth] | None) -> None:
    """Shutting down: stop every sign-in that still runs (Codex's needs its app-server closed)."""
    close_engines(engines)
    for item in (engines or {}).values():
        closer = getattr(item, "aclose", None)
        if callable(closer):
            try:
                await closer()
            except Exception:  # noqa: BLE001 - shutting down
                logger.debug("closing %s sign-in failed", item.name, exc_info=True)


router = APIRouter()


def engines_for(app) -> dict[str, EngineAuth]:
    """The app's sign-in engines, built on first use."""
    engines = getattr(app.state, "auth", None)
    if engines is None:
        engines = build_engines(app.state.settings)
        app.state.auth = engines
    return engines


def _engines(request: Request) -> dict[str, EngineAuth]:
    return engines_for(request.app)


def _engine(request: Request, engine: str) -> EngineAuth:
    found = _engines(request).get(str(engine or "").strip().lower())
    if found is None:
        raise HTTPException(status_code=404, detail="unknown_engine")
    return found


@router.get("/api/auth")
def auth_all(request: Request) -> dict[str, Any]:
    return {"engines": {name: item.status() for name, item in _engines(request).items()}}


@router.get("/api/auth/{engine}")
def auth_status(request: Request, engine: str) -> dict[str, Any]:
    return _engine(request, engine).status()


@router.post("/api/auth/{engine}/login")
async def auth_login_start(request: Request, engine: str) -> dict[str, Any]:
    return await _engine(request, engine).start()


@router.get("/api/auth/{engine}/login/{login_id}")
async def auth_login_state(request: Request, engine: str, login_id: str, wait: int = 0) -> dict[str, Any]:
    item = _engine(request, engine)
    return await _maybe(item.get(login_id, min(max(int(wait or 0), 0), 120)))


@router.post("/api/auth/{engine}/login/{login_id}")
async def auth_login_code(request: Request, engine: str, login_id: str, body: LoginCode) -> dict[str, Any]:
    return await _engine(request, engine).submit(login_id, body.code)


async def _maybe(result):
    return await result if asyncio.iscoroutine(result) else result


@router.delete("/api/auth/{engine}/login/{login_id}", status_code=204)
async def auth_login_cancel(request: Request, engine: str, login_id: str) -> None:
    await _maybe(_engine(request, engine).cancel(login_id))


@router.delete("/api/auth/{engine}")
async def auth_logout(request: Request, engine: str) -> dict[str, Any]:
    item = _engine(request, engine)
    removed = await _maybe(item.logout())
    return {"removed": bool(removed), "auth": item.status()}
