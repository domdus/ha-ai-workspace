from __future__ import annotations

from aiohttp import ClientSession, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

try:
    from homeassistant.components.http import KEY_HASS
except ImportError:
    KEY_HASS = "hass"

_SKIP = {"content-length", "transfer-encoding", "connection", "host"}


def _hass(request: web.Request) -> HomeAssistant:
    app = request.app
    if KEY_HASS in app:
        return app[KEY_HASS]
    return app["hass"]


class RuntimeProxyView(HomeAssistantView):
    """Forward chat API calls to the glibc runtime that can install cursor-sdk."""

    requires_auth = True
    url = "/api/ai_workspace/{path:.*}"
    extra_urls = ["/api/ai_workspace"]
    name = "api:ai_workspace:proxy"

    async def get(self, request: web.Request, path: str = "") -> web.StreamResponse:
        return await self._forward(request, path)

    async def post(self, request: web.Request, path: str = "") -> web.StreamResponse:
        return await self._forward(request, path)

    async def delete(self, request: web.Request, path: str = "") -> web.StreamResponse:
        return await self._forward(request, path)

    async def _forward(self, request: web.Request, path: str) -> web.StreamResponse:
        hass = _hass(request)
        base = str(hass.data[DOMAIN]["runtime_url"]).rstrip("/")
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


def register_proxy_views(hass: HomeAssistant) -> None:
    hass.http.register_view(RuntimeProxyView)
