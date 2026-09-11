"""Bounded loopback-only Ollama API transport; no environment proxies/redirects."""
from __future__ import annotations
import json
import re
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

    def _json(self, path, payload=None, method=None, *, empty=False):
        with self.opener.open(self._request(path, payload, method), timeout=self.timeout) as response:
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
        with self.opener.open(request, timeout=max(self.timeout, 120)) as response:
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
