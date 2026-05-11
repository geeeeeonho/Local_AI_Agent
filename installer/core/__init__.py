"""installer.core — 핵심 유틸 (분할 결과).

이전: installer/utils.py 한 파일에 콘솔/사전검사/다운로드/폴더생성 모두 포함.
변경: 책임별로 4개 모듈로 분할.

호환성:
    `installer.utils` 는 shim 으로 모두 re-export → 기존 `from installer import utils` 보존.
"""
from .console import (
    C, init_console,
    section, info, ok, warn, err,
    finalize_summary,
)
from .preflight import (
    preflight_windows, preflight_python, preflight_disk,
)
from .download import download_with_progress
from .filesystem import create_environment

__all__ = [
    "C", "init_console",
    "section", "info", "ok", "warn", "err",
    "preflight_windows", "preflight_python", "preflight_disk",
    "download_with_progress",
    "create_environment",
    "finalize_summary",
]
