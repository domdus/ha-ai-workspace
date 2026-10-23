"""Internet tools for cloud agents with Allow internet on: fetch a page, search the web.

Only public addresses are reachable. Names that resolve to a private, loopback or
link-local address are refused, and every redirect is checked again, so the model
cannot reach the router, the NAS or Home Assistant itself through these tools.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from aiohttp.resolver import DefaultResolver

from .mcp_client import McpError

_LOGGER = logging.getLogger(__name__)
TOOL_FETCH = "web_fetch"
TOOL_SEARCH = "web_search"
_SEARCH_URL = "https://html.duckduckgo.com/html/"
_MAX_BYTES = 2_000_000
_MAX_REDIRECTS = 5
_DEFAULT_CHARS = 12_000
_MAX_CHARS = 40_000
_SEARCH_RESULTS = 8
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AI-Workspace-HomeAssistant/1.0)",
    "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.5",
}
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml", "application/rss+xml")
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table"}


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global and not address.is_multicast


class _PublicResolver(DefaultResolver):
    """DNS answers that point into the local network are dropped before connecting."""

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict[str, Any]]:
        found = await super().resolve(host, port, family)
        allowed = [item for item in found if public_ip(str(item.get("host") or ""))]
        if not allowed:
            raise OSError(f"{host} is not a public address.")
        return allowed


def _check_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise McpError("Only http and https addresses work.")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host.lower() in {"localhost"} or host.lower().endswith((".local", ".lan", ".internal", ".home.arpa")):
            raise McpError("Local network addresses are blocked.") from None
        return parsed.geturl()
    if not public_ip(host):
        raise McpError("Local network addresses are blocked.")
    return parsed.geturl()


class _Text(HTMLParser):
    """Page text without scripts and styles. Prefers <main>/<article> so menus do not eat the budget."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_main = 0
        self._in_title = False

    def _add(self, text: str) -> None:
        self.parts.append(text)
        if self._in_main:
            self.main.append(text)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in {"main", "article"}:
            self._in_main += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._add("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in {"main", "article"} and self._in_main:
            self._in_main -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._add("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._add(data)

    def text(self) -> str:
        main = _tidy("".join(self.main))
        return main if len(main) >= 200 else _tidy("".join(self.parts))


def _tidy(joined: str) -> str:
    lines = (" ".join(line.split()) for line in joined.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line for line in lines if line)).strip()


class _Results(HTMLParser):
    """DuckDuckGo HTML results: result__a links and result__snippet text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._field = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        classes = str(values.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self.rows.append({"title": "", "url": _result_url(str(values.get("href") or "")), "snippet": ""})
            self._field = "title"
        elif "result__snippet" in classes and self.rows:
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "td", "div"}:
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._field and self.rows:
            self.rows[-1][self._field] += data


def _result_url(href: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<target>."""
    parsed = urlparse(href if "//" in href else f"https:{href}")
    target = parse_qs(parsed.query).get("uddg")
    return target[0] if target else href


class WebClient:
    """In-process tool client with the same shape as McpHttpClient for the API loop."""

    async def initialize(self) -> dict[str, Any]:
        return {}

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": TOOL_FETCH,
                "description": (
                    "Fetch a public web page and return its text. For documentation, prices, release notes "
                    "or anything outside this Home Assistant. Not for the house: use the Home Assistant tools."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full http(s) address."},
                        "max_chars": {
                            "type": "integer",
                            "description": f"Longest text to return (default {_DEFAULT_CHARS}, max {_MAX_CHARS}).",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": TOOL_SEARCH,
                "description": (
                    "Search the web and return titles, links and snippets. Follow up with web_fetch on a link "
                    "when the snippet is not enough."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "What to search for."}},
                    "required": ["query"],
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        args = arguments or {}
        if name == TOOL_FETCH:
            return await self._fetch(str(args.get("url") or ""), args.get("max_chars"))
        if name == TOOL_SEARCH:
            return await self._search(str(args.get("query") or ""))
        raise McpError(f"Unknown web tool: {name}")

    def _session(self) -> ClientSession:
        return ClientSession(
            connector=TCPConnector(resolver=_PublicResolver()),
            timeout=ClientTimeout(total=20),
            headers=_HEADERS,
        )

    async def _get(self, http: ClientSession, url: str, data: dict[str, str] | None = None) -> tuple[str, str, bytes]:
        """Follow redirects one by one so each hop is checked."""
        method = "POST" if data else "GET"
        for _hop in range(_MAX_REDIRECTS + 1):
            url = _check_url(url)
            try:
                async with http.request(method, url, data=data, allow_redirects=False) as resp:
                    if resp.status in {301, 302, 303, 307, 308} and resp.headers.get("Location"):
                        url = urljoin(url, resp.headers["Location"])
                        if resp.status == 303:
                            method, data = "GET", None
                        continue
                    if resp.status >= 400:
                        raise McpError(f"The page answered HTTP {resp.status}.")
                    body = bytearray()
                    async for chunk in resp.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) >= _MAX_BYTES:
                            break
                    return str(resp.url), resp.headers.get("Content-Type", ""), bytes(body[:_MAX_BYTES])
            except (ClientError, TimeoutError, OSError) as exc:
                raise McpError(f"Could not open {urlparse(url).hostname}: {exc}") from None
        raise McpError("Too many redirects.")

    async def _fetch(self, url: str, max_chars: Any = None) -> dict[str, Any]:
        try:
            limit = max(500, min(int(max_chars or _DEFAULT_CHARS), _MAX_CHARS))
        except (TypeError, ValueError):
            limit = _DEFAULT_CHARS
        async with self._session() as http:
            final, kind, body = await self._get(http, url)
        kind = kind.lower()
        if kind and not kind.startswith(_TEXT_TYPES):
            raise McpError(f"That address is not a text page ({kind.split(';')[0]}).")
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", kind)
        if match:
            charset = match.group(1)
        try:
            raw = body.decode(charset, errors="replace")
        except LookupError:
            raw = body.decode("utf-8", errors="replace")
        title = ""
        if "html" in kind or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            parser = _Text()
            parser.feed(raw)
            text, title = parser.text(), " ".join(parser.title.split())
        else:
            text = raw.strip()
        return {
            "url": final,
            "title": title,
            "text": text[:limit],
            "truncated": len(text) > limit,
        }

    async def _search(self, query: str) -> dict[str, Any]:
        query = " ".join(query.split())
        if not query:
            raise McpError("Provide a query.")
        async with self._session() as http:
            _final, _kind, body = await self._get(http, _SEARCH_URL, data={"q": query})
        parser = _Results()
        parser.feed(body.decode("utf-8", errors="replace"))
        rows = [
            {key: " ".join(value.split()) for key, value in row.items()}
            for row in parser.rows
            if row.get("url", "").startswith("http")
        ][:_SEARCH_RESULTS]
        if not rows:
            _LOGGER.debug("web search returned no parsable results for %r", query)
            return {"results": [], "note": "The search returned nothing. Try other words, or web_fetch a known address."}
        return {"results": rows}
