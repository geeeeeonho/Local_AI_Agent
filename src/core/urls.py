"""Only runtime-issued, local HTTP UI addresses reach a browser."""
from urllib.parse import urlsplit


def local_url(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError('invalid local UI address')
    parts = urlsplit(value)
    if (parts.scheme != 'http' or parts.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parts.username or parts.password or parts.port is None):
        raise ValueError('UI address must be a loopback HTTP endpoint with an explicit port')
    return value
