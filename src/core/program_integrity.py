"""Is the shared program copy exactly what a Git commit says it is?

``C:\\LocalAI\\app`` is deployed from Git objects (``installer.steps.app``), not
from whatever a checkout's working tree happens to contain. ``VERSION.json``
beside it records the commit and, for every file, the Git blob id it came from
and the SHA-256 of the bytes written. That lets two different questions be
answered:

* **drift** (``verify``): does the copy still match its own manifest? A
  changed, missing or *added* file - an extra ``sitecustomize.py``, a swapped
  ``.pyc`` - is reported. This runs at every start and needs no Git.
* **origin** (``verify_against_tree``): does the manifest describe the commit
  it names? Run by Setup with the checkout's ``git ls-tree`` listing, so even a
  manifest rewritten after tampering cannot pass as that commit.

The ACL (administrators only) is what prevents changes; this module makes any
change that slips past it - an elevated process, offline editing, a damaged
disk - visible instead of silently run by every account.

This module only reads and hashes; it never writes or runs anything.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional

VERSION_FILE = 'VERSION.json'
SCHEMA = 2

#: Files Windows' ``cmd.exe`` must read with CRLF line ends: labels and
#: ``goto`` misbehave in LF-only batch files. Git stores them LF.
CRLF_SUFFIXES = ('.bat', '.cmd')


def git_blob_id(data: bytes) -> str:
    """The SHA-1 object id Git gives these exact bytes as a blob."""
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def needs_crlf(relpath: str) -> bool:
    return relpath.lower().endswith(CRLF_SUFFIXES)


def to_deployed(relpath: str, blob: bytes) -> bytes:
    """Bytes written for a blob: identical, except LF-only batch files."""
    if needs_crlf(relpath) and b'\r' not in blob:
        return blob.replace(b'\n', b'\r\n')
    return blob


def to_blob(relpath: str, data: bytes, eol: Optional[str]) -> bytes:
    """Undo ``to_deployed`` so a written file can be compared with Git again."""
    if eol == 'crlf':
        return data.replace(b'\r\n', b'\n')
    return data


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def walk(root) -> Iterable[Path]:
    """Every entry under ``root`` except the manifest itself, links included."""
    root = Path(root)
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in sorted(dirs):
            path = base / name
            if path.is_symlink() or _is_junction(path):
                yield path
        for name in sorted(files):
            path = base / name
            if base == root and name == VERSION_FILE:
                continue
            yield path


def _is_junction(path: Path) -> bool:
    check = getattr(path, 'is_junction', None)
    try:
        return bool(check()) if callable(check) else False
    except OSError:
        return False


def load(root) -> Optional[dict]:
    try:
        data = json.loads((Path(root) / VERSION_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def verify(root, manifest: Optional[dict] = None) -> List[str]:
    """Problems between the copy at ``root`` and its manifest; ``[]`` is clean.

    A copy without a schema-2 manifest is reported as unverifiable; callers
    decide whether that blocks (``is_legacy`` tells the two apart).
    """
    root = Path(root)
    manifest = load(root) if manifest is None else manifest
    if not manifest or manifest.get('schema') != SCHEMA or not isinstance(
            manifest.get('files'), dict):
        return ['무결성 정보(VERSION.json schema %d)가 없습니다' % SCHEMA]
    expected: Dict[str, dict] = manifest['files']
    problems: List[str] = []
    seen = set()
    for path in walk(root):
        rel = _relative(root, path)
        if path.is_symlink() or _is_junction(path):
            problems.append('연결(링크) 경로: ' + rel)
            continue
        seen.add(rel)
        entry = expected.get(rel)
        if entry is None:
            problems.append('추가된 파일: ' + rel)
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            problems.append('읽을 수 없음: %s (%s)' % (rel, exc))
            continue
        if sha256(data) != entry.get('sha256'):
            problems.append('변경된 파일: ' + rel)
    for rel in sorted(set(expected) - seen):
        problems.append('없어진 파일: ' + rel)
    return problems


def is_legacy(manifest: Optional[dict]) -> bool:
    """A copy deployed before manifests existed (no per-file record)."""
    return bool(manifest) and 'files' not in manifest and 'schema' not in manifest


def verify_against_tree(manifest: Optional[dict], tree: Dict[str, str]) -> List[str]:
    """Does the manifest describe exactly ``tree`` (``{path: blob id}``)?

    ``tree`` is the deployable part of ``git ls-tree -r <commit>``. Generated
    bytecode has no blob id and must sit beside a tracked source file.
    """
    if not manifest or manifest.get('schema') != SCHEMA:
        return ['무결성 정보가 없습니다']
    files = manifest.get('files') or {}
    problems = []
    for rel, blob in sorted(tree.items()):
        entry = files.get(rel)
        if entry is None:
            problems.append('커밋에 있는데 배포되지 않음: ' + rel)
        elif entry.get('git') != blob:
            problems.append('커밋과 다른 내용: ' + rel)
    for rel, entry in sorted(files.items()):
        if rel in tree:
            continue
        if entry.get('git') is not None or not _is_generated_bytecode(rel, tree):
            problems.append('커밋에 없는 파일: ' + rel)
    return problems


def _is_generated_bytecode(rel: str, tree: Dict[str, str]) -> bool:
    """``pkg/__pycache__/mod.cpython-313.pyc`` for a tracked ``pkg/mod.py``."""
    parts = rel.split('/')
    if len(parts) < 2 or parts[-2] != '__pycache__' or not parts[-1].endswith('.pyc'):
        return False
    module = parts[-1].split('.', 1)[0]
    source = '/'.join(parts[:-2] + [module + '.py'])
    return source in tree


#: The program actually running: core/ -> src/ -> program root. Derived from
#: this file, never from an environment variable a caller could redirect.
RUNNING_ROOT = Path(__file__).resolve().parents[2]


class IntegrityError(RuntimeError):
    """The shared program copy no longer matches the commit it was deployed from."""


def check_running_copy(root=None) -> Optional[str]:
    """Refuse to run a deployed copy that drifted from its manifest.

    A development checkout has no ``VERSION.json`` and is not checked. A copy
    deployed before manifests existed is allowed with a notice (returned) so
    an update does not lock anyone out; the next administrator Setup writes
    the manifest. Any other mismatch raises ``IntegrityError``.
    """
    root = RUNNING_ROOT if root is None else Path(root)
    if not (root / VERSION_FILE).is_file():
        return None
    manifest = load(root)
    if is_legacy(manifest):
        return ('이 공용 프로그램에는 무결성 정보가 없습니다. LocalAI 관리자가 Git 체크아웃에서 '
                '[설치 / 복구]를 실행하면 기록됩니다.')
    problems = verify(root, manifest)
    if problems:
        raise IntegrityError(
            '공용 프로그램(%s)이 배포된 Git 커밋 %s와 다릅니다. 변조되었을 수 있어 실행하지 '
            '않습니다.\n- %s\nLocalAI 관리자가 신뢰된 Git 체크아웃에서 RUN.bat --install 을 '
            '실행해 다시 배포하세요.'
            % (root, str((manifest or {}).get('commit') or '?')[:12],
               '\n- '.join(problems[:8]) + ('\n- ...' if len(problems) > 8 else '')))
    return None


__all__ = ['VERSION_FILE', 'SCHEMA', 'git_blob_id', 'sha256', 'needs_crlf',
           'to_deployed', 'to_blob', 'walk', 'load', 'verify', 'is_legacy',
           'verify_against_tree', 'check_running_copy', 'IntegrityError',
           'RUNNING_ROOT']
