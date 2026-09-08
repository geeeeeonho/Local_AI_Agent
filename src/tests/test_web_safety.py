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


class FakeSocket:
    def __init__(self):
        self.timeout = None
        self.connected = None
        self.sent = bytearray()
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, target):
        self.connected = target

    def sendall(self, payload):
        self.sent.extend(payload)

    def close(self):
        self.closed = True


class FakeHTTPResponse:
    def __init__(self, stream):
        self.stream = stream
        self.status = 200

    def begin(self):
        return None

    def getheaders(self):
        return [("Content-Type", "text/plain")]

    def read(self, count):
        return b"ok"[:count]


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


def test_unicode_url_is_normalized_for_dns_tls_and_http():
    resolver = FakeResolver({"93.184.216.34"})
    raw = "https://예시.한국/검색/abc?q=한글%20test&x=1#fragment"

    result = web_safety.validate_outbound_url(raw, network_mode="direct", resolver=resolver)

    ascii_host = "예시.한국".encode("idna").decode("ascii")
    assert result.ok is True
    assert result.hostname == ascii_host
    assert resolver.calls == [(ascii_host, 443)]
    assert result.url.startswith(f"https://{ascii_host}/")
    assert "%EA%B2%80%EC%83%89" in result.url
    assert "q=%ED%95%9C%EA%B8%80%20test" in result.url
    assert "%2520" not in result.url
    assert "#fragment" not in result.url


def test_existing_percent_encoded_url_is_not_double_encoded():
    resolver = FakeResolver({"93.184.216.34"})
    result = web_safety.validate_outbound_url(
        "https://example.com/%EA%B2%80%EC%83%89?q=%ED%95%9C%EA%B8%80",
        network_mode="direct",
        resolver=resolver,
    )
    assert result.ok is True
    assert "%25EA" not in result.url
    assert "/%EA%B2%80%EC%83%89" in result.url


def test_direct_request_connects_to_validated_literal_ip_without_second_dns(monkeypatch):
    fake_socket = FakeSocket()
    monkeypatch.setattr(web_safety.socket, "socket", lambda *args, **kwargs: fake_socket)
    monkeypatch.setattr(
        web_safety.socket,
        "getaddrinfo",
        lambda *args, **kwargs: pytest.fail("direct request must not resolve hostname again"),
    )
    monkeypatch.setattr(web_safety.http.client, "HTTPResponse", FakeHTTPResponse)
    validated = web_safety.ValidationResult(
        True,
        url="http://example.com/resource?q=1",
        scheme="http",
        hostname="example.com",
        port=80,
        addresses=("93.184.216.34",),
    )

    response = web_safety.direct_request(validated, timeout=3.0, max_bytes=100)

    assert fake_socket.connected == ("93.184.216.34", 80)
    request = bytes(fake_socket.sent).decode("ascii")
    assert request.startswith("GET /resource?q=1 HTTP/1.1\r\n")
    assert "Host: example.com\r\n" in request
    assert response.body == b"ok"


def test_direct_https_uses_original_normalized_hostname_for_sni(monkeypatch):
    fake_socket = FakeSocket()
    captured = {}

    class FakeContext:
        def wrap_socket(self, sock, *, server_hostname):
            captured["server_hostname"] = server_hostname
            return sock

    monkeypatch.setattr(web_safety.socket, "socket", lambda *args, **kwargs: fake_socket)
    monkeypatch.setattr(web_safety.ssl, "create_default_context", lambda: FakeContext())
    monkeypatch.setattr(web_safety.http.client, "HTTPResponse", FakeHTTPResponse)
    validated = web_safety.ValidationResult(
        True,
        url="https://xn--9n2bp8q.xn--3e0b707e/%EA%B2%80%EC%83%89",
        scheme="https",
        hostname="xn--9n2bp8q.xn--3e0b707e",
        port=443,
        addresses=("93.184.216.34",),
    )

    web_safety.direct_request(validated, timeout=3.0, max_bytes=100)

    assert fake_socket.connected == ("93.184.216.34", 443)
    assert captured["server_hostname"] == validated.hostname
    assert f"Host: {validated.hostname}\r\n".encode("ascii") in bytes(fake_socket.sent)
