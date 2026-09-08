"""Outbound URL validation and protected DNS/connection primitives.

Direct mode may resolve targets with the local resolver. WARP/Tor must resolve
public targets through a protected resolver and then connect to the exact IP
that was validated. This keeps SSRF checks while avoiding target DNS leakage.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import ssl
import struct
import urllib.parse
from dataclasses import dataclass
from typing import Protocol

_PROTECTED_MODES = {"warp", "tor"}
_DOH_HOST = "cloudflare-dns.com"
_DOH_PATH = "/dns-query"


class Resolver(Protocol):
    def resolve(self, host: str, port: int) -> set[str]: ...


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str = ""
    url: str = ""
    scheme: str = ""
    hostname: str = ""
    port: int = 0
    addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtectedResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _mode(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in {"direct", "warp", "tor", "block"} else "warp"


def is_public_address(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(str(raw).split("%", 1)[0])
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
    )


def _literal_address(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        return None


class LocalResolver:
    def resolve(self, host: str, port: int) -> set[str]:
        return {
            str(info[4][0]).split("%", 1)[0]
            for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }


def _proxy_url_from_env() -> str | None:
    value = os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
    return str(value).strip() if value else None


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        part = sock.recv(count - len(chunks))
        if not part:
            raise OSError("unexpected EOF from SOCKS proxy")
        chunks.extend(part)
    return bytes(chunks)


def _proxy_endpoint(proxy_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(proxy_url)
    if parsed.scheme.lower() not in {"socks5", "socks5h"}:
        raise OSError("protected resolver requires SOCKS5 proxy")
    if parsed.username or parsed.password:
        raise OSError("authenticated SOCKS proxy is not supported")
    if not parsed.hostname or not parsed.port:
        raise OSError("invalid SOCKS proxy endpoint")
    return parsed.hostname, int(parsed.port)


def _connect_proxy_host(host: str, port: int, timeout: float) -> socket.socket:
    """Connect to the managed proxy itself without using getaddrinfo.

    Target-host DNS privacy is the security property. Managed container names
    may use Docker's local resolver; numeric Host endpoints bypass DNS entirely.
    """
    literal = _literal_address(host)
    if literal:
        family = socket.AF_INET6 if ":" in literal else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((literal, port))
        return sock
    proxy_ip = socket.gethostbyname(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((proxy_ip, port))
    return sock


def open_socks5_connection(
    proxy_url: str,
    target_host: str,
    target_port: int,
    *,
    timeout: float,
    target_is_literal: bool,
) -> socket.socket:
    proxy_host, proxy_port = _proxy_endpoint(proxy_url)
    sock = _connect_proxy_host(proxy_host, proxy_port, timeout)
    try:
        sock.sendall(b"\x05\x01\x00")
        if _recv_exact(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS5 proxy rejected no-auth handshake")

        if target_is_literal:
            address = ipaddress.ip_address(target_host)
            if address.version == 4:
                atyp = b"\x01"
                encoded = address.packed
            else:
                atyp = b"\x04"
                encoded = address.packed
        else:
            encoded_host = target_host.encode("idna")
            if not encoded_host or len(encoded_host) > 255:
                raise OSError("invalid SOCKS target hostname")
            atyp = b"\x03"
            encoded = bytes([len(encoded_host)]) + encoded_host

        sock.sendall(b"\x05\x01\x00" + atyp + encoded + struct.pack("!H", int(target_port)))
        head = _recv_exact(sock, 4)
        if head[0] != 5 or head[1] != 0:
            raise OSError("SOCKS5 connect failed")
        if head[3] == 1:
            _recv_exact(sock, 4)
        elif head[3] == 4:
            _recv_exact(sock, 16)
        elif head[3] == 3:
            _recv_exact(sock, _recv_exact(sock, 1)[0])
        else:
            raise OSError("invalid SOCKS5 reply")
        _recv_exact(sock, 2)
        return sock
    except Exception:
        sock.close()
        raise


class ProtectedDoHResolver:
    """Resolve target names through DoH carried inside the selected SOCKS route."""

    def __init__(self, proxy_url: str, *, timeout: float = 10.0):
        self.proxy_url = str(proxy_url)
        self.timeout = float(timeout)
        _proxy_endpoint(self.proxy_url)

    @classmethod
    def from_environment(cls, *, timeout: float = 10.0) -> "ProtectedDoHResolver":
        proxy = _proxy_url_from_env()
        if not proxy:
            raise OSError("protected resolver proxy is unavailable")
        return cls(proxy, timeout=timeout)

    def _query(self, host: str, record_type: str) -> set[str]:
        sock = open_socks5_connection(
            self.proxy_url,
            _DOH_HOST,
            443,
            timeout=self.timeout,
            target_is_literal=False,
        )
        tls = None
        try:
            tls = ssl.create_default_context().wrap_socket(sock, server_hostname=_DOH_HOST)
            query = urllib.parse.urlencode({"name": host, "type": record_type})
            request = (
                f"GET {_DOH_PATH}?{query} HTTP/1.1\r\n"
                f"Host: {_DOH_HOST}\r\n"
                "Accept: application/dns-json\r\n"
                "User-Agent: Local_AI_Agent/1 protected-resolver\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            tls.sendall(request)
            response = http.client.HTTPResponse(tls)
            response.begin()
            if response.status != 200:
                raise OSError(f"DoH resolver HTTP {response.status}")
            payload = json.loads(response.read(1024 * 1024).decode("utf-8", "replace"))
            if int(payload.get("Status", 1)) != 0:
                return set()
            wanted = 1 if record_type == "A" else 28
            values = set()
            for answer in payload.get("Answer") or ():
                if not isinstance(answer, dict) or int(answer.get("type", -1)) != wanted:
                    continue
                raw = str(answer.get("data") or "").strip()
                try:
                    values.add(str(ipaddress.ip_address(raw)))
                except ValueError:
                    continue
            return values
        finally:
            try:
                (tls or sock).close()
            except Exception:
                pass

    def resolve(self, host: str, port: int) -> set[str]:
        del port
        values: set[str] = set()
        errors: list[Exception] = []
        for record_type in ("A", "AAAA"):
            try:
                values.update(self._query(host, record_type))
            except Exception as exc:
                errors.append(exc)
        if values:
            return values
        if errors:
            raise OSError("protected DNS resolution failed") from errors[0]
        raise OSError("protected DNS returned no addresses")


def validate_outbound_url(
    url: str,
    *,
    network_mode: str,
    resolver: Resolver | None = None,
) -> ValidationResult:
    raw_url = str(url or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return ValidationResult(False, "invalid URL")
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ValidationResult(False, "only http/https URLs are allowed")
    if parsed.username or parsed.password:
        return ValidationResult(False, "URLs with embedded credentials are not allowed")

    host = parsed.hostname.rstrip(".")
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return ValidationResult(False, "private/local network URLs are not allowed")
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)

    literal = _literal_address(host)
    if literal is not None:
        addresses = {literal}
    else:
        mode = _mode(network_mode)
        if resolver is None:
            if mode in _PROTECTED_MODES:
                try:
                    resolver = ProtectedDoHResolver.from_environment()
                except Exception:
                    return ValidationResult(False, "protected resolver unavailable")
            elif mode == "direct":
                resolver = LocalResolver()
            else:
                return ValidationResult(False, "public egress is blocked")
        try:
            addresses = {str(value).split("%", 1)[0] for value in resolver.resolve(host, port)}
        except Exception:
            return ValidationResult(False, "host resolution failed")

    if not addresses:
        return ValidationResult(False, "host resolution returned no addresses")
    if not all(is_public_address(value) for value in addresses):
        return ValidationResult(False, "private/local network URLs are not allowed")

    return ValidationResult(
        True,
        url=raw_url,
        scheme=parsed.scheme.lower(),
        hostname=host,
        port=int(port),
        addresses=tuple(sorted(addresses)),
    )


def protected_request(
    validated: ValidationResult,
    *,
    proxy_url: str | None = None,
    timeout: float = 25.0,
    max_bytes: int = 48000,
) -> ProtectedResponse:
    if not validated.ok or not validated.addresses:
        raise OSError("validated public target required")
    proxy = proxy_url or _proxy_url_from_env()
    if not proxy:
        raise OSError("protected proxy is unavailable")

    target_ip = validated.addresses[0]
    sock = open_socks5_connection(
        proxy,
        target_ip,
        validated.port,
        timeout=timeout,
        target_is_literal=True,
    )
    stream = sock
    try:
        if validated.scheme == "https":
            stream = ssl.create_default_context().wrap_socket(
                sock,
                server_hostname=validated.hostname,
            )
        parsed = urllib.parse.urlsplit(validated.url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        default_port = 443 if validated.scheme == "https" else 80
        host_header = validated.hostname
        if validated.port != default_port:
            host_header += f":{validated.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "User-Agent: Local_AI_Agent/1 local-search-mcp\r\n"
            "Accept: text/html,text/plain,application/xhtml+xml,*/*;q=0.5\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", "strict")
        stream.sendall(request)
        response = http.client.HTTPResponse(stream)
        response.begin()
        headers = {str(k).lower(): str(v) for k, v in response.getheaders()}
        body = response.read(max(1, int(max_bytes)))
        return ProtectedResponse(int(response.status), headers, body)
    finally:
        try:
            stream.close()
        except Exception:
            pass


__all__ = [
    "Resolver",
    "ValidationResult",
    "ProtectedResponse",
    "LocalResolver",
    "ProtectedDoHResolver",
    "is_public_address",
    "validate_outbound_url",
    "open_socks5_connection",
    "protected_request",
]
