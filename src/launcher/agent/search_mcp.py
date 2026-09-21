from __future__ import annotations

import html
import json
import os
import re
# 이름 해석의 정본 핸들. 직접 호출하지 않아도, 보안 테스트가 이 속성에
# sentinel 을 꽂아 "검증 전에 DNS 를 타지 않는다" 를 확인한다.
import socket  # noqa: F401
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

try:
    from ..privacy_policy import blocked_outbound_reason
except Exception:
    try:
        from privacy_policy import blocked_outbound_reason  # type: ignore
    except Exception:
        def blocked_outbound_reason(text: str) -> str | None:
            return "blocked outbound privacy policy unavailable"

try:
    from . import web_safety
except Exception:
    import web_safety  # type: ignore

SERVER_NAME = "local_search"
SERVER_VERSION = "1"
PROTOCOL_VERSION = "2025-06-18"
DEFAULT_SEARXNG_URL = "http://127.0.0.1:8888"
DEFAULT_TIMEOUT = 25.0
DEFAULT_PAGE_LIMIT = 12000
_CHARSET_RE = re.compile(rb"(?i)charset\s*=\s*[\"']?\s*([a-z0-9._-]+)")
_CHARSET_ALIASES = {"euc-kr": "cp949", "euckr": "cp949", "ks_c_5601-1987": "cp949", "ks_c_5601-1989": "cp949", "ms949": "cp949", "x-windows-949": "cp949", "shift_jis": "cp932", "sjis": "cp932", "gb2312": "gbk"}
_REDIRECT_STATUS = {301, 302, 303, 307, 308}


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


def _network_mode() -> str:
    mode = (os.environ.get("LOCAL_AI_NETWORK_MODE") or os.environ.get("NET_MODE") or "warp").strip().lower()
    return mode if mode in {"warp", "tor", "direct", "block"} else "warp"


def _network_blocked() -> bool:
    return _network_mode() == "block"


def _read_json_url(url: str, *, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Local_AI_Agent/1 local-search-mcp"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _decode_body(raw: bytes, content_type: str = "") -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    declared = ""
    match = re.search(r"(?i)charset\s*=\s*[\"']?\s*([a-z0-9._-]+)", content_type or "")
    if match:
        declared = match.group(1).lower()
    if not declared:
        meta = _CHARSET_RE.search(raw[:4096])
        if meta:
            declared = meta.group(1).decode("ascii", "ignore").lower()
    declared = _CHARSET_ALIASES.get(declared, declared)
    candidates = [declared] if declared else []
    candidates.extend(["utf-8", "cp949", "cp932", "gbk"])
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


def _rpc_result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _rpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    if _network_blocked():
        return _text_result("network mode block: public web search is disabled", is_error=True)
    query = str(arguments.get("query") or "").strip()
    if not query:
        return _text_result("query is required", is_error=True)
    reason = blocked_outbound_reason(query)
    if reason:
        return _text_result(reason, is_error=True)
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
        if not url:
            continue
        rows.append({"title": str(item.get("title") or "").strip(), "url": url, "snippet": str(item.get("content") or item.get("snippet") or "").strip()})
        if len(rows) >= limit:
            break
    return _text_result(json.dumps(rows, ensure_ascii=False))


def _resolver_for_mode(mode: str):
    if mode in {"warp", "tor"}:
        return web_safety.ProtectedDoHResolver.from_environment(timeout=float(os.environ.get("LOCAL_SEARCH_TIMEOUT", DEFAULT_TIMEOUT)))
    return None


def _validation(url: str, mode: str, resolver=None):
    return web_safety.validate_outbound_url(url, network_mode=mode, resolver=resolver)


def _privacy_preflight(url: str) -> tuple[str | None, str | None]:
    raw = str(url or "").strip()
    reason = blocked_outbound_reason(raw)
    if reason:
        return reason, None
    normalized = web_safety.normalize_outbound_url(raw)
    if not normalized.ok:
        return normalized.reason, None
    for view in (normalized.url, urllib.parse.unquote(normalized.url)):
        reason = blocked_outbound_reason(view)
        if reason:
            return reason, None
    return None, normalized.url


def _fetch_with_request(url: str, *, mode: str, timeout: float, limit: int, resolver=None) -> tuple[str, bytes, str] | str:
    current = url
    for _ in range(6):
        privacy_reason, normalized_url = _privacy_preflight(current)
        if privacy_reason:
            return privacy_reason
        validated = _validation(normalized_url or current, mode, resolver=resolver)
        if not validated.ok:
            return validated.reason
        try:
            request_fn = web_safety.protected_request if mode in {"warp", "tor"} else web_safety.direct_request
            response = request_fn(validated, timeout=timeout, max_bytes=max(limit * 4, limit))
        except Exception as exc:
            return f"page fetch failed: {type(exc).__name__}: {exc}"
        if response.status in _REDIRECT_STATUS:
            location = response.headers.get("location", "").strip()
            if not location:
                return "page fetch failed: redirect without location"
            current = urllib.parse.urljoin(validated.url, location)
            continue
        return validated.url, response.body, response.headers.get("content-type", "")
    return "page fetch failed: too many redirects"


def _fetch_direct(url: str, *, timeout: float, limit: int) -> tuple[str, bytes, str] | str:
    return _fetch_with_request(url, mode="direct", timeout=timeout, limit=limit)


def _fetch_protected(url: str, *, mode: str, timeout: float, limit: int) -> tuple[str, bytes, str] | str:
    try:
        resolver = _resolver_for_mode(mode)
    except Exception:
        return "protected resolver unavailable"
    return _fetch_with_request(url, mode=mode, timeout=timeout, limit=limit, resolver=resolver)


def _fetch_page(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = _network_mode()
    if mode == "block":
        return _text_result("network mode block: public page fetch is disabled", is_error=True)
    url = str(arguments.get("url") or "").strip()
    privacy_reason = blocked_outbound_reason(url)
    if privacy_reason:
        return _text_result(privacy_reason, is_error=True)
    timeout = float(os.environ.get("LOCAL_SEARCH_TIMEOUT", DEFAULT_TIMEOUT))
    limit = int(os.environ.get("LOCAL_SEARCH_PAGE_LIMIT", DEFAULT_PAGE_LIMIT))
    fetched = _fetch_protected(url, mode=mode, timeout=timeout, limit=limit) if mode in {"warp", "tor"} else _fetch_direct(url, timeout=timeout, limit=limit)
    if isinstance(fetched, str):
        return _text_result(fetched, is_error=True)
    final_url, raw, content_type = fetched
    text = _decode_body(raw, content_type)
    if "html" in content_type.lower() or "<html" in text[:1000].lower():
        parser = _TextExtractor()
        try:
            parser.feed(text)
            text = "\n".join(parser.parts)
        except Exception:
            text = html.unescape(text)
    text = text.strip()[:limit]
    return _text_result(json.dumps({"url": final_url, "text": text}, ensure_ascii=False))


def _tools() -> list[dict[str, Any]]:
    return [
        {"name": "search", "description": "Search the current web through Local_AI_Agent's local SearXNG service. Never put private local content, credentials, file contents, or identifying local paths in the query.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Public web search query"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}, "required": ["query"], "additionalProperties": False}},
        {"name": "fetch_page", "description": "Fetch readable text from one public http/https page returned by search. Local/private network addresses are rejected.", "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"], "additionalProperties": False}},
    ]


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    message_id = message.get("id")
    if message_id is None:
        return None
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        protocol = str(requested or PROTOCOL_VERSION)
        return _rpc_result(message_id, {"protocolVersion": protocol, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}})
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
