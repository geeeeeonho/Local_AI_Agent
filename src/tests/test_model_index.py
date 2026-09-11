"""Canonical inventory behavior; no Ollama, Docker, network or GUI required."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from launcher.models import model_files as mf


def blob(root, letter='a', size=10, suffix=''):
    path = root / 'blobs' / ('sha256-' + letter * 64 + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    return path


def layer(letter='a', size=10, role='model'):
    return {'digest': 'sha256:' + letter * 64, 'size': size,
            'mediaType': 'application/vnd.ollama.image.' + role}


def manifest(root, name='alpha', layers=None, registry='registry.ollama.ai',
             namespace='library', tag='latest', config=None):
    path = root / 'manifests' / registry / namespace / name / tag
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'schemaVersion': 2, 'layers': layers if layers is not None else [layer()]}
    if config is not None:
        data['config'] = config
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def inventory(root):
    return mf.build_index(root)


def one_model(index, name='alpha:latest'):
    return next(m for m in index['models'] if m['name'] == name)


def one_blob(index, name):
    return next(b for b in index['blobs'] if b['file_name'] == name)


def test_schema_identifies_the_observed_store_and_does_not_claim_hash_verification(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    result = inventory(tmp_path)
    assert result['schema_version'] == 1
    assert result['model_storage'] == str(tmp_path.resolve())
    assert result['blob_hashes_verified'] is False
    assert result['deletion_safe'] is False
    assert result['scan_complete'] is True


def test_forward_and_reverse_references_include_the_manifest(tmp_path):
    p = blob(tmp_path)
    m = manifest(tmp_path)
    result = inventory(tmp_path)
    model = one_model(result)
    assert model['manifest'] == m.relative_to(tmp_path).as_posix()
    assert model['blobs'] == [p.name]
    assert one_blob(result, p.name)['models'] == ['alpha:latest']


def test_shared_and_exclusive_sizes_count_each_blob_only_once(tmp_path):
    a = blob(tmp_path, 'a', 10)
    blob(tmp_path, 'b', 20)
    blob(tmp_path, 'c', 4)
    manifest(tmp_path, layers=[layer('a', 10), layer('c', 4), layer('c', 4)])
    manifest(tmp_path, 'beta', [layer('b', 20), layer('c', 4)])
    result = inventory(tmp_path)
    alpha = one_model(result)
    assert alpha['size_bytes'] == 14
    assert alpha['shared_bytes'] == 4
    assert alpha['exclusive_bytes'] == 10
    assert result['totals']['size_bytes'] == 34
    assert one_blob(result, a.name)['models'] == ['alpha:latest']
    assert len([r for r in result['files'] if r['model'] == 'alpha:latest']) == 2


def test_config_blob_is_included(tmp_path):
    blob(tmp_path)
    p = blob(tmp_path, 'b', 3)
    manifest(tmp_path, config=layer('b', 3))
    result = inventory(tmp_path)
    assert p.name in one_model(result)['blobs']
    assert any(r['layer'] == 'config' for r in result['files'])


def test_same_tag_from_different_registries_does_not_collide(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    manifest(tmp_path, registry='private.example')
    result = inventory(tmp_path)
    assert {m['name'] for m in result['models']} == {
        'alpha:latest', 'private.example/library/alpha:latest'}
    assert len(result['blobs'][0]['models']) == 2


def test_missing_blobs_are_not_counted_as_installed_bytes(tmp_path):
    manifest(tmp_path)
    (tmp_path / 'blobs').mkdir()
    result = inventory(tmp_path)
    assert result['blobs'][0]['status'] == 'missing'
    assert one_model(result)['missing_blobs'] == ['sha256-' + 'a' * 64]
    assert one_model(result)['size_bytes'] == 0
    assert result['totals']['size_bytes'] == 0


def test_size_mismatch_is_visible_without_claiming_hash_validation(tmp_path):
    p = blob(tmp_path, size=3)
    manifest(tmp_path)
    result = inventory(tmp_path)
    assert one_blob(result, p.name)['status'] == 'size_mismatch'
    assert one_model(result)['size_bytes'] == 3


def test_unreferenced_complete_blob_is_only_an_orphan_candidate(tmp_path):
    p = blob(tmp_path, 'b')
    manifest(tmp_path)
    result = inventory(tmp_path)
    assert one_blob(result, p.name)['status'] == 'orphan'
    assert result['deletion_safe'] is False


@pytest.mark.parametrize('suffix', ['-partial', '-partial-0', '-partial-12'])
def test_in_progress_downloads_are_never_orphans(tmp_path, suffix):
    p = blob(tmp_path, suffix=suffix)
    (tmp_path / 'manifests').mkdir()
    result = inventory(tmp_path)
    assert one_blob(result, p.name)['status'] == 'partial'
    assert not any(r['status'] == 'orphan' for r in result['files'])


def test_unknown_files_are_not_orphans(tmp_path):
    path = tmp_path / 'blobs' / 'notes.txt'
    path.parent.mkdir()
    path.write_text('keep me', encoding='utf-8')
    (tmp_path / 'manifests').mkdir()
    assert one_blob(inventory(tmp_path), path.name)['status'] == 'unknown'


@pytest.mark.parametrize('data', ['{', '[]', '{"layers":17}',
                                   '{"layers":[{"digest":"../../secret", "size":3}]}'])
def test_invalid_manifest_makes_unreferenced_status_uncertain(tmp_path, data):
    p = blob(tmp_path)
    m = manifest(tmp_path)
    m.write_text(data, encoding='utf-8')
    result = inventory(tmp_path)
    assert result['scan_complete'] is False
    assert result['errors']
    assert one_blob(result, p.name)['status'] == 'unreferenced_unknown'


@pytest.mark.parametrize('size', [-1, True, '10', None, 1.5])
def test_invalid_declared_sizes_are_reported_not_coerced(tmp_path, size):
    blob(tmp_path)
    manifest(tmp_path, layers=[dict(layer(), size=size)])
    result = inventory(tmp_path)
    assert result['scan_complete'] is False
    assert result['errors']


def test_missing_manifest_tree_prevents_orphan_classification(tmp_path):
    p = blob(tmp_path)
    result = inventory(tmp_path)
    assert result['scan_complete'] is False
    assert one_blob(result, p.name)['status'] == 'unreferenced_unknown'


def test_desktop_metadata_is_ignored_without_hiding_real_errors(tmp_path):
    blob(tmp_path)
    m = manifest(tmp_path)
    (m.parent / '.DS_Store').write_bytes(b'junk')
    assert inventory(tmp_path)['scan_complete'] is True


def symlink_or_skip(target, link, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip('The runner does not permit creating symlinks')


def test_symlinked_manifest_tree_is_not_followed(tmp_path):
    external = tmp_path / 'external'
    manifest(external)
    root = tmp_path / 'store'
    root.mkdir()
    p = blob(root)
    symlink_or_skip(external / 'manifests', root / 'manifests', True)
    result = inventory(root)
    assert not result['models']
    assert result['scan_complete'] is False
    assert one_blob(result, p.name)['status'] == 'unreferenced_unknown'


def test_symlinked_blob_is_not_treated_as_installed(tmp_path):
    root = tmp_path / 'store'
    manifest(root)
    (root / 'blobs').mkdir()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'private data')
    symlink_or_skip(outside, root / 'blobs' / ('sha256-' + 'a' * 64))
    result = inventory(root)
    assert result['scan_complete'] is False
    assert result['blobs'][0]['status'] == 'unavailable'
    assert one_model(result)['size_bytes'] == 0
    assert outside.read_bytes() == b'private data'


def test_scanning_does_not_create_a_missing_store(tmp_path):
    root = tmp_path / 'not-created'
    result = inventory(root)
    assert not result['scan_complete']
    assert result['models'] == []
    assert not root.exists()
    assert mf.refresh(root) is None
    assert not root.exists()


def test_refresh_publishes_json_and_csv_from_the_same_snapshot(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    out = mf.refresh(tmp_path)
    assert out == tmp_path / mf.CSV_NAME
    data = json.loads((tmp_path / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert data['csv_sha256'] == hashlib.sha256(out.read_bytes()).hexdigest()
    with out.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == list(mf.FIELDS)
    assert rows[0]['model'] == data['files'][0]['model']
    assert out.read_bytes().startswith(b'\xef\xbb\xbf')


def test_legacy_scan_returns_filerow_and_keeps_role_labels(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    with patch.object(mf, '_catalog_roles', return_value={'alpha:latest': 'chat'}):
        rows = mf.scan(tmp_path)
    assert isinstance(rows[0], mf.FileRow)
    assert rows[0].role == 'chat'


def test_refresh_tracks_external_install_and_remove_without_touching_the_store(tmp_path):
    b = blob(tmp_path)
    m = manifest(tmp_path)
    before = b.read_bytes()
    assert mf.refresh(tmp_path)
    m.unlink()
    assert mf.refresh(tmp_path)
    data = json.loads((tmp_path / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert not data['models']
    assert data['blobs'][0]['status'] == 'orphan'
    assert b.read_bytes() == before


def test_unique_write_probe_does_not_destroy_an_existing_file(tmp_path):
    protected = tmp_path / '.model_files_write_probe'
    protected.write_text('do not delete', encoding='utf-8')
    assert mf._writable(tmp_path)
    assert protected.read_text(encoding='utf-8') == 'do not delete'


def test_json_replace_failure_preserves_previous_json_and_cleans_temporary_files(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    assert mf.refresh(tmp_path)
    target = tmp_path / 'MODEL_INDEX.json'
    previous = target.read_bytes()
    original_replace = os.replace

    def fail_json(source, destination):
        if Path(destination) == target:
            raise PermissionError('locked by reader')
        return original_replace(source, destination)

    with patch('os.replace', side_effect=fail_json):
        assert mf.refresh(tmp_path) is None
    assert target.read_bytes() == previous
    assert not list(tmp_path.glob('*.tmp'))


def test_read_only_store_fallback_keeps_both_outputs_together(tmp_path):
    root, output = tmp_path / 'store', tmp_path / 'derived'
    blob(root)
    manifest(root)
    with patch.object(mf, 'default_csv_path', return_value=output / mf.CSV_NAME):
        assert mf.refresh(root) == output / mf.CSV_NAME
    data = json.loads((output / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert data['model_storage'] == str(root.resolve())
    assert not (root / 'MODEL_INDEX.json').exists()


def test_cli_one_shot_indexes_without_loading_a_runtime(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    command = [sys.executable, '-m', 'launcher.models.model_index', str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'MODEL_INDEX.json').is_file()


@pytest.mark.parametrize('interval', ['0', '-1', 'nan', 'inf'])
def test_cli_rejects_unsafe_watch_intervals(tmp_path, interval):
    command = [sys.executable, '-m', 'launcher.models.model_index', str(tmp_path),
               '--watch', interval]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert not (tmp_path / 'MODEL_INDEX.json').exists()


def test_summary_excludes_unavailable_declared_bytes():
    row = mf.FileRow('sha256-' + 'a' * 64, 'alpha:latest', '', 'weights',
                     1024 ** 3, 1.0, 1, 'unavailable', 'blobs/example')
    lines = mf.summary_lines([row])
    assert '0.0GB' in lines[0]
    assert any('unavailable' in line for line in lines)


@pytest.mark.parametrize('status', ['partial', 'size_mismatch', 'unknown', 'unreferenced_unknown'])
def test_summary_does_not_silently_hide_new_statuses(status):
    row = mf.FileRow('example', '', '', 'unreferenced', 1, 0.0, 0, status, 'blobs/example')
    assert status in '\n'.join(mf.summary_lines([row]))


def test_refresh_surfaces_scan_errors_and_both_output_names(tmp_path):
    blob(tmp_path)
    path = manifest(tmp_path)
    path.write_text('not json', encoding='utf-8')
    messages = []
    assert mf.refresh(tmp_path, log=messages.append)
    text = '\n'.join(messages)
    assert 'MODEL_INDEX.json' in text
    assert 'MODEL_FILES.csv' in text
    assert 'scan_complete=false' in text
    assert path.relative_to(tmp_path).as_posix() in text


def test_publish_rejects_output_collision_without_overwriting_json(tmp_path):
    from launcher.models import model_index
    target = tmp_path / 'MODEL_INDEX.json'
    target.write_text('previous', encoding='utf-8')
    with pytest.raises(ValueError):
        model_index.publish({'files': []}, target)
    assert target.read_text(encoding='utf-8') == 'previous'


def test_csv_publication_failure_leaves_whole_json_and_detectable_mismatch(tmp_path):
    blob(tmp_path)
    manifest(tmp_path)
    csv_path = mf.refresh(tmp_path)
    previous = csv_path.read_bytes()
    manifest(tmp_path, name='beta')
    replace = os.replace

    def fail_csv(source, destination):
        if Path(destination) == csv_path:
            raise PermissionError('open in spreadsheet')
        return replace(source, destination)

    with patch('os.replace', side_effect=fail_csv):
        assert mf.refresh(tmp_path) is None
    assert csv_path.read_bytes() == previous
    document = json.loads((tmp_path / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert document['csv_sha256'] != hashlib.sha256(previous).hexdigest()
    assert not list(tmp_path.glob('.*.tmp'))
    assert mf.refresh(tmp_path)
    assert document['csv_sha256'] == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_csv_formula_like_labels_are_text_and_json_keeps_raw_labels(tmp_path):
    blob(tmp_path)
    manifest(tmp_path, name='=SUM(1)')
    assert mf.refresh(tmp_path)
    data = json.loads((tmp_path / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert data['files'][0]['model'] == '=SUM(1):latest'
    with (tmp_path / mf.CSV_NAME).open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.DictReader(stream))['model'] == "'=SUM(1):latest"


def test_explicit_watch_observes_an_external_manifest_removal(tmp_path, capsys):
    from launcher.models import model_index
    blob(tmp_path)
    path = manifest(tmp_path)
    sleeps = []

    def tick(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            path.unlink()
        else:
            raise KeyboardInterrupt

    with patch.object(model_index.time, 'sleep', side_effect=tick):
        assert model_index.main([str(tmp_path), '--watch', '0.5']) == 130
    assert sleeps == [0.5, 0.5]
    data = json.loads((tmp_path / 'MODEL_INDEX.json').read_text(encoding='utf-8'))
    assert data['models'] == []
    assert data['blobs'][0]['status'] == 'orphan'


def test_cli_missing_store_returns_error_without_creating_it(tmp_path):
    root = tmp_path / 'missing'
    command = [sys.executable, '-m', 'launcher.models.model_index', str(root)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert 'Unable to publish' in result.stderr
    assert not root.exists()


def test_windows_scandir_zero_identity_does_not_reject_valid_manifests(tmp_path):
    # Windows DirEntry.stat reports st_ino/st_dev/st_nlink as zero, unlike lstat.
    # Exercise the real scanner with that OS boundary behavior, not os.name.
    from contextlib import contextmanager
    from types import SimpleNamespace
    from launcher.models import model_index
    blob(tmp_path)
    manifest(tmp_path)
    real_scandir = os.scandir

    class WindowsEntry:
        def __init__(self, entry):
            self._entry, self.path, self.name = entry, entry.path, entry.name

        def stat(self, *, follow_symlinks=True):
            info = self._entry.stat(follow_symlinks=follow_symlinks)
            return SimpleNamespace(st_ino=0, st_dev=0, st_nlink=0,
                                   st_size=info.st_size, st_mode=info.st_mode,
                                   st_mtime_ns=info.st_mtime_ns,
                                   st_file_attributes=getattr(info, 'st_file_attributes', 0))

    @contextmanager
    def windows_scandir(path):
        with real_scandir(path) as stream:
            yield [WindowsEntry(entry) for entry in stream]

    with patch.object(model_index.os, 'scandir', windows_scandir):
        result = inventory(tmp_path)
    assert result['scan_complete'] is True, result['errors']
    assert one_model(result)['size_bytes'] == 10
    assert result['blobs'][0]['status'] == 'ok'


def test_unreadable_blob_directory_is_unavailable_not_missing(tmp_path):
    from launcher.models import model_index
    blob(tmp_path)
    manifest(tmp_path)
    real_scandir = os.scandir

    def denied(path):
        if Path(path) == tmp_path / 'blobs':
            raise PermissionError('not permitted to enumerate blobs')
        return real_scandir(path)

    with patch.object(model_index.os, 'scandir', side_effect=denied):
        result = inventory(tmp_path)
    assert result['scan_complete'] is False
    assert result['blobs'][0]['status'] == 'unavailable'
    assert one_model(result)['missing_blobs'] == []
    assert one_model(result)['unavailable_blobs'] == ['sha256-' + 'a' * 64]
    assert one_model(result)['size_bytes'] == 0


def test_manifest_replaced_since_listing_is_rejected(tmp_path):
    from launcher.models import model_index
    blob(tmp_path)
    path = manifest(tmp_path)
    before = path.lstat()
    replacement = path.with_name('new')
    replacement.write_text(path.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    os.replace(replacement, path)
    with pytest.raises(ValueError, match='manifest changed before reading'):
        model_index._read_manifest(path, before)
