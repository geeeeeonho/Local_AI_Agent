"""Publication diagnostics and model-info integration regressions.

The presentation function is loaded from the real action AST so these tests do
not import or launch Ollama/GUI dependencies; scanner and publication are real.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from launcher.models import model_files as mf
from launcher.models import model_index


def store(root, size=10):
    blob = root / 'blobs' / ('sha256-' + 'a' * 64)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b'x' * 10)
    manifest = root / 'manifests' / 'registry.ollama.ai' / 'library' / 'alpha' / 'latest'
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({'schemaVersion': 2, 'layers': [{
        'digest': 'sha256:' + 'a' * 64, 'size': size,
        'mediaType': 'application/vnd.ollama.image.model',
    }]}), encoding='utf-8')
    return blob, manifest


def show_file_map(root):
    source = Path(__file__).resolve().parents[1] / 'launcher' / 'actions' / 'model_info.py'
    tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == '_show_file_map')
    scope = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    messages, warnings = [], []
    presenter = SimpleNamespace(info=messages.append, warn=warnings.append)
    scope['_show_file_map'](SimpleNamespace(model_dir=root), presenter)
    return '\n'.join(messages), '\n'.join(warnings)


def read_json(root):
    return json.loads((root / mf.INDEX_NAME).read_text(encoding='utf-8'))


def test_model_info_updates_json_as_well_as_csv(tmp_path):
    store(tmp_path)
    messages, warnings = show_file_map(tmp_path)
    assert (tmp_path / mf.INDEX_NAME).is_file()
    data = read_json(tmp_path)
    assert data['models'][0]['name'] == 'alpha:latest'
    assert data['csv_sha256'] == hashlib.sha256((tmp_path / mf.CSV_NAME).read_bytes()).hexdigest()
    assert mf.INDEX_NAME in messages and mf.CSV_NAME in messages
    assert not warnings


def test_model_info_clears_inventory_after_last_model_and_blob_are_removed(tmp_path):
    blob, manifest = store(tmp_path)
    assert mf.refresh(tmp_path)
    blob.unlink()
    manifest.unlink()
    show_file_map(tmp_path)
    data = read_json(tmp_path)
    assert data['models'] == [] and data['files'] == []
    assert data['totals']['size_bytes'] == 0
    assert (tmp_path / mf.CSV_NAME).read_bytes().count(b'\n') == 1


def test_model_info_exposes_incomplete_scan_diagnostics(tmp_path):
    _, manifest = store(tmp_path)
    manifest.write_text('{', encoding='utf-8')
    messages, warnings = show_file_map(tmp_path)
    assert 'scan_complete=false' in messages + warnings
    assert manifest.relative_to(tmp_path).as_posix() in messages + warnings


def test_refresh_logs_missing_store_without_creating_it(tmp_path):
    root = tmp_path / 'missing'
    messages = []
    assert mf.refresh(root, log=messages.append) is None
    assert str(root) in '\n'.join(messages)
    assert not root.exists()


def test_refresh_explains_failed_replace_and_keeps_previous_json(tmp_path):
    store(tmp_path)
    assert mf.refresh(tmp_path)
    previous = (tmp_path / mf.INDEX_NAME).read_bytes()
    messages = []
    with patch.object(model_index.os, 'replace', side_effect=PermissionError('locked by reader')):
        assert mf.refresh(tmp_path, log=messages.append) is None
    message = '\n'.join(messages)
    assert 'PermissionError' in message and 'locked by reader' in message
    assert str(tmp_path) in message
    assert (tmp_path / mf.INDEX_NAME).read_bytes() == previous


def test_a_failing_logger_does_not_break_successful_publication(tmp_path):
    store(tmp_path)

    def broken_logger(_message):
        raise RuntimeError('closed UI')

    assert mf.refresh(tmp_path, log=broken_logger) == tmp_path / mf.CSV_NAME
    assert read_json(tmp_path)['models']
    assert mf.refresh(tmp_path / 'missing', log=broken_logger) is None


@pytest.mark.parametrize('size', [2 ** 63, 10 ** 1000])
def test_impossible_declared_sizes_do_not_abort_the_inventory(tmp_path, size):
    store(tmp_path, size=size)
    data = mf.build_index(tmp_path)
    assert data['scan_complete'] is False
    assert data['errors'] and not data['models']
    assert data['blobs'][0]['status'] == 'unreferenced_unknown'


def test_cli_reports_scan_errors_on_stderr_while_stdout_remains_a_path(tmp_path):
    _, manifest = store(tmp_path)
    manifest.write_text('{', encoding='utf-8')
    command = [sys.executable, '-m', 'launcher.models.model_index', str(tmp_path)]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, env=env)
    assert result.returncode == 0, result.stderr
    assert 'scan_complete=false' in result.stderr
    assert result.stdout.strip() == str(tmp_path / mf.INDEX_NAME)


def test_watch_recovers_from_a_transient_csv_lock_without_stopping(tmp_path, capsys):
    store(tmp_path)
    real_replace = os.replace
    blocked = False
    ticks = []

    def temporarily_locked(source, destination):
        nonlocal blocked
        if Path(destination).name == mf.CSV_NAME and not blocked:
            blocked = True
            raise PermissionError('transient CSV lock')
        return real_replace(source, destination)

    def tick(interval):
        ticks.append(interval)
        if len(ticks) == 2:
            raise KeyboardInterrupt

    with patch.object(model_index.os, 'replace', side_effect=temporarily_locked), \
         patch.object(model_index.time, 'sleep', side_effect=tick):
        assert model_index.main([str(tmp_path), '--watch', '0.5']) == 130
    assert ticks == [0.5, 0.5]
    data = read_json(tmp_path)
    assert data['csv_sha256'] == hashlib.sha256((tmp_path / mf.CSV_NAME).read_bytes()).hexdigest()
    assert 'transient CSV lock' in capsys.readouterr().err
