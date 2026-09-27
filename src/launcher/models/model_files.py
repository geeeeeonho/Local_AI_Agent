# -*- coding: utf-8 -*-
"""model_files — 디스크의 blob 파일과 모델 이름을 잇는 표.

MODEL_INDEX.json is authoritative; MODEL_FILES.csv is its human-readable derived view.

Ollama 는 받은 모델을 내용 해시로만 저장한다.

    C:\\LocalAI\\models\\
      blobs\\sha256-3f1c...           <- 실제 가중치. 이름만 봐선 뭔지 알 수 없다
      manifests\\registry.ollama.ai\\
        library\\gemma4\\12b           <- 이 JSON 이 위 해시를 가리킨다
        prutser\\gemma-4-...\\Q4_K_S

그래서 폴더를 열어 보면 15GB 짜리 `sha256-...` 파일들만 있고 어느 모델인지,
지워도 되는지 알 수 없다. 이 모듈이 manifest 를 읽어 blob -> 모델 이름 표를
만들고 `MODEL_FILES.csv` 로 저장한다.

세 가지를 구분해서 알려 준다.
  ok      : manifest 가 가리키고 실제로 있는 파일
  missing : manifest 는 가리키는데 파일이 없다 (받다 만 모델 — 다시 pull 해야 함)
  orphan  : unreferenced candidate, NEVER permission to delete during a live pull

같은 blob 을 여러 모델이 공유하는 일이 흔하다(같은 template/license, 같은 베이스
가중치). shared_with 열이 그 수를 보여 주므로, 모델 하나를 지운다고 그 파일이
사라진다고 오해하지 않게 한다.

stdlib 전용. Ollama 가 떠 있지 않아도 동작한다(파일만 읽는다).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import model_index as _index

CSV_NAME = _index.CSV_NAME
INDEX_NAME = _index.INDEX_NAME


@dataclass(frozen=True)
class FileRow:
    file_name: str      # blobs 안의 실제 파일 이름 (sha256-...)
    model: str          # "gemma4:12b" 같은 모델 이름. orphan 이면 빈 문자열
    role: str           # 카탈로그 역할 라벨 (있으면)
    layer: str          # weights / template / params / license / ...
    size_bytes: int
    size_gb: float
    shared_with: int    # 이 파일을 함께 쓰는 모델 수 (1 이면 전용)
    status: str         # ok | missing | size_mismatch | partial | orphan | unknown | unavailable
    rel_path: str       # 저장소 루트 기준 상대 경로


def build_index(model_dir) -> dict:
    """Build the canonical, non-destructive model inventory in memory."""
    return _index.build_index(model_dir, roles=_catalog_roles())


def _catalog_roles() -> Dict[str, str]:
    try:
        from . import model_catalog as cat
    except Exception:
        try:
            from launcher.models import model_catalog as cat
        except Exception:
            return {}
    try:
        return {e.tag: e.role for e in cat.all_entries()}
    except Exception:
        return {}


def default_csv_path(model_dir) -> Path:
    """The one machine-wide CSV beside the shared model store.

    A permission failure is a setup/ACL error, not a reason to create a second
    per-account truth. Callers surface the failure and keep the previous shared
    snapshot intact.
    """
    import project_paths
    return project_paths.model_files_path(model_dir)


def summary_lines(rows: Iterable[FileRow]) -> List[str]:
    """콘솔/패널에 그대로 찍을 수 있는 요약."""
    rows = list(rows)
    weights = [r for r in rows if r.layer == "weights" and r.status == "ok"]
    missing = [r for r in rows if r.status == "missing"]
    orphans = [r for r in rows if r.status == "orphan"]
    unique_bytes = {r.file_name: r.size_bytes for r in rows if r.status not in {"missing", "unavailable"}}
    total_gb = sum(unique_bytes.values()) / (1024 ** 3)

    out = ["모델 %d개 · 파일 %d개 · 합계 %.1fGB"
           % (len({r.model for r in rows if r.model}), len(unique_bytes), total_gb)]
    for r in sorted(weights, key=lambda x: -x.size_bytes):
        share = ("  (공유 %d모델)" % r.shared_with) if r.shared_with > 1 else ""
        out.append("  %-52s %6.1fGB  %s%s" % (r.model, r.size_gb, r.file_name[:19], share))
    if missing:
        out.append("  받다 만 파일 %d개 — 해당 모델을 다시 pull 하세요: %s"
                   % (len(missing), ", ".join(sorted({r.model for r in missing})[:5])))
    if orphans:
        gb = sum(r.size_bytes for r in orphans) / (1024 ** 3)
        out.append("  참조 없는 잔여 파일 %d개 (%.1fGB) — `ollama rm` 후 남은 것일 수 있습니다."
                   % (len(orphans), gb))
    for status in ("partial", "size_mismatch", "unavailable", "unknown", "unreferenced_unknown"):
        names = sorted({r.file_name for r in rows if r.status == status})
        if names:
            out.append("  %s: %d files - %s" % (status, len(names), ", ".join(names[:3])))
    if orphans or any(r.status in {"partial", "unreferenced_unknown"} for r in rows):
        out.append("  Inventory is not deletion approval; concurrent downloads may still own these files.")
    return out


def _log_message(log, message: str) -> None:
    """Diagnostics must not make an optional inventory refresh fail."""
    if log is not None:
        try:
            log(message)
        except Exception:
            pass


def refresh(model_dir, log=None) -> Optional[Path]:
    """Publish one JSON/CSV snapshot, reporting failures without raising them."""
    try:
        if not Path(model_dir).is_dir():
            _log_message(log, "Model store is missing or inaccessible: " + str(model_dir))
            return None
        index = build_index(model_dir)
        rows = [FileRow(**row) for row in index["files"]]
        out = default_csv_path(model_dir)
        _index.publish(index, out)
    except Exception as exc:
        _log_message(log, "Unable to publish model inventory for %s: %s: %s"
                     % (model_dir, type(exc).__name__, exc))
        return None
    _log_message(log, "모델 파일 목록: " + str(out))
    _log_message(log, "MODEL_INDEX.json: " + str(out.with_name(INDEX_NAME)))
    if not index["scan_complete"]:
        _log_message(log, "scan_complete=false: references are incomplete; no cleanup conclusion is safe.")
        for error in index["errors"]:
            _log_message(log, "  " + error["path"] + ": " + error["reason"])
    for line in summary_lines(rows):
        _log_message(log, "  " + line)
    return out


__all__ = ["FileRow", "CSV_NAME", "INDEX_NAME", "build_index",
           "default_csv_path", "summary_lines", "refresh"]
