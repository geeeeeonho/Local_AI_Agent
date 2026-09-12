"""The catalogue checker's contracts, with the registry injected.

The tool exists because a hand-maintained tag list drifts away from a live
registry: devstral-small:24b was never a library name and qwen3.5:27b had to be
swapped out, and both only surfaced at pull time. These tests pin the parts that
decide a verdict - never the network.
"""
import json
from types import SimpleNamespace
import urllib.error

import pytest

from tools import verify_model_catalog as verify


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def read(self, limit=None):
        return self._payload
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Answers by URL so a test can mix present, missing and broken tags."""
    def __init__(self, answers):
        self.answers = answers
        self.urls = []
    def open(self, request, timeout=None):
        self.urls.append(request.full_url)
        answer = self.answers.get(request.full_url, 404)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, 'err', {}, None)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer if isinstance(answer, bytes)
                            else json.dumps(answer).encode('utf-8'))


def manifest(*sizes):
    return {'layers': [{'digest': 'sha256:' + 'a' * 64, 'size': size} for size in sizes]}


def url(tag):
    repository, label = verify.split_tag(tag)
    return '%s/%s/manifests/%s' % (verify.REGISTRY, repository, label)


# ── tag parsing ──────────────────────────────────────────────────────────
@pytest.mark.parametrize('tag,expected', [
    ('gemma4:12b', ('library/gemma4', '12b')),
    ('gemma4', ('library/gemma4', 'latest')),
    ('huihui_ai/qwen3-abliterated:8b', ('huihui_ai/qwen3-abliterated', '8b')),
    ('prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S',
     ('prutser/gemma-4-26B-A4B-it-ara-abliterated', 'Q4_K_S')),
])
def test_library_and_namespaced_tags_both_resolve_to_a_manifest_path(tag, expected):
    assert verify.split_tag(tag) == expected


# ── verdicts ─────────────────────────────────────────────────────────────
def test_a_present_tag_reports_its_real_download_size():
    opener = FakeOpener({url('gemma4:12b'): manifest(7 * 1024 ** 3, 1024 ** 3)})
    result = verify.check('gemma4:12b', 7.6, opener=opener)
    assert result.exists is True
    assert result.actual_gb == pytest.approx(8.0)
    assert result.drift_gb == pytest.approx(0.4)


def test_a_404_is_the_one_answer_that_means_the_tag_is_gone():
    opener = FakeOpener({url('devstral-small:24b'): 404})
    result = verify.check('devstral-small:24b', 15.0, opener=opener)
    assert result.exists is False
    assert result.detail == 'HTTP 404'


@pytest.mark.parametrize('answer', [500, 429, urllib.error.URLError('offline'), TimeoutError('slow')])
def test_anything_other_than_404_is_unknown_not_missing(answer):
    """An outage must never be reported as 'this model no longer exists'."""
    opener = FakeOpener({url('gemma4:12b'): answer})
    result = verify.check('gemma4:12b', 7.6, opener=opener)
    assert result.exists is None
    assert result.actual_gb is None


def test_a_manifest_without_usable_layer_sizes_is_present_but_unsized():
    opener = FakeOpener({url('gemma4:12b'): {'layers': [{'size': 'big'}]}})
    result = verify.check('gemma4:12b', 7.6, opener=opener)
    assert result.exists is True and result.actual_gb is None
    assert 'layer sizes' in result.detail


def test_an_oversized_or_unreadable_response_is_not_treated_as_a_manifest():
    opener = FakeOpener({url('gemma4:12b'): b'x' * (1024 * 1024 + 2)})
    assert verify.check('gemma4:12b', 7.6, opener=opener).exists is None
    opener = FakeOpener({url('gemma4:12b'): b'not json'})
    assert verify.check('gemma4:12b', 7.6, opener=opener).exists is None


# ── summary ──────────────────────────────────────────────────────────────
def build(answers, declared):
    opener = FakeOpener({url(tag): answer for tag, answer in answers.items()})
    return verify.report([(tag, declared[tag]) for tag in answers], opener=opener)


def test_the_summary_separates_missing_from_drifted_from_unanswered():
    reports = build(
        {'a:1': 404,
         'b:1': manifest(20 * 1024 ** 3),
         'c:1': 503,
         'd:1': manifest(int(7.6 * 1024 ** 3))},
        {'a:1': 1.0, 'b:1': 15.0, 'c:1': 1.0, 'd:1': 7.6})
    text = '\n'.join(verify.summarise(reports))
    assert 'MISSING' in text and 'a:1' in text
    assert 'SIZE DRIFT' in text and 'b:1' in text
    assert 'UNKNOWN' in text and 'c:1' in text
    assert 'd:1' not in text.split('UNKNOWN')[0].split('SIZE DRIFT')[0]


def test_a_clean_catalogue_says_so_without_listing_every_tag():
    reports = build({'a:1': manifest(int(7.6 * 1024 ** 3))}, {'a:1': 7.6})
    text = '\n'.join(verify.summarise(reports))
    assert 'Every tag resolves' in text
    assert 'MISSING' not in text and 'SIZE DRIFT' not in text


def test_rounding_in_the_catalogue_is_not_reported_as_drift():
    reports = build({'a:1': manifest(int(7.9 * 1024 ** 3))}, {'a:1': 7.6})
    assert 'SIZE DRIFT' not in '\n'.join(verify.summarise(reports))


# ── wiring ───────────────────────────────────────────────────────────────
def test_every_catalogue_entry_is_checked_exactly_once():
    from launcher.models import model_catalog as catalog
    tags = verify.catalogue_tags()
    assert [tag for tag, _ in tags] == [entry.tag for entry in catalog.all_entries()]
    assert len(set(tag for tag, _ in tags)) == len(tags)
    assert all(declared > 0 for _, declared in tags)


def test_the_tool_reads_manifests_and_never_pulls():
    """Prose may mention pulling; the code must not do it."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(verify))
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                         and isinstance(node.value.value, str))]
    code = ast.unparse(tree)
    for forbidden in ('/blobs/', 'subprocess', 'os.system', 'popen'):
        assert forbidden not in code, forbidden
    assert 'manifests' in code


def test_a_missing_tag_fails_the_command_and_an_outage_does_not(monkeypatch, capsys):
    monkeypatch.setattr(verify, 'catalogue_tags', lambda: [('a:1', 1.0)])
    monkeypatch.setattr(verify, 'report',
                        lambda tags, **kw: [verify.TagReport('a:1', False, 1.0, None, 'HTTP 404')])
    assert verify.main([]) == 1
    monkeypatch.setattr(verify, 'report',
                        lambda tags, **kw: [verify.TagReport('a:1', None, 1.0, None, 'URLError')])
    assert verify.main([]) == 0
    assert 'UNKNOWN' in capsys.readouterr().out
