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


def test_notification_returns_no_response():
    assert search_mcp.handle_request(
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    ) is None
