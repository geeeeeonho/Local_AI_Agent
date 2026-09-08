import socket

import pytest

from launcher.agent import web_safety


class FakeResolver:
    def __init__(self, addresses=None, error=None):
        self.addresses = set(addresses or ())
        self.error = error
        self.calls = []

    def resolve(self, host: str, port: int):
        self.calls.append((host, port))
        if self.error:
            raise self.error
        return set(self.addresses)


def test_direct_validation_accepts_public_resolution(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
        ],
    )
    result = web_safety.validate_outbound_url("https://example.com/a", network_mode="direct")
    assert result.ok is True
    assert result.addresses == ("93.184.216.34",)


def test_direct_validation_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        ],
    )
    result = web_safety.validate_outbound_url("https://example.com/a", network_mode="direct")
    assert result.ok is False
    assert "private" in result.reason.lower() or "local" in result.reason.lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://172.16.1.1/",
        "http://192.168.1.1/",
        "http://169.254.1.1/",
        "http://localhost/",
        "http://user:pass@example.com/",
        "file:///C:/private.txt",
    ],
)
def test_unsafe_targets_rejected_without_resolution(monkeypatch, url):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("literal/local invalid target must not resolve"),
    )
    result = web_safety.validate_outbound_url(url, network_mode="direct")
    assert result.ok is False


@pytest.mark.parametrize("mode", ["warp", "tor"])
def test_protected_validation_never_uses_local_target_dns(monkeypatch, mode):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("protected mode must not use local DNS"),
    )
    resolver = FakeResolver({"93.184.216.34"})
    result = web_safety.validate_outbound_url(
        "https://example.com/resource", network_mode=mode, resolver=resolver
    )
    assert result.ok is True
    assert result.addresses == ("93.184.216.34",)
    assert resolver.calls == [("example.com", 443)]


@pytest.mark.parametrize("mode", ["warp", "tor"])
def test_protected_resolution_private_or_failure_is_fail_closed(mode):
    private = web_safety.validate_outbound_url(
        "https://example.com/", network_mode=mode, resolver=FakeResolver({"10.0.0.2"})
    )
    assert private.ok is False

    failed = web_safety.validate_outbound_url(
        "https://example.com/",
        network_mode=mode,
        resolver=FakeResolver(error=OSError("resolver down")),
    )
    assert failed.ok is False


def test_protected_mode_without_resolver_fails_closed(monkeypatch):
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    result = web_safety.validate_outbound_url("https://example.com/", network_mode="warp")
    assert result.ok is False
    assert "resolver" in result.reason.lower() or "proxy" in result.reason.lower()
