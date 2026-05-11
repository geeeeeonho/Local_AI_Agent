"""installer.core.download — 진행률 표시 다운로드."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from .console import info, ok


def download_with_progress(url: str, dest: Path, label: str = ""):
    """진행률 표시 다운로드 (stdlib only).

    Raises:
        RuntimeError: 다운로드 실패
    """
    info(f"다운로드: {label or dest.name}")
    info(f"  → {dest}")

    def report(blocknum, blocksize, totalsize):
        if totalsize <= 0:
            return
        d = blocknum * blocksize
        pct = min(100, d * 100 / totalsize)
        mb_n = d / (1024 ** 2)
        mb_t = totalsize / (1024 ** 2)
        filled = int(30 * pct / 100)
        bar = "█" * filled + "░" * (30 - filled)
        sys.stdout.write(
            f"\r  [{bar}] {pct:5.1f}%  {mb_n:7.1f}/{mb_t:7.1f} MB"
        )
        sys.stdout.flush()

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest, reporthook=report)
        sys.stdout.write("\n")
        ok(f"완료 ({dest.stat().st_size / (1024 ** 2):.1f} MB)")
    except Exception as e:
        sys.stdout.write("\n")
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"다운로드 실패: {e}")
