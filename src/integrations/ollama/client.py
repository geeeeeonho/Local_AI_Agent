"""Bounded loopback-only Ollama API transport; no environment proxies/redirects."""
from __future__ import annotations
import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

_MAX_JSON = 4 * 1024 * 1024
_MAX_LINE = 128 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Ollama API redirect refused')


def model_name(value: str) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}', value)
            or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('invalid Ollama model name')
    return value


# The rule lives in core.models.registry so there is one of it. The local
# daemon attaches the user's credentials and proxies these to Ollama's servers,
# so the prompt leaves the machine through the daemon - not through anything
# this project prepared - and every OpenAI-compatible client, this one
# included, talks to them exactly like a local model.
from core.models.registry import is_cloud_tag  # noqa: E402  (re-export)


def local_model_name(value: str) -> str:
    """Model name for anything that must stay on this machine.

    Block promises no public egress and WARP/Tor promise a specific route. A
    cloud tag silently voids all three, so it is refused here rather than
    somewhere the network policy can no longer see it.
    """
    name = model_name(value)
    if is_cloud_tag(name):
        raise ValueError(
            'refusing the Ollama cloud model ' + name + ': it runs on Ollama\'s '
            'servers, so it would leave this machine outside the selected '
            'network policy. Choose a local tag.')
    return name


class OllamaClient:
    def __init__(self, base_url='http://127.0.0.1:11434', *, opener=None, timeout=10):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or
                parsed.username or parsed.password or parsed.path or parsed.query or
                parsed.fragment or parsed.port is None):
            raise ValueError('use a literal IPv4 loopback HTTP endpoint with an explicit port')
        self.base_url, self.port, self.timeout = base_url, parsed.port, timeout
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, path, payload=None, method=None):
        data = json.dumps(payload, allow_nan=False).encode('utf-8') if payload is not None else None
        return urllib.request.Request(self.base_url + path, data=data, method=method,
                                      headers={'Content-Type': 'application/json', 'Accept': 'application/json'})

    def _failure(self, error):
        """Ollama's own words for a failure, not just its status code.

        A refused pull or delete answers with {"error": "..."} and a non-2xx
        status, and urllib raises before the caller can read it. Reporting
        "HTTP Error 500" hid the part the user can act on - the tag that does
        not exist, the disk that is full, the registry that is unreachable.
        """
        detail = ''
        try:
            body = error.read(_MAX_JSON + 1)
            value = json.loads(body.decode('utf-8', 'replace'))
            if isinstance(value, dict) and value.get('error'):
                detail = str(value['error'])
        except Exception:
            detail = ''
        finally:
            try:
                error.close()
            except Exception:
                pass
        if detail:
            return RuntimeError(detail)
        return RuntimeError('Ollama refused the request (HTTP %s)' % (error.code,))

    def _open(self, request, timeout):
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            raise self._failure(error) from None

    def _json(self, path, payload=None, method=None, *, empty=False):
        with self._open(self._request(path, payload, method), self.timeout) as response:
            raw = response.read(_MAX_JSON + 1)
        if len(raw) > _MAX_JSON:
            raise RuntimeError('Ollama JSON response exceeds size limit')
        if not raw and empty:
            return {}
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Ollama response must be an object')
        if value.get('error'):
            raise RuntimeError(str(value['error']))
        return value

    def list_models(self) -> list[dict]:
        models = self._json('/api/tags').get('models')
        if not isinstance(models, list) or not all(isinstance(m, dict) and isinstance(m.get('name'), str) for m in models):
            raise ValueError('Ollama tags response has no valid models array')
        return models

    def show(self, name: str) -> dict:
        return self._json('/api/show', {'model': model_name(name)})

    def remove(self, name: str):
        self._json('/api/delete', {'model': model_name(name)}, 'DELETE', empty=True)

    def pull(self, name: str, progress=None):
        request = self._request('/api/pull', {'model': model_name(name), 'stream': True})
        success = False
        with self._open(request, max(self.timeout, 120)) as response:
            while True:
                raw = response.readline(_MAX_LINE + 1)
                if not raw:
                    break
                if len(raw) > _MAX_LINE:
                    raise RuntimeError('Ollama progress line exceeds size limit')
                message = json.loads(raw.decode('utf-8'))
                if not isinstance(message, dict):
                    raise ValueError('Ollama progress must be an object')
                if message.get('error'):
                    raise RuntimeError(str(message['error']))
                if progress:
                    progress(message)
                success = message.get('status') == 'success'
                if success:
                    break
        if not success:
            raise RuntimeError('Ollama pull ended before terminal success')
