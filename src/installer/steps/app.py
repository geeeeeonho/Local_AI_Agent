"""installer.steps.app — the one copy of the program every account runs.

Each Windows account used to run LocalAI from its own checkout. Now Setup
copies the program to ``C:\\LocalAI\\app`` and every account starts it from
there through one shortcut: one version on the machine, updated in one place
by a LocalAI administrator, readable and executable - not writable - by
everyone else. The account folder ACLs stay as they are; the app inherits the
shared root's (administrators full control, every account read/execute).

The copy is built beside the live one and swapped in, so an account running
the old version while an administrator updates never sees half of each.
"""
from __future__ import annotations

import compileall
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..core.console import info, ok, warn

#: What the program is. Tests, caches and the user's own runtime state are not.
_TOP_LEVEL = ("src", "RUN.bat", "README.md", "STUDIO.md")
_SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache", ".git", ".mypy_cache"}
_SKIP_SUFFIXES = (".pyc", ".pyo")

VERSION_FILE = "VERSION.json"


def _ignore(directory, names):
    return [name for name in names
            if name in _SKIP_DIRS or name.endswith(_SKIP_SUFFIXES)]


def source_revision(source: Path) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(source), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False,
                                creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else None


def same_place(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))
    except OSError:
        return False


def deploy(source: Path, target: Path) -> bool:
    """Copy the program from ``source`` (a checkout) to ``target``.

    True when ``target`` now holds this version - including when Setup is
    already running from it. Failure leaves the previous copy untouched.
    """
    source, target = Path(source), Path(target)
    if same_place(source, target):
        info("공용 프로그램에서 실행 중입니다: %s" % target)
        return True
    if not (source / "src").is_dir() or not (source / "RUN.bat").is_file():
        warn("프로그램 원본을 찾지 못해 공용 프로그램을 갱신하지 않았습니다: %s" % source)
        return False
    staging = target.with_name(target.name + ".new")
    retired = target.with_name(target.name + ".old")
    try:
        for leftover in (staging, retired):
            if leftover.exists():
                shutil.rmtree(leftover, ignore_errors=True)
        staging.mkdir(parents=True)
        for name in _TOP_LEVEL:
            item = source / name
            if item.is_dir():
                shutil.copytree(item, staging / name, ignore=_ignore)
            elif item.is_file():
                shutil.copy2(item, staging / name)
        # Every account runs this copy, and none of them may write into it, so
        # bytecode has to exist before the first start instead of each account
        # compiling its own in memory.
        compileall.compile_dir(str(staging / "src"), quiet=1, workers=0)
        revision = source_revision(source)
        (staging / VERSION_FILE).write_text(json.dumps({
            "revision": revision,
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            os.replace(target, retired)
        os.replace(staging, target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if retired.exists() and not target.exists():
            try:
                os.replace(retired, target)
            except OSError:
                pass
        warn("공용 프로그램을 갱신하지 못했습니다 (다른 계정이 실행 중일 수 있습니다): %s" % exc)
        return False
    shutil.rmtree(retired, ignore_errors=True)
    ok("공용 프로그램 갱신: %s%s" % (target, (" (" + revision + ")") if revision else ""))
    return True


def installed_revision(target: Path) -> Optional[str]:
    try:
        data = json.loads((Path(target) / VERSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("revision") if isinstance(data, dict) else None
    return str(value) if value else None


__all__ = ["deploy", "installed_revision", "same_place", "source_revision", "VERSION_FILE"]
