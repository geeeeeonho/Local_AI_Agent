"""High-confidence outbound privacy checks.

The policy intentionally blocks only patterns that are very likely to be local
secrets, local paths, credential-bearing URLs, or private/local addresses.
Ordinary public identifiers such as names, e-mail addresses and phone numbers
are not blanket-blocked because they may be legitimate search terms.
"""
from __future__ import annotations

import ipaddress
import re

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|"
    r"password|passwd|secret|client[_-]?secret)\b\s*[:=]\s*[^\s,;]{6,}"
)
_KNOWN_TOKEN_RE = re.compile(
    r"(?i)(?:\bsk-[A-Za-z0-9_-]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*\b)"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:^|[\s\"'])(?:[A-Z]:\\+|\\\\+)[^\r\n]+")
_POSIX_LOCAL_PATH_RE = re.compile(
    r"(?:^|[\s\"'])(?:/(?:home|Users|private|etc|var|tmp|mnt|opt)/)[^\s\"']+"
)
_FILE_URL_RE = re.compile(r"(?i)\bfile://[^\s]+")
_CREDENTIAL_URL_RE = re.compile(r"(?i)\bhttps?://[^\s/:@]+:[^\s/@]+@[^\s]+")
_IPV4_RE = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
_LOCALHOST_RE = re.compile(r"(?i)(?:^|[^A-Za-z0-9.-])localhost(?::\d+)?(?:$|[^A-Za-z0-9.-])")


def _private_address_present(text: str) -> bool:
    if _LOCALHOST_RE.search(text):
        return True
    for match in _IPV4_RE.finditer(text):
        try:
            address = ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        if not address.is_global:
            return True
    return False


def blocked_outbound_reason(text: str) -> str | None:
    """Return a redaction-safe category when outbound text must be blocked."""
    value = str(text or "")
    if not value:
        return None
    if _SECRET_ASSIGNMENT_RE.search(value) or _KNOWN_TOKEN_RE.search(value):
        return "blocked outbound secret/token"
    if _FILE_URL_RE.search(value) or _WINDOWS_PATH_RE.search(value) or _POSIX_LOCAL_PATH_RE.search(value):
        return "blocked local file path"
    if _CREDENTIAL_URL_RE.search(value):
        return "blocked credential URL"
    if _private_address_present(value):
        return "blocked private/local address"
    return None


__all__ = ["blocked_outbound_reason"]
