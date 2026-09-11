"""Read-only Ollama inventory and atomic derived-file publication.

This is a Phase 0 component, not a second model runtime or a garbage collector.
A scan is an observation, not an Ollama transaction. Even a complete scan cannot
prove that an unreferenced blob is safe to delete while another app is pulling.
No blob contents are read, copied, modified, deleted, or cryptographically checked.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from typing import Mapping

INDEX_NAME = 'MODEL_INDEX.json'
CSV_NAME = 'MODEL_FILES.csv'
CSV_FIELDS = ('file_name', 'model', 'role', 'layer', 'size_bytes', 'size_gb',
              'shared_with', 'status', 'rel_path')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
_BLOB = re.compile(r'sha256-[0-9a-f]{64}\Z')
_PARTIAL = re.compile(r'sha256-[0-9a-f]{64}-partial(?:-\d+)?\Z')
_IGNORED_METADATA = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_LAYER_NAMES = {
    'application/vnd.ollama.image.' + name: label for name, label in (
        ('model', 'weights'), ('projector', 'projector'), ('adapter', 'adapter'),
        ('template', 'template'), ('system', 'system'), ('params', 'params'),
        ('prompt', 'prompt'), ('license', 'license'), ('messages', 'messages'))
}


def _linked(info: os.stat_result) -> bool:
    # Reject junctions and other Windows reparse points, not only POSIX symlinks.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & 0x400)


def _error(errors: list[dict], root: Path, path: Path, reason: str) -> None:
    errors.append({'path': path.relative_to(root).as_posix(), 'reason': reason})


def _entries(root: Path, folder: Path, errors: list[dict], recursive=False):
    """Enumerate without following symlinks; surface missing/unreadable trees."""
    try:
        info = folder.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise OSError('not a regular directory or is a reparse point')
        with os.scandir(folder) as stream:
            entries = sorted(stream, key=lambda entry: entry.name)
    except OSError as exc:
        _error(errors, root, folder, str(exc))
        return
    for entry in entries:
        path = Path(entry.path)
        if entry.name in _IGNORED_METADATA:
            continue
        try:
            # DirEntry.stat has zero st_ino/st_dev on Windows. lstat obtains
            # comparable identities for _read_manifest without following links.
            info = path.lstat()
        except OSError as exc:
            _error(errors, root, path, str(exc))
            yield path, None
            continue
        if _linked(info):
            _error(errors, root, path, 'symlink or reparse point not followed')
            yield path, None
        elif stat.S_ISDIR(info.st_mode) and recursive:
            yield from _entries(root, path, errors, recursive=True)
        elif stat.S_ISREG(info.st_mode):
            yield path, info
        else:
            _error(errors, root, path, 'not a regular file')
            yield path, None


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_manifest(path: Path, expected: os.stat_result) -> dict:
    """Bound metadata reads and reject files replaced/modified during the read."""
    if expected.st_size > _MAX_MANIFEST_BYTES:
        raise ValueError('manifest exceeds the metadata size limit')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(expected):
            raise ValueError('manifest changed before reading')
        payload = handle.read(_MAX_MANIFEST_BYTES + 1)
        after = os.fstat(handle.fileno())
    if len(payload) > _MAX_MANIFEST_BYTES or _identity(before) != _identity(after):
        raise ValueError('manifest changed during reading')
    data = json.loads(payload.decode('utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('layers'), list):
        raise ValueError('manifest must contain a layers array')
    return data


def _layer(value: object, config=False) -> dict:
    if not isinstance(value, dict):
        raise ValueError('layer must be an object')
    digest, size = value.get('digest'), value.get('size')
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError('layer must have a canonical sha256 digest')
    if type(size) is not int or size < 0:
        raise ValueError('layer size must be a non-negative integer')
    media = value.get('mediaType', '')
    if not isinstance(media, str):
        raise ValueError('layer mediaType must be a string')
    return {'file_name': digest.replace(':', '-', 1), 'digest': digest,
            'size_bytes': size,
            'layer': 'config' if config else _LAYER_NAMES.get(media, media or 'unknown')}


def _manifest_records(root: Path, errors: list[dict]) -> list[dict]:
    records = []
    folder = root / 'manifests'
    for path, info in _entries(root, folder, errors, recursive=True):
        if info is None:
            continue
        try:
            parts = path.relative_to(folder).parts
            if len(parts) < 4:
                raise ValueError('manifest must include registry/namespace/model/tag')
            registry, namespace = parts[0], '/'.join(parts[1:-2])
            local_name = parts[-2] + ':' + parts[-1]
            name = local_name if namespace == 'library' else namespace + '/' + local_name
            if registry != 'registry.ollama.ai':
                name = registry + '/' + namespace + '/' + local_name
            data = _read_manifest(path, info)
            layers = [_layer(v) for v in data['layers']]
            if 'config' in data:
                layers.insert(0, _layer(data['config'], config=True))
            sizes = {}
            for item in layers:
                previous = sizes.setdefault(item['file_name'], item['size_bytes'])
                if previous != item['size_bytes']:
                    raise ValueError('one manifest declares conflicting blob sizes')
            records.append({'name': name, 'registry': registry,
                            'manifest': path.relative_to(root).as_posix(),
                            'layers': layers, 'data': data})
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            _error(errors, root, path, str(exc))
    return records


def read_manifests(model_dir) -> dict[str, dict]:
    """Legacy dictionary view. Use build_index for scan diagnostics."""
    return {item['name']: item['data'] for item in
            _manifest_records(Path(model_dir).absolute(), [])}


def build_index(model_dir, roles: Mapping[str, str] | None = None) -> dict:
    """Build an inventory in memory; never create a missing model store.

    size_bytes means logical file length, not allocated filesystem blocks.
    Shared blobs are counted once per model and once in the store total.
    Missing declared bytes are shown in CSV, but excluded from installed totals.
    """
    root = Path(model_dir).expanduser().resolve()
    errors: list[dict] = []
    records = _manifest_records(root, errors)
    on_disk, unavailable = {}, set()
    blob_error_start = len(errors)
    for path, info in _entries(root, root / 'blobs', errors):
        if info is None:
            unavailable.add(path.name)
        else:
            on_disk[path.name] = info.st_size
    blob_tree_unavailable = any(error['path'] == 'blobs'
                                for error in errors[blob_error_start:])
    roles = roles or {}
    refs: dict[str, dict[str, list[dict]]] = {}
    for record in records:
        for item in record['layers']:
            refs.setdefault(item['file_name'], {}).setdefault(record['name'], []).append(item)

    complete = not errors
    blobs, files = [], []
    for name in sorted(set(on_disk) | set(refs) | unavailable):
        users = refs.get(name, {})
        declared = sorted({item['size_bytes'] for layers in users.values() for item in layers})
        actual = on_disk.get(name)
        if name in unavailable or (blob_tree_unavailable and actual is None):
            status = 'unavailable'
        elif users:
            status = 'missing' if actual is None else (
                'ok' if all(actual == value for value in declared) else 'size_mismatch')
        elif _PARTIAL.fullmatch(name):
            status = 'partial'
        elif not _BLOB.fullmatch(name):
            status = 'unknown'
        else:
            status = 'orphan' if complete else 'unreferenced_unknown'
        blobs.append({'file_name': name, 'rel_path': 'blobs/' + name,
                      'models': sorted(users), 'size_bytes': actual,
                      'declared_sizes': declared, 'status': status})
        shown_size = actual if actual is not None else max(declared, default=0)
        for model in sorted(users) or ['']:
            labels = sorted({item['layer'] for item in users.get(model, [])})
            files.append({'file_name': name, 'model': model,
                          'role': roles.get(model, ''),
                          'layer': '/'.join(labels) if labels else 'unreferenced',
                          'size_bytes': shown_size,
                          'size_gb': round(shown_size / (1024 ** 3), 3),
                          'shared_with': len(users), 'status': status,
                          'rel_path': 'blobs/' + name})

    by_name = {b['file_name']: b for b in blobs}
    models = []
    for record in records:
        names = sorted({item['file_name'] for item in record['layers']})
        size = lambda n: by_name[n]['size_bytes'] or 0
        shared = sum(size(n) for n in names if len(refs[n]) > 1)
        exclusive = sum(size(n) for n in names if len(refs[n]) == 1)
        models.append({'name': record['name'], 'registry': record['registry'],
                       'manifest': record['manifest'], 'blobs': names,
                       'layers': record['layers'], 'size_bytes': shared + exclusive,
                       'shared_bytes': shared, 'exclusive_bytes': exclusive,
                       'missing_blobs': [n for n in names if by_name[n]['status'] == 'missing'],
                       'unavailable_blobs': [n for n in names if by_name[n]['status'] == 'unavailable'],
                       'size_mismatches': [n for n in names if by_name[n]['status'] == 'size_mismatch']})
    files.sort(key=lambda row: (-row['size_bytes'], row['model'], row['layer'], row['file_name']))
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'model_storage': str(root), 'scan_complete': complete,
            'snapshot_semantics': 'observed_non_transactional',
            'blob_hashes_verified': False, 'deletion_safe': False,
            'models': sorted(models, key=lambda model: model['name']),
            'blobs': blobs, 'files': files, 'errors': errors,
            'totals': {'models': len(models), 'present_files': len(on_disk),
                       'size_bytes': sum(on_disk.values()),
                       'referenced_bytes': sum(on_disk.get(n, 0) for n in refs),
                       'shared_bytes': sum(on_disk.get(n, 0) for n in refs if len(refs[n]) > 1)}}


def csv_bytes(rows) -> bytes:
    """Render the compatibility view; keep formula-like labels as Excel text."""
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator='\r\n')
    writer.writeheader()
    for row in rows:
        safe = {}
        for field in CSV_FIELDS:
            value = row[field]
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            safe[field] = value
        writer.writerow(safe)
    return stream.getvalue().encode('utf-8-sig')


def atomic_write(path: Path, payload: bytes) -> None:
    """Replace one whole derived file; retain the previous file on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def publish(index: dict, csv_path: Path) -> Path:
    """Publish JSON first and derived CSV second, each atomically.

    This is deliberately NOT a two-file transaction. csv_sha256 in the canonical
    JSON detects an interrupted or concurrent publication. Readers use JSON and
    may regenerate CSV; they must not treat mismatching CSV as a matching snapshot.
    """
    csv_path = Path(csv_path)
    if csv_path.name.casefold() == INDEX_NAME.casefold():
        raise ValueError('JSON and CSV output paths must be distinct')
    payload = csv_bytes(index['files'])
    document = dict(index, csv_sha256=hashlib.sha256(payload).hexdigest(),
                    csv_file=csv_path.name)
    json_path = csv_path.with_name(INDEX_NAME)
    atomic_write(json_path, (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    atomic_write(csv_path, payload)
    return json_path


def _interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('watch interval must be finite and greater than zero')
    return number


def main(argv=None) -> int:
    """Explicit foreground refresh; no runtime launch or implicit daemon."""
    parser = argparse.ArgumentParser(description='Refresh the read-only Ollama model inventory')
    parser.add_argument('model_dir', type=Path)
    parser.add_argument('--watch', type=_interval, metavar='SECONDS',
                        help='Refresh in the foreground until Ctrl+C; default is one scan')
    args = parser.parse_args(argv)
    from launcher.models import model_files
    try:
        while True:
            out = model_files.refresh(args.model_dir)
            if out is None:
                print('Unable to publish model inventory; check the store and output permissions.', file=sys.stderr)
                return 1
            print(str(out.with_name(INDEX_NAME)), flush=True)
            if args.watch is None:
                return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
