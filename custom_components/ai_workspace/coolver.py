from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession, ClientTimeout

from .mcp_client import McpError, McpHttpClient, _parse_body

_OP = re.compile(r"[^A-Za-z0-9_-]+")
_SKIP = {"/docs", "/redoc", "/openapi.json", "/openapi.yaml"}


class CoolverClient:
    """Vibecode Agent is REST plus an Agent Key. Prefer /mcp if present, else OpenAPI."""

    def __init__(self, http: ClientSession, url: str, headers: dict[str, str] | None = None) -> None:
        self._http = http
        self._url = str(url or "").rstrip("/")
        self._headers = {key: value for key, value in (headers or {}).items() if value}
        self._mcp: McpHttpClient | None = None
        self._ops: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> dict[str, Any]:
        status, _ = await self._request("GET", "/api/health")
        if status < 400:
            return {"protocol": "coolver-rest"}
        for candidate in (f"{self._url}/mcp", self._url):
            mcp = McpHttpClient(self._http, candidate, self._headers)
            try:
                result = await mcp.initialize()
            except McpError:
                continue
            self._mcp = mcp
            return result
        raise McpError(
            f"Vibecode Agent at {self._url} is unreachable (HTTP {status}). "
            "Check the Agent URL and Agent Key."
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._mcp is not None:
            return await self._mcp.list_tools()
        status, spec = await self._request("GET", "/openapi.json")
        if status >= 400 or not isinstance(spec, dict):
            raise McpError(
                "Vibecode Agent answered, but it is not an MCP HTTP server and has no OpenAPI at "
                "/openapi.json. Use Home Assistant MCP Server or HA-MCP, or enable the Agent's Swagger."
            )
        tools = []
        for path, methods in (spec.get("paths") or {}).items():
            if path in _SKIP or not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method not in {"get", "post", "put", "patch", "delete"} or not isinstance(op, dict):
                    continue
                name = _tool_name(str(op.get("operationId") or f"{method}_{path}"))
                if name in self._ops:
                    continue
                desc = str(op.get("summary") or op.get("description") or name)
                schema = _input_schema(op)
                self._ops[name] = {"method": method.upper(), "path": str(path), "schema": schema}
                tools.append({"name": name, "description": desc[:180], "inputSchema": schema})
                if len(tools) >= 48:
                    return tools
        if not tools:
            raise McpError("Vibecode Agent OpenAPI listed no HTTP operations.")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._mcp is not None:
            return await self._mcp.call_tool(name, arguments)
        op = self._ops.get(name)
        if not op:
            raise McpError(f"Unknown Vibecode tool {name}.")
        args = dict(arguments or {})
        path = str(op["path"])
        for key, value in list(args.items()):
            token = "{" + key + "}"
            if token in path:
                path = path.replace(token, quote(str(value), safe=""))
                args.pop(key, None)
        method = str(op["method"])
        if method == "GET":
            status, body = await self._request(method, path, params=args)
        else:
            status, body = await self._request(method, path, json_body=args)
        if status >= 400:
            raise McpError(f"Vibecode HTTP {status}: {str(body)[:300]}")
        return body

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> tuple[int, Any]:
        headers = {"Accept": "application/json", **self._headers}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            resp = await self._http.request(
                method,
                f"{self._url}{path}",
                headers=headers,
                params=params or None,
                json=json_body,
                timeout=ClientTimeout(total=60),
            )
        except (ClientError, TimeoutError, OSError) as exc:
            raise McpError(f"Vibecode Agent at {self._url} is unreachable: {exc}") from exc
        text = await resp.text()
        try:
            body: Any = json.loads(text) if text else {}
        except json.JSONDecodeError:
            try:
                body = _parse_body(text, resp.headers.get("Content-Type", ""))
            except McpError:
                body = text
        return resp.status, body


def _tool_name(raw: str) -> str:
    name = _OP.sub("_", raw).strip("_")[:64]
    return name or "tool"


def _input_schema(op: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in op.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "")
        if not name:
            continue
        schema = param.get("schema") if isinstance(param.get("schema"), dict) else {"type": "string"}
        properties[name] = schema
        if param.get("required"):
            required.append(name)
    body = op.get("requestBody")
    if isinstance(body, dict):
        content = body.get("content") if isinstance(body.get("content"), dict) else {}
        json_body = content.get("application/json") if isinstance(content, dict) else None
        schema = json_body.get("schema") if isinstance(json_body, dict) else None
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            properties.update(schema["properties"])
            extra = schema.get("required")
            if isinstance(extra, list):
                required.extend(str(item) for item in extra if item not in required)
        elif "body" not in properties:
            properties["body"] = {"type": "object"}
    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out
