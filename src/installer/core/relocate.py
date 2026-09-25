"""Move a folder to where this product now keeps it, and prove it arrived.

Setup has to relocate directories a user cannot afford to lose: a model store
that took a day to download, the managed environment, and the settings and
projects under ``user_data``. A plain ``shutil.move`` is not good enough for
any of them. Interrupt a cross-volume copy - the installer is closed, the
laptop sleeps, the drive fills - and the destination is left holding a
half-written tree that looks exactly like a finished one. The next run then
"finds" the models already in place and the user is short forty gigabytes with
nothing to point at.

So every move goes through a staging folder beside the target:

1. same volume - ``os.replace`` renames the directory. Atomic; nothing to resume.
2. other volume - copy into staging, write a marker naming the source, delete
   the source, then rename staging onto the target.

At every interruption point the next run can tell a finished copy from a
partial one: staging without a marker while the source still exists is
wreckage, so it is discarded and the move restarts from the source; staging
with a marker, or staging with no source left, is the only surviving copy, so
it is promoted.

Afterwards the target is measured and compared with what the source held. A
move that reports success while losing files is the failure this module exists
to prevent, so the count is checked rather than assumed.
"""
from __future__ import annotations

import errno
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: Written inside staging once a cross-volume copy is complete. Its second line
#: names the source, so a resumed run knows which original it may delete.
MARKER_NAME = ".LOCAL_AI_MIGRATION_COMPLETE"
STAGING_SUFFIX = ".migrating"


@dataclass
class Result:
    """What a relocation did, in the terms a user needs to hear."""

    target: Path
    moved_from: Path | None = None
    files: int = 0
    total_bytes: int = 0
    verified: bool = False
    promoted: bool = False
    leftovers: list = field(default_factory=list)
    problem: str = ''

    @property
    def changed(self) -> bool:
        return self.moved_from is not None or self.promoted


def measure(path) -> tuple:
    """(file count, total bytes) under ``path``. Missing path counts as empty.

    Walked with ``scandir`` rather than ``rglob`` because a model store holds
    thousands of blob files and the difference is seconds, not milliseconds.
    """
    path = Path(path)
    files = total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except (OSError, ValueError):
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                else:
                    files += 1
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return files, total


def human_bytes(value: int) -> str:
    step = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if step < 1024 or unit == 'TB':
            return ('%.0f%s' if unit == 'B' else '%.1f%s') % (step, unit)
        step /= 1024
    return '%.1fTB' % step         # pragma: no cover - loop always returns


def staging_for(target) -> Path:
    target = Path(target)
    return target.with_name(target.name + STAGING_SUFFIX)


def is_empty_dir(path) -> bool:
    try:
        with os.scandir(path) as entries:
            return next(iter(entries), None) is None
    except (OSError, ValueError):
        return False


def _discard(staging: Path) -> None:
    if staging.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
    elif staging.exists():
        try:
            staging.unlink()
        except OSError:
            pass


def _promote(staging: Path, target: Path) -> None:
    marker = staging / MARKER_NAME
    try:
        marker.unlink()
    except OSError:
        pass
    staging.replace(target)


def _marker_origin(marker: Path):
    try:
        lines = marker.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    return Path(lines[1]) if len(lines) > 1 and lines[1].strip() else None


def resume(target, sources) -> bool:
    """Deal with a staging folder an interrupted run left behind.

    Returns True when a finished copy was promoted onto ``target``.
    """
    target = Path(target)
    staging = staging_for(target)
    marker = staging / MARKER_NAME
    sources = [Path(s) for s in sources]
    if not staging.exists():
        return False
    if not marker.is_file():
        if any(source.exists() for source in sources):
            # The source is still there, so staging is an unfinished copy of it.
            _discard(staging)
            return False
        # No source left: a same-volume rename finished and the run stopped
        # before the promote. Discarding staging here would delete the only copy.
        _promote(staging, target)
        return True
    origin = _marker_origin(marker)
    if origin is None:
        present = [s for s in sources if s.exists()]
        origin = present[0] if len(present) == 1 else None
    if origin is not None and origin.exists():
        shutil.rmtree(origin, ignore_errors=True)
    _promote(staging, target)
    return True


def move(source, target) -> None:
    """Move one directory onto ``target`` through staging."""
    source, target = Path(source), Path(target)
    staging = staging_for(target)
    marker = staging / MARKER_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Same volume: an atomic rename, with nothing half-written in between.
        source.replace(staging)
    except OSError as exc:
        cross_volume = exc.errno == errno.EXDEV or getattr(exc, 'winerror', None) == 17
        if not cross_volume:
            raise
        # Other volume: copy, record completion, then remove the source. A copy
        # that fails leaves the source intact and no marker, so the next run
        # discards the partial staging and starts again.
        shutil.copytree(source, staging, copy_function=shutil.copy2, symlinks=True)
        marker.write_text('complete\n%s\n' % source, encoding='utf-8')
        shutil.rmtree(source)
    _promote(staging, target)


def relocate(sources, target, *, say=None, label='') -> Result:
    """Bring the first surviving ``sources`` entry to ``target``, verified.

    ``target`` already holding data is never merged into: two model stores with
    overlapping blobs is a data question this installer has no right to answer
    on its own. It reports what it left alone instead.
    """
    target = Path(target)
    sources = [Path(s) for s in sources if Path(s) != target]
    result = Result(target=target)
    speak = say if callable(say) else (lambda message: None)

    # An earlier run that only managed to create the empty destination must not
    # block the move; an empty folder holds nothing to lose.
    if target.is_dir() and is_empty_dir(target):
        try:
            target.rmdir()
        except OSError:
            pass

    if not target.exists():
        result.promoted = resume(target, sources)

    if target.exists():
        staging = staging_for(target)
        result.leftovers = ([s for s in sources if s.exists()]
                            + ([staging] if staging.exists() else []))
        if result.promoted:
            result.files, result.total_bytes = measure(target)
            result.verified = True
            speak('%s 이전을 마쳤습니다 → %s' % (label or str(target), target))
        return result

    for source in sources:
        if not source.exists():
            continue
        expected = measure(source)
        move(source, target)
        result.moved_from = source
        result.files, result.total_bytes = measure(target)
        result.verified = (result.files, result.total_bytes) == expected
        if not result.verified:
            result.problem = (
                '%s 을(를) 옮긴 뒤 내용이 달라졌습니다: 원본 %d개 / %s, '
                '옮긴 뒤 %d개 / %s. 원본 위치를 확인하세요.'
                % (label or str(source), expected[0], human_bytes(expected[1]),
                   result.files, human_bytes(result.total_bytes)))
        else:
            speak('%s → %s (%d개 / %s 확인)'
                  % (source, target, result.files, human_bytes(result.total_bytes)))
        break
    return result


__all__ = ['MARKER_NAME', 'STAGING_SUFFIX', 'Result', 'measure', 'human_bytes',
           'staging_for', 'is_empty_dir', 'resume', 'move', 'relocate']
