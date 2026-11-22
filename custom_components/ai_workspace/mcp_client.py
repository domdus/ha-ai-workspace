from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import DEFAULT_TOOL_TIMEOUT_SECONDS, VERSION

logger = logging.getLogger(__name__)

_PROTOCOL = "2025-11-25"
ELICIT_METHOD = "elicitation/create"
ELICIT_MODES = ("form", "url")
# What the user is asked through: form fields, or a link to open (MCP 2025-11-25 elicitation modes).
ELICITATION_CAPABILITY: dict[str, Any] = {"form": {}, "url": {}}
# MCP _meta key for the chat a tools/call belongs to (namespaced, MCP 2025-06-18 _meta rules).
CONVERSATION_META = "io.github.domdus/conversation_id"
# initialize, tools/list and other short requests.
_SHORT_TIMEOUT = 60.0
_MAX_TOOL_PAGES = 50
# Background notifications/cancelled sends; kept so they are not garbage collected mid-flight.
_CANCELS: set[asyncio.Task] = set()


_LANGUAGE_TAG = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


def accept_language(language: str) -> str:
    """Accept-Language for MCP servers: Home Assistant's language first, English as fallback.

    Server-made texts (approval prompts, elicitation field titles) can only be translated by the server.
    "de" -> "de, en;q=0.5"; English alone stays "en"; anything that is not a language tag -> "".
    """
    tag = str(language or "").strip().replace("_", "-")
    if not tag or not _LANGUAGE_TAG.match(tag):
        return ""
    return tag if tag.lower() == "en" else f"{tag}, en;q=0.5"


def with_accept_language(headers: dict[str, str] | None, language: str) -> dict[str, str]:
    """headers plus Accept-Language, unless the connection already sets its own."""
    out = dict(headers or {})
    value = accept_language(language)
    if value and not any(str(key).lower() == "accept-language" for key in out):
        out["Accept-Language"] = value
    return out


class McpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def ha_mcp_trouble(exc: BaseException, hint: str = "") -> str:
    """Plain-language next step for a failed HA-MCP connection."""
    status = getattr(exc, "status", None)
    text = str(exc)
    if status in {401, 403}:
        return hint or (
            "HA-MCP asks for a login. In HA-MCP's Configure, set the authentication mode to "
            "\u201cSecret webhook URL\u201d, or use \u201cSign in with Home Assistant\u201d and chat as an administrator."
        )
    if "response was empty" in text:
        return (
            "The address answered without an MCP reply. When it is HA-MCP's webhook, turn on "
            "\u201cRemote access via webhook\u201d in HA-MCP, or let AI Workspace use HA-MCP's direct address."
        )
    return hint


class McpTimeout(McpError):
    """The server sent neither an answer nor progress for the call's timeout."""


def _messages(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload]
    return [item for item in items if isinstance(item, dict)]


class McpHttpClient:
    """MCP Streamable HTTP client: requests over POST, answers as JSON or an event stream.

    tools/call sends ``_meta.progressToken``; every ``notifications/progress`` for it starts the
    call's timeout again and goes to ``on_progress``. A call that is stopped (task cancelled) or
    times out gets ``notifications/cancelled``.

    ``elicitation/create`` on a call's stream goes to that call's ``on_elicit`` (the user answers in
    the chat); its result is the JSON-RPC answer. While the user is asked, the call's timeout waits.
    A call that is stopped meanwhile answers the open question with ``decline``.
    """

    def __init__(self, http: ClientSession, url: str, headers: dict[str, str] | None = None) -> None:
        self._http = http
        self._url = url.rstrip("/")
        self._id = 0
        self._session_id: str | None = None
        # The version the server chose in initialize; sent as MCP-Protocol-Version afterwards.
        self.protocol_version = ""
        # Questions the server withdrew (notifications/cancelled): no answer goes back for them.
        self._withdrawn: set[asyncio.Task] = set()
        self._headers = {key: value for key, value in (headers or {}).items() if value}
        # Set when the server says its tool list changed (notifications/tools/list_changed).
        self.tools_changed = False

    async def initialize(self) -> dict[str, Any]:
        result = await self.call(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {"elicitation": dict(ELICITATION_CAPABILITY)},
                "clientInfo": {"name": "ai-workspace", "version": VERSION},
            },
        )
        version = result.get("protocolVersion") if isinstance(result, dict) else None
        self.protocol_version = str(version) if isinstance(version, str) and version else ""
        await self.call("notifications/initialized", notify=True)
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """Every page of tools/list (MCP pagination with nextCursor)."""
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _page in range(_MAX_TOOL_PAGES):
            result = await self.call("tools/list", {"cursor": cursor} if cursor else {})
            found = result.get("tools") if isinstance(result, dict) else None
            if isinstance(found, list):
                tools.extend(item for item in found if isinstance(item, dict))
            cursor = result.get("nextCursor") if isinstance(result, dict) else None
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                break
            seen.add(cursor)
        self.tools_changed = False
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        on_progress: Callable[[dict[str, Any]], Any] | None = None,
        conversation_id: str = "",
        on_elicit: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> Any:
        """tools/call. timeout: seconds without an answer or progress (default 120).

        on_elicit asks the user an ``elicitation/create`` of this call; without it the server gets cancel.
        """
        token = f"aiw-{secrets.token_hex(8)}"
        meta: dict[str, Any] = {"progressToken": token}
        if conversation_id:
            meta[CONVERSATION_META] = str(conversation_id)
        params = {"name": name, "arguments": arguments or {}, "_meta": meta}
        return await self.call(
            "tools/call",
            params,
            timeout=float(timeout or DEFAULT_TOOL_TIMEOUT_SECONDS),
            progress_token=token,
            on_progress=on_progress,
            on_elicit=on_elicit,
        )

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            **self._headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        notify: bool = False,
        timeout: float = _SHORT_TIMEOUT,
        progress_token: str = "",
        on_progress: Callable[[dict[str, Any]], Any] | None = None,
        on_elicit: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> Any:
        self._id += 1
        request_id = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params
        loop = asyncio.get_running_loop()
        # Counts from the last sign of life: the request, then each progress notification.
        deadline = [loop.time() + timeout]
        resp = None
        try:
            try:
                resp = await asyncio.wait_for(
                    self._http.post(
                        self._url,
                        json=payload,
                        headers=self._request_headers(),
                        timeout=ClientTimeout(total=None, sock_connect=30),
                    ),
                    timeout,
                )
            except TimeoutError as exc:
                raise McpTimeout(f"MCP server at {self._url} did not answer within {timeout:.0f} s.") from exc
            except (ClientError, OSError) as exc:
                raise McpError(f"MCP server at {self._url} is unreachable: {exc}") from exc
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid
            content_type = resp.headers.get("Content-Type", "")
            if resp.status >= 400:
                text = await resp.text()
                raise McpError(f"MCP HTTP {resp.status}: {text[:300]}", resp.status)
            if notify:
                return {}
            if "text/event-stream" in content_type:
                body = await self._read_stream(
                    resp, request_id, deadline, timeout, progress_token, on_progress, on_elicit
                )
            else:
                remaining = max(0.1, deadline[0] - loop.time())
                try:
                    text = await asyncio.wait_for(resp.text(), remaining)
                except TimeoutError as exc:
                    raise McpTimeout(
                        f"MCP server at {self._url} did not answer within {timeout:.0f} s."
                    ) from exc
                body = _parse_body(text, content_type)
        except McpTimeout:
            if not notify and method != "initialize":
                self._cancel_later(request_id, "timeout")
            raise
        except asyncio.CancelledError:
            # The chat was stopped: tell the server so it can stop working on it.
            if not notify and method != "initialize":
                self._cancel_later(request_id, "stopped by the user")
            raise
        finally:
            if resp is not None:
                resp.release()
        if "error" in body:
            err = body["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise McpError(str(message))
        return body.get("result")

    async def _read_stream(
        self,
        resp: Any,
        request_id: int,
        deadline: list[float],
        timeout: float,
        progress_token: str,
        on_progress: Callable[[dict[str, Any]], Any] | None,
        on_elicit: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Read server-sent events until the answer to request_id comes.

        While a question to the user (elicitation) is open the timeout waits; it starts again
        once the last one is answered.
        """
        loop = asyncio.get_running_loop()
        data: list[str] = []
        last: dict[str, Any] | None = None
        buffer = b""
        ended = False
        asking: set[asyncio.Task] = set()
        # Open questions by their JSON-RPC id, so the server can withdraw one (notifications/cancelled).
        asked: dict[str, asyncio.Task] = {}
        reader: asyncio.Future | None = None
        try:
            while True:
                # One line at a time; a result can be one very long data line, so no readline limit.
                while b"\n" not in buffer and not ended:
                    if reader is None:
                        reader = asyncio.ensure_future(resp.content.readany())
                    if asking:
                        await asyncio.wait({reader, *asking}, return_when=asyncio.FIRST_COMPLETED)
                        answered = {task for task in asking if task.done()}
                        asking -= answered
                        if answered and not asking:
                            deadline[0] = loop.time() + timeout
                        if not reader.done():
                            continue
                    else:
                        remaining = deadline[0] - loop.time()
                        if remaining <= 0:
                            raise McpTimeout(f"MCP server at {self._url} did not answer within {timeout:.0f} s.")
                        done, _pending = await asyncio.wait({reader}, timeout=remaining)
                        if reader not in done:
                            raise McpTimeout(
                                f"MCP server at {self._url} did not answer within {timeout:.0f} s."
                            )
                    chunk = reader.result()
                    reader = None
                    if chunk:
                        buffer += chunk
                    else:
                        ended = True
                if b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    raw += b"\n"
                else:
                    raw, buffer = buffer, b""
                line = raw.decode("utf-8", "replace").rstrip("\r\n") if raw else ""
                if raw and line.startswith("data:"):
                    data.append(line[5:].lstrip())
                    continue
                if raw and line:
                    continue
                if data:
                    chunk = "\n".join(data).strip()
                    data = []
                    if chunk and chunk != "[DONE]":
                        try:
                            payload = json.loads(chunk)
                        except json.JSONDecodeError:
                            payload = None
                        for message in _messages(payload):
                            if message.get("id") == request_id and ("result" in message or "error" in message):
                                return message
                            if message.get("method") == ELICIT_METHOD and "id" in message:
                                task = loop.create_task(self._elicit(message, on_elicit))
                                asking.add(task)
                                asked[json.dumps(message.get("id"))] = task
                                continue
                            if message.get("method") == "notifications/cancelled":
                                params = message.get("params") if isinstance(message.get("params"), dict) else {}
                                withdrawn = asked.pop(json.dumps(params.get("requestId")), None)
                                if withdrawn is not None and not withdrawn.done():
                                    # The server no longer waits: close the card, send no answer.
                                    self._withdrawn.add(withdrawn)
                                    withdrawn.cancel()
                                continue
                            if self._on_message(message, progress_token, on_progress):
                                deadline[0] = loop.time() + timeout
                            if "result" in message or "error" in message:
                                last = message
                if not raw:
                    if last is not None:
                        return last
                    raise McpError("MCP SSE response was empty.")
        finally:
            if reader is not None and not reader.done():
                reader.cancel()
            # The call is over (answered, stopped, failed): its open questions are declined.
            for task in asking:
                task.cancel()

    async def _elicit(
        self,
        message: dict[str, Any],
        on_elicit: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None,
    ) -> None:
        """Ask the user an elicitation/create and send the JSON-RPC answer to the server."""
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        mode = str(params.get("mode") or "form")
        answer: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if mode not in ELICIT_MODES:
            answer["error"] = {"code": -32602, "message": f"Elicitation mode {mode!r} is not supported."}
            self._send_later(answer)
            return
        if on_elicit is None:
            # No one to ask (a task run, a check): the user did not answer.
            answer["result"] = {"action": "cancel"}
            self._send_later(answer)
            return
        try:
            result = await on_elicit(dict(params))
        except asyncio.CancelledError:
            # Stopped while the user was asked: the server must not wait for an answer that never comes.
            current = asyncio.current_task()
            if current in self._withdrawn:
                self._withdrawn.discard(current)
            else:
                self._send_later({**answer, "result": {"action": "decline"}})
            raise
        except Exception:  # noqa: BLE001 - a broken card must not leave the server waiting
            logger.warning("MCP elicitation from %s could not be shown", self._url, exc_info=True)
            result = {"action": "cancel"}
        if not isinstance(result, dict) or result.get("action") not in {"accept", "decline", "cancel"}:
            result = {"action": "cancel"}
        out: dict[str, Any] = {"action": result["action"]}
        if result["action"] == "accept" and mode == "form":
            out["content"] = dict(result.get("content") or {})
        answer["result"] = out
        self._send_later(answer)

    def _on_message(
        self,
        message: dict[str, Any],
        progress_token: str,
        on_progress: Callable[[dict[str, Any]], Any] | None,
    ) -> bool:
        """Handle a server message inside a call's stream. True for progress on this call."""
        method = message.get("method")
        if not isinstance(method, str):
            return False
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if "id" in message:
            # A server request: ping is answered (elicitation/create is read by _read_stream),
            # everything else this client does not offer.
            if method == "ping":
                answer: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"], "result": {}}
            else:
                answer = {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"{method} is not supported by this client."},
                }
            self._send_later(answer)
            return False
        if method == "notifications/progress":
            if not progress_token or str(params.get("progressToken")) != progress_token:
                return False
            if on_progress is not None:
                try:
                    on_progress(dict(params))
                except Exception:  # noqa: BLE001 - progress display must never break the call
                    logger.debug("MCP progress handler failed", exc_info=True)
            return True
        if method == "notifications/tools/list_changed":
            self.tools_changed = True
        return False

    def _send_later(self, message: dict[str, Any]) -> None:
        task = asyncio.get_running_loop().create_task(self._post_message(message))
        _CANCELS.add(task)
        task.add_done_callback(_CANCELS.discard)

    def _cancel_later(self, request_id: int, reason: str) -> None:
        """notifications/cancelled for an open request, sent in the background."""
        logger.info("MCP request %s to %s cancelled: %s", request_id, self._url, reason)
        self._send_later(
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": request_id, "reason": reason},
            }
        )

    async def _post_message(self, message: dict[str, Any]) -> None:
        try:
            resp = await self._http.post(
                self._url,
                json=message,
                headers=self._request_headers(),
                timeout=ClientTimeout(total=10),
            )
            resp.release()
        except (ClientError, TimeoutError, OSError) as exc:
            logger.debug("MCP message to %s not delivered: %s", self._url, exc)
