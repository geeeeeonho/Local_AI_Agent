"""utils — 호환 shim.

신규 코드는 installer.core.* 직접 사용 권장.
기존 `from . import utils; utils.section(...)` 보존.

이전: 350+ 라인의 단일 파일.
이후: 본 shim + 4개 책임별 모듈 (console/preflight/download/filesystem).
"""
from .core.console import (
    C, init_console,
    section, info, ok, warn, err,
    finalize_summary,
)
from .core.preflight import (
    preflight_windows, preflight_python, preflight_disk,
)
from .core.download import download_with_progress
from .core.filesystem import create_environment

__all__ = [
    "C", "init_console",
    "section", "info", "ok", "warn", "err",
    "preflight_windows", "preflight_python", "preflight_disk",
    "download_with_progress",
    "create_environment",
    "finalize_summary",
]
