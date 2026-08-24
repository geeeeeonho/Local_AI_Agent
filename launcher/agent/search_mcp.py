from __future__ import annotations

import html
import ipaddress
import json
import os
import socket
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

SERVER_NAME = "local_search"
SERVER_VERSION = "1"
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_SEARXNG_URL = "http://127.0.0.1:8888"
DEFAULT_TIMEOUT = 25.0
DEFAULT_PAGE_LIMIT = 12000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def _read_json_url(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Local_AI_Agent/1 local-search-mcp"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": bool(is_error),
    }


def _rpc_result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _rpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return _text_result("query is required", is_error=True)
    try:
        limit = max(1, min(int(arguments.get("limit", 5)), 10))
    except (TypeError, ValueError):
        limit = 5

    base = os.environ.get("SEARXNG_URL", DEFAULT_SEARXNG_URL).rstrip("/")
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    timeout = float(os.environ.get("LOCAL_SEARCH_TIMEOUT", DEFAULT_TIMEOUT))
    try:
        payload = _read_json_url(f"{base}/search?{params}", timeout=timeout)
    except Exception as exc:
        return _text_result(f"SearXNG search failed: {type(exc).__name__}: {exc}", is_error=True)

    rows: list[dict[str, str]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        if not url:
            continue
        rows.append({"title": title, "url": url, "snippet": snippet})
        if len(rows) >= limit:
            break
    return _text_result(json.dumps(rows, ensure_ascii=False))


def _is_public_http_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False, "invalid URL"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "only http/https URLs are allowed"
    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed"
    host = parsed.hostname
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except OSError as exc:
        return False, f"host resolution failed: {exc}"
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False, "private/local network URLs are not allowed"
    return True, ""


def _fetch_page(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    allowed, reason = _is_public_http_url(url)
    if not allowed:
        return _text_result(reason, is_error=True)
    timeout = float(os.environ.get("LOCAL_SEARCH_TIMEOUT", DEFAULT_TIMEOUT))
    limit = int(os.environ.get("LOCAL_SEARCH_PAGE_LIMIT", DEFAULT_PAGE_LIMIT))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Local_AI_Agent/1 local-search-mcp"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            raw = response.read(max(limit * 4, limit))
    except Exception as exc:
        return _text_result(f"page fetch failed: {type(exc).__name__}: {exc}", is_error=True)

    text = raw.decode("utf-8", "replace")
    if "html" in content_type or "<html" in text[:1000].lower():
        parser = _TextExtractor()
        try:
            parser.feed(text)
            text = "\n".join(parser.parts)
        except Exception:
            text = html.unescape(text)
    text = text.strip()[:limit]
    return _text_result(json.dumps({"url": url, "text": text}, ensure_ascii=False))


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search",
            "description": "Search the current web through Local_AI_Agent's local SearXNG service. Never put private local content, credentials, file contents, or identifying local paths in the query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Public web search query"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "fetch_page",
            "description": "Fetch readable text from one public http/https page returned by search. Local/private network addresses are rejected.",
            "inputSchema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    ]


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    message_id = message.get("id")
    if message_id is None:
        return None
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        protocol = str(requested or PROTOCOL_VERSION)
        return _rpc_result(
            message_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _rpc_result(message_id, {})
    if method == "tools/list":
        return _rpc_result(message_id, {"tools": _tools()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        if name == "search":
            return _rpc_result(message_id, _search(arguments))
        if name == "fetch_page":
            return _rpc_result(message_id, _fetch_page(arguments))
        return _rpc_result(message_id, _text_result(f"unknown tool: {name}", is_error=True))
    return _rpc_error(message_id, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            response = handle_request(message)
        except Exception as exc:
            response = _rpc_error(None, -32700, f"invalid request: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
