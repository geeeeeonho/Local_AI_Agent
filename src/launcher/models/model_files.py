# -*- coding: utf-8 -*-
"""model_files — 디스크의 blob 파일과 모델 이름을 잇는 표.

MODEL_FILES_v1.

Ollama 는 받은 모델을 내용 해시로만 저장한다.

    C:\\LLM_Models\\
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
  orphan  : 어떤 manifest 도 안 쓰는 파일 (지워도 되는 잔여물)

같은 blob 을 여러 모델이 공유하는 일이 흔하다(같은 template/license, 같은 베이스
가중치). shared_with 열이 그 수를 보여 주므로, 모델 하나를 지운다고 그 파일이
사라진다고 오해하지 않게 한다.

stdlib 전용. Ollama 가 떠 있지 않아도 동작한다(파일만 읽는다).
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

CSV_NAME = "MODEL_FILES.csv"
MARKER = "MODEL_FILES_v1"

# manifest 의 mediaType -> 사람이 읽는 이름
_LAYER_NAMES = {
    "application/vnd.ollama.image.model": "weights",
    "application/vnd.ollama.image.projector": "projector",
    "application/vnd.ollama.image.adapter": "adapter",
    "application/vnd.ollama.image.template": "template",
    "application/vnd.ollama.image.system": "system",
    "application/vnd.ollama.image.params": "params",
    "application/vnd.ollama.image.prompt": "prompt",
    "application/vnd.ollama.image.license": "license",
    "application/vnd.ollama.image.messages": "messages",
}
_CONFIG_LAYER = "config"

FIELDS = ("file_name", "model", "role", "layer", "size_bytes", "size_gb",
          "shared_with", "status", "rel_path")


@dataclass(frozen=True)
class FileRow:
    file_name: str      # blobs 안의 실제 파일 이름 (sha256-...)
    model: str          # "gemma4:12b" 같은 모델 이름. orphan 이면 빈 문자열
    role: str           # 카탈로그 역할 라벨 (있으면)
    layer: str          # weights / template / params / license / ...
    size_bytes: int
    size_gb: float
    shared_with: int    # 이 파일을 함께 쓰는 모델 수 (1 이면 전용)
    status: str         # ok | missing | orphan
    rel_path: str       # 저장소 루트 기준 상대 경로


def _blob_file_name(digest: str) -> str:
    """manifest 의 'sha256:abcd' -> 디스크의 'sha256-abcd'."""
    return str(digest).replace(":", "-", 1)


def _model_name(manifest_root: Path, path: Path) -> str:
    """manifests/<host>/<ns>/<name>/<tag> -> 'ns/name:tag' (library 는 ns 생략)."""
    parts = path.relative_to(manifest_root).parts
    if len(parts) < 3:
        return ":".join(parts)
    tag = parts[-1]
    name = parts[-2]
    namespace = parts[-3]
    # parts[0] 은 레지스트리 호스트. library 네임스페이스는 표기에서 뺀다.
    if namespace == "library":
        return "%s:%s" % (name, tag)
    return "%s/%s:%s" % (namespace, name, tag)


def read_manifests(model_dir) -> Dict[str, dict]:
    """{모델이름: manifest dict}. 읽을 수 없는 파일은 건너뛴다."""
    root = Path(model_dir)
    manifest_root = root / "manifests"
    out: Dict[str, dict] = {}
    if not manifest_root.is_dir():
        return out
    for path in sorted(manifest_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or "layers" not in data:
            continue  # manifest 가 아닌 파일(.DS_Store 등)
        out[_model_name(manifest_root, path)] = data
    return out


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


def _iter_layers(manifest: dict):
    """(mediaType, digest, size) — config 레이어까지 포함."""
    config = manifest.get("config")
    if isinstance(config, dict) and config.get("digest"):
        yield _CONFIG_LAYER, config["digest"], int(config.get("size") or 0)
    for layer in manifest.get("layers") or []:
        if not isinstance(layer, dict) or not layer.get("digest"):
            continue
        media = layer.get("mediaType") or ""
        yield _LAYER_NAMES.get(media, media or "unknown"), layer["digest"], int(
            layer.get("size") or 0)


def scan(model_dir) -> List[FileRow]:
    """blob 하나당 한 행. 여러 모델이 공유하면 모델별로 행이 생긴다."""
    root = Path(model_dir)
    blobs_dir = root / "blobs"
    manifests = read_manifests(root)
    roles = _catalog_roles()

    on_disk: Dict[str, int] = {}
    if blobs_dir.is_dir():
        try:
            for entry in blobs_dir.iterdir():
                if entry.is_file():
                    try:
                        on_disk[entry.name] = entry.stat().st_size
                    except OSError:
                        on_disk[entry.name] = 0
        except OSError:
            pass

    # 먼저 blob 별 참조 모델 수를 센다 (shared_with 계산용)
    refs: Dict[str, List[str]] = {}
    for model, manifest in manifests.items():
        for _layer, digest, _size in _iter_layers(manifest):
            refs.setdefault(_blob_file_name(digest), []).append(model)

    rows: List[FileRow] = []
    referenced = set()
    for model in sorted(manifests):
        for layer, digest, declared in _iter_layers(manifests[model]):
            name = _blob_file_name(digest)
            referenced.add(name)
            actual = on_disk.get(name)
            size = actual if actual is not None else declared
            rows.append(FileRow(
                file_name=name,
                model=model,
                role=roles.get(model, ""),
                layer=layer,
                size_bytes=int(size),
                size_gb=round(int(size) / (1024 ** 3), 3),
                shared_with=len(set(refs.get(name, []))),
                status="ok" if actual is not None else "missing",
                rel_path=str(Path("blobs") / name),
            ))

    for name in sorted(set(on_disk) - referenced):
        size = on_disk[name]
        rows.append(FileRow(
            file_name=name, model="", role="", layer="unreferenced",
            size_bytes=int(size), size_gb=round(int(size) / (1024 ** 3), 3),
            shared_with=0, status="orphan",
            rel_path=str(Path("blobs") / name),
        ))

    # 큰 파일이 위로 — 폴더를 열어 본 사람이 가장 먼저 알고 싶은 순서.
    rows.sort(key=lambda r: (-r.size_bytes, r.model, r.layer))
    return rows


def _writable(path: Path) -> bool:
    """이미 있는 디렉터리에 쓸 수 있는지만 본다.

    없는 경로를 만들어 보지는 않는다 — 존재 확인용 프로브가 공용 모델 저장소를
    새로 만들어 버리면, 저장소가 아직 없다는 사실 자체가 사라진다.
    """
    if not path.is_dir():
        return False
    probe = path / ".model_files_write_probe"
    try:
        probe.write_text("", encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def default_csv_path(model_dir) -> Path:
    """가능하면 모델 저장소 옆에, 쓰기 권한이 없으면 user_data 로.

    저장소는 여러 사용자가 공유하도록 읽기/실행만 열어 두는 경우가 있어
    (README '경로 정책' 참고) 쓰기가 막힐 수 있다.
    """
    root = Path(model_dir)
    if _writable(root):
        return root / CSV_NAME
    try:
        from launcher.core import user_data
        fallback = user_data.root() / "models"
    except Exception:
        fallback = Path.cwd() / "user_data" / "models"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback / CSV_NAME


def write_csv(model_dir, path=None, rows: Optional[Iterable[FileRow]] = None
              ) -> Optional[Path]:
    """표를 CSV 로 저장하고 경로를 돌려준다. 실패하면 None.

    Excel 이 한글을 깨뜨리지 않도록 UTF-8 BOM 으로 쓴다. 줄바꿈은 newline=""
    + \\r\\n 으로 Windows Excel 기본과 맞춘다.
    """
    root = Path(model_dir)
    if path is None and not root.is_dir():
        return None  # 저장소가 없으면 적을 대응도 없다
    rows = list(rows) if rows is not None else scan(root)
    out = Path(path) if path is not None else default_csv_path(root)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(FIELDS),
                                    lineterminator="\r\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: asdict(row)[k] for k in FIELDS})
        return out
    except OSError:
        return None


def summary_lines(rows: Iterable[FileRow]) -> List[str]:
    """콘솔/패널에 그대로 찍을 수 있는 요약."""
    rows = list(rows)
    weights = [r for r in rows if r.layer == "weights" and r.status == "ok"]
    missing = [r for r in rows if r.status == "missing"]
    orphans = [r for r in rows if r.status == "orphan"]
    unique_bytes = {r.file_name: r.size_bytes for r in rows if r.status != "missing"}
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
    return out


def refresh(model_dir, log=None) -> Optional[Path]:
    """설치/삭제 뒤에 부르는 진입점. 실패해도 예외를 올리지 않는다."""
    try:
        rows = scan(model_dir)
        out = write_csv(model_dir, rows=rows)
    except Exception:
        return None
    if log:
        try:
            if out:
                log("모델 파일 목록: " + str(out))
                for line in summary_lines(rows):
                    log("  " + line)
            else:
                log("모델 파일 목록을 쓰지 못했습니다 (쓰기 권한 확인).")
        except Exception:
            pass
    return out


__all__ = ["FileRow", "FIELDS", "CSV_NAME", "MARKER",
           "read_manifests", "scan", "write_csv", "default_csv_path",
           "summary_lines", "refresh"]
