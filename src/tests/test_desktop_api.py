"""Local API transport regressions retained from the reviewed foundation."""
import io
import json
import pytest

class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        self.response = Response(self.payload)
        return self.response


def test_api_uses_loopback_and_closes_response():
    from integrations.ollama.client import OllamaClient
    opener = Opener(b'{"models": []}')
    client = OllamaClient(opener=opener)
    assert client.list_models() == []
    assert opener.response.closed
    assert opener.requests[0][0].full_url == 'http://127.0.0.1:11434/api/tags'


@pytest.mark.parametrize('url', ['http://example.com', 'http://127.0.0.1.evil:11434',
                                'https://127.0.0.1:11434', 'http://user:pw@127.0.0.1:11434',
                                'http://127.0.0.1:11434/api', 'http://localhost:11434'])
def test_api_rejects_noncanonical_endpoints(url):
    from integrations.ollama.client import OllamaClient
    with pytest.raises(ValueError):
        OllamaClient(base_url=url)


def test_pull_stream_requires_terminal_success_and_reports_progress():
    from integrations.ollama.client import OllamaClient
    opener = Opener(b'{"status":"pulling","completed":8}\n{"status":"success"}\n')
    events = []
    OllamaClient(opener=opener).pull('gemma4:12b', progress=events.append)
    assert events[-1]['status'] == 'success'
    assert opener.response.closed
    request = opener.requests[0][0]
    assert json.loads(request.data) == {'model': 'gemma4:12b', 'stream': True}


@pytest.mark.parametrize('payload', [b'{"error":"disk full"}\n', b'{"status":"pulling"}\n', b'not-json\n'])
def test_pull_rejects_errors_and_truncation(payload):
    from integrations.ollama.client import OllamaClient
    opener = Opener(payload)
    with pytest.raises((ValueError, RuntimeError)):
        OllamaClient(opener=opener).pull('gemma4:12b')
    assert opener.response.closed


def test_remove_uses_delete_and_never_filesystem_unlink():
    from integrations.ollama.client import OllamaClient
    opener = Opener(b'')
    OllamaClient(opener=opener).remove('namespace/model:tag')
    request = opener.requests[0][0]
    assert request.get_method() == 'DELETE'
    assert json.loads(request.data)['model'] == 'namespace/model:tag'


@pytest.mark.parametrize('name', ['', '../model', 'model\nFROM evil', '--flag', 'x\\y'])
def test_invalid_model_names_rejected_before_io(name):
    from integrations.ollama.client import OllamaClient
    opener = Opener(b'{}')
    with pytest.raises(ValueError):
        OllamaClient(opener=opener).show(name)
    assert opener.requests == []


def test_api_default_transport_ignores_proxy_environment(monkeypatch):
    from integrations.ollama.client import OllamaClient
    import urllib.request
    monkeypatch.setenv('HTTP_PROXY', 'http://attacker:8080')
    client = OllamaClient()
    assert not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies
                   for h in client.opener.handlers)


def test_api_redirects_are_denied():
    from integrations.ollama.client import NoRedirect
    with pytest.raises(RuntimeError, match='redirect'):
        NoRedirect().redirect_request(None, None, 302, 'Moved', {}, 'http://evil/')
