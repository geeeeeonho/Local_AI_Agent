import pytest

from launcher.agent import search_mcp, web_safety


class FakeResolver:
    def __init__(self, addresses=None):
        self.addresses = set(addresses or {"93.184.216.34"})
        self.calls = []

    def resolve(self, host, port):
        self.calls.append((host, port))
        return set(self.addresses)


def _call(url):
    return search_mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "fetch_page", "arguments": {"url": url}},
    })["result"]


def test_direct_fetch_uses_validated_request_primitive(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "direct")
    resolver = FakeResolver()
    monkeypatch.setattr(web_safety.LocalResolver, "resolve", resolver.resolve)
    seen = []

    def fake_request(validated, **kwargs):
        seen.append(validated)
        return web_safety.ProtectedResponse(200, {"content-type": "text/plain"}, b"public page")

    monkeypatch.setattr(search_mcp.web_safety, "direct_request", fake_request)
    result = _call("https://example.com/page")

    assert result["isError"] is False
    assert resolver.calls == [("example.com", 443)]
    assert len(seen) == 1
    assert seen[0].addresses == ("93.184.216.34",)


def test_direct_redirect_to_private_is_blocked_before_second_connection(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "direct")
    resolver = FakeResolver()
    monkeypatch.setattr(web_safety.LocalResolver, "resolve", resolver.resolve)
    calls = []

    def fake_request(validated, **kwargs):
        calls.append(validated.url)
        return web_safety.ProtectedResponse(302, {"location": "http://127.0.0.1/admin"}, b"")

    monkeypatch.setattr(search_mcp.web_safety, "direct_request", fake_request)
    result = _call("https://example.com/start")

    assert result["isError"] is True
    assert "private" in result["content"][0]["text"].lower() or "local" in result["content"][0]["text"].lower()
    assert calls == ["https://example.com/start"]


def test_direct_unicode_redirect_is_normalized_before_second_request(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "direct")
    resolver = FakeResolver()
    monkeypatch.setattr(web_safety.LocalResolver, "resolve", resolver.resolve)
    calls = []

    def fake_request(validated, **kwargs):
        calls.append(validated)
        if len(calls) == 1:
            return web_safety.ProtectedResponse(
                302,
                {"location": "https://예시.한국/검색?q=한글"},
                b"",
            )
        return web_safety.ProtectedResponse(200, {"content-type": "text/plain"}, b"ok")

    monkeypatch.setattr(search_mcp.web_safety, "direct_request", fake_request)
    result = _call("https://example.com/start")

    assert result["isError"] is False
    assert len(calls) == 2
    assert calls[1].hostname == "예시.한국".encode("idna").decode("ascii")
    assert "%EA%B2%80%EC%83%89" in calls[1].url
    assert "%ED%95%9C%EA%B8%80" in calls[1].url


def test_direct_redirect_secret_is_blocked_before_second_connection(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "direct")
    resolver = FakeResolver()
    monkeypatch.setattr(web_safety.LocalResolver, "resolve", resolver.resolve)
    calls = []

    def fake_request(validated, **kwargs):
        calls.append(validated.url)
        return web_safety.ProtectedResponse(
            302,
            {"location": "https://example.com/?access_token=redacted-test-token-value"},
            b"",
        )

    monkeypatch.setattr(search_mcp.web_safety, "direct_request", fake_request)
    result = _call("https://example.com/start")

    assert result["isError"] is True
    assert "secret" in result["content"][0]["text"].lower()
    assert calls == ["https://example.com/start"]


def test_percent_encoded_secret_name_is_blocked_before_dns_or_http(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "direct")
    monkeypatch.setattr(
        web_safety.LocalResolver,
        "resolve",
        lambda *args, **kwargs: pytest.fail("privacy preflight must run before DNS"),
    )
    monkeypatch.setattr(
        search_mcp.web_safety,
        "direct_request",
        lambda *args, **kwargs: pytest.fail("privacy preflight must run before HTTP"),
    )

    result = _call("https://example.com/?%61ccess_token=redacted-test-token-value")

    assert result["isError"] is True
    assert "secret" in result["content"][0]["text"].lower()
