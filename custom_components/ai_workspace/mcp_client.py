from __future__ import annotations

import json
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import VERSION

_PROTOCOL = "2025-03-26"


class McpError(RuntimeError):
    pass


def _parse_body(text: str, content_type: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if "text/event-stream" in (content_type or "") or raw.startswith("event:") or "\ndata:" in raw:
        payload = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    payload = json.loads(chunk)
        if payload is None:
            raise McpError("MCP SSE response was empty.")
        return payload
    if not raw:
        raise McpError("MCP response was empty.")
    return json.loads(raw)


class McpHttpClient:
    def __init__(self, http: ClientSession, url: str, headers: dict[str, str] | None = None) -> None:
        self._http = http
        self._url = url.rstrip("/")
        self._id = 0
        self._session_id: str | None = None
        self._headers = {key: value for key, value in (headers or {}).items() if value}

    async def initialize(self) -> dict[str, Any]:
        result = await self.call(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "ai-workspace", "version": VERSION},
            },
        )
        await self.call("notifications/initialized", notify=True)
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.call("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("tools/call", {"name": name, "arguments": arguments or {}})

    async def call(self, method: str, params: dict | None = None, *, notify: bool = False) -> Any:
        self._id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            payload["id"] = self._id
        if params is not None:
            payload["params"] = params
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **self._headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = await self._http.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=ClientTimeout(total=60),
            )
        except (ClientError, TimeoutError, OSError) as exc:
            raise McpError(f"MCP server at {self._url} is unreachable: {exc}") from exc
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        text = await resp.text()
        if resp.status >= 400:
            raise McpError(f"MCP HTTP {resp.status}: {text[:300]}")
        if notify:
            return {}
        body = _parse_body(text, resp.headers.get("Content-Type", ""))
        if "error" in body:
            err = body["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise McpError(str(message))
        return body.get("result")
