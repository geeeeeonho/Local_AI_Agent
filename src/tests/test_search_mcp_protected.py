import socket

import pytest

from launcher.agent import search_mcp, web_safety


class FakeResolver:
    def __init__(self, addresses=None, error=None):
        self.addresses = set(addresses or ())
        self.error = error
        self.calls = []

    def resolve(self, host, port):
        self.calls.append((host, port))
        if self.error:
            raise self.error
        return set(self.addresses)


def _call(url):
    return search_mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "fetch_page", "arguments": {"url": url}},
    })["result"]


@pytest.mark.parametrize("mode", ["warp", "tor"])
def test_protected_fetch_never_uses_local_target_getaddrinfo(monkeypatch, mode):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", mode)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("protected fetch must not use local target DNS"),
    )
    resolver = FakeResolver({"93.184.216.34"})
    monkeypatch.setattr(search_mcp, "_resolver_for_mode", lambda selected: resolver)

    seen = []
    def fake_request(validated, **kwargs):
        seen.append(validated)
        assert validated.addresses == ("93.184.216.34",)
        return web_safety.ProtectedResponse(200, {"content-type": "text/plain"}, b"public page")

    monkeypatch.setattr(search_mcp.web_safety, "protected_request", fake_request)
    result = _call("https://example.com/page")
    assert result["isError"] is False
    assert resolver.calls == [("example.com", 443)]
    assert len(seen) == 1


def test_protected_redirect_is_revalidated_before_second_connection(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    resolver = FakeResolver({"93.184.216.34"})
    monkeypatch.setattr(search_mcp, "_resolver_for_mode", lambda selected: resolver)
    calls = []

    def fake_request(validated, **kwargs):
        calls.append(validated.url)
        return web_safety.ProtectedResponse(302, {"location": "http://127.0.0.1/admin"}, b"")

    monkeypatch.setattr(search_mcp.web_safety, "protected_request", fake_request)
    result = _call("https://example.com/start")
    assert result["isError"] is True
    assert "private" in result["content"][0]["text"].lower() or "local" in result["content"][0]["text"].lower()
    assert calls == ["https://example.com/start"]


def test_protected_redirect_secret_is_blocked_before_second_connection(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "tor")
    resolver = FakeResolver({"93.184.216.34"})
    monkeypatch.setattr(search_mcp, "_resolver_for_mode", lambda selected: resolver)
    calls = []

    def fake_request(validated, **kwargs):
        calls.append(validated.url)
        return web_safety.ProtectedResponse(
            302,
            {"location": "https://example.com/?access_token=secret-value-abcdefghijklmnop"},
            b"",
        )

    monkeypatch.setattr(search_mcp.web_safety, "protected_request", fake_request)
    result = _call("https://example.com/start")
    assert result["isError"] is True
    assert "secret" in result["content"][0]["text"].lower()
    assert "secret-value-abcdefghijklmnop" not in result["content"][0]["text"]
    assert calls == ["https://example.com/start"]


def test_protected_resolve_failure_does_not_attempt_connection(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_NETWORK_MODE", "warp")
    resolver = FakeResolver(error=OSError("resolver down"))
    monkeypatch.setattr(search_mcp, "_resolver_for_mode", lambda selected: resolver)
    monkeypatch.setattr(
        search_mcp.web_safety,
        "protected_request",
        lambda *args, **kwargs: pytest.fail("resolution failure must fail closed"),
    )
    result = _call("https://example.com/")
    assert result["isError"] is True
    assert "resolution" in result["content"][0]["text"].lower()
