"""One pipeline answers "which models are here", and everything uses it.

Seven places used to ask that question and each answered differently: the
launcher spawned `ollama list` and parsed its columns, the role resolver made
its own unproxied HTTP call, the management screen made another, the model
screen read manifests, and the Ollama service read both and compared them.
They disagreed about tag spelling, about what a failed lookup means, and about
which host to ask, so the same store could read as full on one screen and
empty on the next.
"""
import ast
from pathlib import Path

import pytest

import model_router_stub as router
from core.models import registry

SRC = Path(__file__).resolve().parents[1]


# ── the rule itself, with no server and no disk ──────────────────────────

def test_the_router_is_the_authority_while_it_is_running():
    """It is the process that will serve the prompt, so it decides."""
    found = registry.resolve(lambda: ['served:1'], lambda: ['stale:1'])
    assert found.source == registry.ROUTER
    assert found.tags == frozenset({'served:1'})
    assert found.on_disk == frozenset({'stale:1'}), 'the other side is kept, not lost'


def test_a_stopped_router_falls_back_to_the_store():
    """Those models will be served the moment Ollama starts."""
    found = registry.resolve(None, lambda: ['here:1'])
    assert found.source == registry.STORE and found.tags == frozenset({'here:1'})
    assert found.router_reachable is False


def test_reading_neither_is_not_the_same_as_having_none():
    """'You have no models' and 'I could not check' lead to opposite actions."""
    found = registry.resolve(None, None)
    assert found.source == registry.UNKNOWN
    assert found.known is False
    assert found.has('anything:1') is False, 'unknown never reads as usable'


@pytest.mark.parametrize('failure', [OSError('refused'), ValueError('garbage'), RuntimeError])
def test_a_reader_that_raises_means_could_not_read_not_empty(failure):
    def explode():
        raise failure
    found = registry.resolve(explode, lambda: ['here:1'])
    assert found.source == registry.STORE and found.served is None


def test_one_canonicalizer_runs_on_both_sides():
    found = registry.resolve(lambda: ['A:1'], lambda: ['a:1'],
                             canonical=lambda names: {n.lower() for n in names})
    assert found.served == found.on_disk == frozenset({'a:1'})


# ── agreement: is the router serving out of the store we resolved? ───────

def test_a_router_serving_models_the_store_does_not_hold_is_pointed_elsewhere():
    assert registry.resolve(lambda: ['ghost:7b'], lambda: []).agreement is False


def test_a_case_difference_is_not_a_disagreement():
    """Vendor tags mix case and Ollama does not promise to echo them back."""
    assert registry.resolve(lambda: ['Ghost:7B'], lambda: ['ghost:7b']).agreement is True


def test_a_router_serving_none_of_what_is_on_disk_is_the_clearest_disagreement():
    """This used to read as agreement - "nothing served contradicts nothing" -
    and it hid the case it most needed to catch: Ollama restarted by Windows
    without OLLAMA_MODELS, reading its own empty default while every installed
    model sat in the store this program manages. Three models on disk, zero
    served, and the program reported the store as matching."""
    assert registry.resolve(lambda: [], lambda: ['a:1']).agreement is False
    assert registry.resolve(lambda: [], lambda: ['a:1']).unreachable == frozenset({'a:1'})


def test_two_empty_sides_still_agree():
    assert registry.resolve(lambda: [], lambda: []).agreement is True


def test_agreement_is_unknown_when_either_side_is_unreadable():
    assert registry.resolve(None, lambda: ['a:1']).agreement is None
    assert registry.resolve(lambda: ['a:1'], None).agreement is None


# ── the composition everything shares ────────────────────────────────────

def test_the_pipeline_refuses_proxies_for_a_loopback_call(monkeypatch):
    """A bare urlopen sent a 127.0.0.1 request through http_proxy."""
    from integrations.ollama import inventory
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    seen = router.serve(monkeypatch, ['a:1'])
    assert sorted(inventory.read(store=False).tags) == ['a:1']
    assert seen == ['http://127.0.0.1:11434']


def test_the_store_side_reads_manifests_not_every_blob(monkeypatch, tmp_path):
    from integrations.ollama import inventory
    router.refuse(monkeypatch)
    router.store(monkeypatch, ['a:1'])
    walked = router.forbid_blob_walk(monkeypatch)
    assert inventory.read(tmp_path).tags == frozenset({'a:1'})
    assert walked == []


def test_every_caller_gets_the_same_answer_from_the_same_stub(monkeypatch, tmp_path):
    """The point of the unification: one stub moves every reader at once."""
    from launcher.models import model_roles
    from launcher.actions import model_manage
    from services.models.service import ModelService
    from types import SimpleNamespace

    router.serve(monkeypatch, ['gemma4:12b'])
    router.store(monkeypatch, ['gemma4:12b'])

    service = ModelService(SimpleNamespace(model_dir=tmp_path, client=object()))
    assert model_roles.installed_models() == {'gemma4:12b'}
    assert model_manage._installed_tags(SimpleNamespace(model_dir=tmp_path)) == {'gemma4:12b'}
    assert service.installed_tags() == {'gemma4:12b'}


def test_a_stopped_router_no_longer_reads_as_an_empty_library(monkeypatch, tmp_path):
    """Every one of these used to report nothing installed and offer to re-download."""
    from launcher.models import model_roles
    from launcher.actions import model_manage
    from types import SimpleNamespace

    router.refuse(monkeypatch)
    router.store(monkeypatch, ['gemma4:12b'])
    assert model_roles.installed_models() == {'gemma4:12b'}
    assert model_manage._installed_tags(SimpleNamespace(model_dir=tmp_path)) == {'gemma4:12b'}


def test_the_ladder_keeps_a_downloaded_model_when_the_server_is_stopped(monkeypatch):
    """It used to ignore the store and name a rung that is not on the machine."""
    from launcher.models import model_roles
    ladder = model_roles.LADDERS['coding']
    lowest = min(ladder, key=lambda rung: rung[1])[0]
    router.refuse(monkeypatch)
    router.store(monkeypatch, [lowest])
    assert model_roles.resolve_ladder('coding', 512.0) == lowest


# ── and nothing gets to ask its own way again ────────────────────────────

def _code_strings(tree):
    """Every string literal that is not a docstring — prose is not a call."""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, 'body', None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_no_second_way_of_asking_the_router_gets_added():
    """Every /api/tags call must come from the one hardened transport."""
    allowed = {
        Path('integrations/ollama/client.py'),   # the transport itself
        Path('launcher/config.py'),              # where the endpoint is defined
        Path('tools/evaluate_local_search_e2e.py'),  # an offline eval harness
        # Not a Python transport at all: this string is JavaScript that runs
        # *inside* the AnythingLLM container (docker exec node -e) to prove the
        # container itself can reach the host's Ollama. There is no stdlib
        # client in there to route it through.
        Path('launcher/anythingllm_runtime.py'),
    }
    offenders = []
    for path in sorted(SRC.rglob('*.py')):
        rel = path.relative_to(SRC)
        if rel.parts[0] == 'tests' or rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if any('/api/tags' in value for value in _code_strings(tree)):
            offenders.append(str(rel))
    assert offenders == [], 'ask through integrations.ollama.inventory: ' + ', '.join(offenders)


def test_nothing_shells_out_to_ask_what_is_installed():
    """`ollama list` is a process launch for a question HTTP already answers."""
    offenders = []
    for path in sorted(SRC.rglob('*.py')):
        if path.relative_to(SRC).parts[0] == 'tests':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in node.args:
                if not isinstance(arg, (ast.List, ast.Tuple)):
                    continue
                words = [e.value for e in arg.elts if isinstance(e, ast.Constant)
                         and isinstance(e.value, str)]
                if 'list' in words and any('ollama' in w.lower() for w in words):
                    offenders.append('%s:%d' % (path.relative_to(SRC), node.lineno))
    assert offenders == [], offenders


# ── failures the user can act on ─────────────────────────────────────────
# Ollama answers a refused pull or delete with {"error": "..."} and a non-2xx
# status. urllib raises before the caller can read the body, so the screen
# used to show "HTTP Error 500: Internal Server Error" and hide the part that
# says which tag does not exist or that the disk is full.

def _client_answering(status, body, *, reason='Server Error'):
    import io
    import urllib.error
    from integrations.ollama.client import OllamaClient

    class Opener:
        def open(self, request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, status, reason, {},
                io.BytesIO(body.encode('utf-8')))
    return OllamaClient('http://127.0.0.1:11434', opener=Opener())


def test_the_screen_gets_ollamas_reason_not_its_status_code():
    client = _client_answering(404, '{"error": "model \'ghost:7b\' not found"}')
    with pytest.raises(RuntimeError, match="ghost:7b"):
        client.remove('ghost:7b')


def test_a_failed_pull_says_why():
    client = _client_answering(500, '{"error": "write blob: no space left on device"}')
    with pytest.raises(RuntimeError, match='no space left'):
        client.pull('gemma4:12b')


@pytest.mark.parametrize('body', ['', 'not json', '{}', '{"error": ""}', '[]'])
def test_an_unreadable_error_body_still_names_the_status(body):
    client = _client_answering(503, body)
    with pytest.raises(RuntimeError, match='503'):
        client.show('gemma4:12b')


def test_an_oversized_error_body_does_not_become_the_message():
    client = _client_answering(500, '{"error": "' + 'x' * (5 * 1024 * 1024) + '"}')
    with pytest.raises(RuntimeError):
        client.show('gemma4:12b')
