"""installer.core.preflight — 설치 전 환경 검사."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .console import ok, err, warn


def preflight_windows():
    """Windows 운영체제 확인."""
    try:
        from ..i18n import t
    except Exception:
        t = lambda k, **kw: k

    if os.name != "nt":
        err(t("install.preflight_windows_fail", os=os.name))
        sys.exit(1)
    ok(t("install.preflight_windows_ok"))


def preflight_python(min_version: tuple = (3, 11)):
    """Python 버전 확인."""
    try:
        from ..i18n import t
    except Exception:
        t = lambda k, **kw: k

    if sys.version_info < min_version:
        err(t("install.preflight_python_fail",
              min_ver=f"{min_version[0]}.{min_version[1]}",
              ver=sys.version.split()[0]))
        sys.exit(1)
    ok(t("install.preflight_python_ok", ver=sys.version.split()[0]))


def preflight_disk(parent: Path, need_gb: int):
    """디스크 여유 공간 확인."""
    try:
        from ..i18n import t
    except Exception:
        t = lambda k, **kw: k

    try:
        target = parent if parent.exists() else parent.parent
        free = shutil.disk_usage(target).free / (1024 ** 3)
        if free < need_gb:
            err(t("install.preflight_disk_fail", gb=free, need=need_gb))
            sys.exit(1)
        ok(t("install.preflight_disk_ok", gb=free))
    except Exception:
        warn(t("install.preflight_disk_unknown"))
