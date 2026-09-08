import json

import pytest

from launcher.agent import search_mcp


def test_initialize_advertises_tools_capability():
    response = search_mcp.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "local_search"
    assert "tools" in response["result"]["capabilities"]


def test_tools_list_exposes_search_and_fetch_page():
    response = search_mcp.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {"search", "fetch_page"}


def test_search_tool_uses_searxng_json_endpoint(monkeypatch):
    captured = {}

    def fake_json_request(url, *, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return {
            "results": [
                {
                    "title": "Open Interpreter",
                    "url": "https://example.test/oi",
                    "content": "agent runtime",
                }
            ]
        }

    monkeypatch.setenv("SEARXNG_URL", "http://llm_searxng:8080")
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    monkeypatch.setattr(search_mcp, "_read_json_url", fake_json_request)

    response = search_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "open interpreter", "limit": 3}},
        }
    )

    assert captured["url"].startswith("http://llm_searxng:8080/search?")
    assert "format=json" in captured["url"]
    assert "q=open+interpreter" in captured["url"]
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload[0]["title"] == "Open Interpreter"
    assert payload[0]["url"] == "https://example.test/oi"
    assert response["result"]["isError"] is False


def test_decode_body_honors_cp949_content_type():
    raw = "한글 본문입니다".encode("cp949")
    text = search_mcp._decode_body(raw, "text/html; charset=euc-kr")
    assert text == "한글 본문입니다"


def test_decode_body_honors_html_meta_charset():
    raw = '<meta charset="euc-kr"><p>한글 페이지</p>'.encode("cp949")
    text = search_mcp._decode_body(raw, "text/html")
    assert "한글 페이지" in text


def test_fetch_page_rejects_non_http_urls():
    response = search_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "fetch_page", "arguments": {"url": "file:///etc/passwd"}},
        }
    )
    assert response["result"]["isError"] is True
    assert "http" in response["result"]["content"][0]["text"].lower()


def _tool_call(name, arguments, *, request_id=10):
    return search_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


def _error_text(response):
    assert response["result"]["isError"] is True
    return response["result"]["content"][0]["text"]


def test_block_mode_rejects_search_without_network_io(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "block")
    monkeypatch.setattr(
        search_mcp,
        "_read_json_url",
        lambda *args, **kwargs: pytest.fail("block mode must not call SearXNG"),
    )

    text = _error_text(_tool_call("search", {"query": "open interpreter"}))
    assert "block" in text.lower() or "차단" in text


def test_block_mode_rejects_fetch_without_network_io(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "block")
    monkeypatch.setattr(
        search_mcp,
        "_open_public_url",
        lambda *args, **kwargs: pytest.fail("block mode must not fetch public pages"),
    )

    text = _error_text(_tool_call("fetch_page", {"url": "https://example.com"}))
    assert "block" in text.lower() or "차단" in text


@pytest.mark.parametrize(
    "query,category_hint",
    [
        ("api_key=sk-abcdefghijklmnopqrstuvwxyz123456", "secret"),
        ("password=hunter2-super-secret", "secret"),
        (r"summarize C:\\Users\\Alice\\Documents\\private.txt", "path"),
        ("upload file:///home/alice/private.txt", "path"),
        ("open http://user:pass@example.com/private", "credential"),
        ("search http://127.0.0.1:8000/admin", "private"),
        ("search 192.168.1.15 dashboard", "private"),
    ],
)
def test_search_rejects_high_confidence_outbound_sensitive_text(monkeypatch, query, category_hint):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    monkeypatch.setattr(
        search_mcp,
        "_read_json_url",
        lambda *args, **kwargs: pytest.fail("sensitive query must be rejected before SearXNG"),
    )

    text = _error_text(_tool_call("search", {"query": query}))
    assert category_hint in text.lower() or "차단" in text
    assert query not in text


@pytest.mark.parametrize(
    "query",
    [
        "Open Interpreter permissions",
        "contact public@example.com",
        "010-1234-5678 공개 연락처 검색",
    ],
)
def test_search_does_not_blanket_block_normal_or_ambiguous_public_queries(monkeypatch, query):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    monkeypatch.setenv("SEARXNG_URL", "http://llm_searxng:8080")
    monkeypatch.setattr(
        search_mcp,
        "_read_json_url",
        lambda *args, **kwargs: {"results": []},
    )

    response = _tool_call("search", {"query": query})
    assert response["result"]["isError"] is False


def test_notification_returns_no_response():
    assert search_mcp.handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    ) is None
