# -*- coding: utf-8 -*-
"""user_data — 영속 데이터 루트 관리 (USER_DATA_v1).

프로젝트 루트(`Local_AI/`) 아래 `user_data/` 폴더를 단일 진실 공급원으로 두고,
설정 / 로그 / 일반챗 / 인터프리터(샌드박스·호스트) 세션 데이터를 보관한다.

구조::

    user_data/
      settings/                 # 설정값 (현 launcher/settings 에서 점진 이전)
      logs/                     # 실행/세션 로그 (현 logs 에서 점진 이전)
      chat/                     # 일반챗 대화별 저장소 (현재 예약)
      interpreter/
        sandbox/                # [2] 샌드박스 에이전트 세션 JSON
        host/                   # [3] 호스트직접 에이전트 세션 JSON

설계 원칙
─────────
- 호스트 측에서 import 해 쓰는 모듈이다. (컨테이너 안 미니루프는 자체 stdlib
  저장 로직을 쓰고, 호스트가 마운트한 폴더에 기록한다 — 2단계에서 배선.)
- 모든 쓰기는 원자적(tmp + os.replace).
- 디렉터리는 접근 시 지연 생성(lazy) + ensure_all() 로 일괄 생성 둘 다 지원.
- 기존 코드/경로를 건드리지 않는 순수 추가 모듈. (설정/로그 실제 이전은 3단계)
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, List, Optional

__all__ = [
    "project_root", "root",
    "settings_dir", "logs_dir", "chat_dir", "interpreter_dir",
    "ensure_all",
    "save_json", "load_json",
    "new_session_id", "session_path", "list_sessions", "latest_session",
    "session_meta",
]

# 인터프리터 종류 (= "타입 두 개")
INTERPRETER_KINDS = ("sandbox", "host")

# user_data 하위 기본 레이아웃 (상대 경로)
_LAYOUT = (
    "settings",
    "logs",
    "chat",
    "interpreter/sandbox",
    "interpreter/host",
)


# ─────────────────────────────────────────────
#  경로
# ─────────────────────────────────────────────
def project_root() -> Path:
    """프로젝트 루트.

    이 파일은 `launcher/user_data.py` 로 배치되므로
    parent(=launcher) 의 parent 가 프로젝트 루트(Local_AI).
    환경변수 LLM_PROJECT_ROOT 가 있으면 그것을 우선한다(테스트/이식성).
    """
    ov = os.environ.get("LLM_PROJECT_ROOT")
    if ov:
        return Path(ov).resolve()
    return Path(__file__).resolve().parent.parent


def root() -> Path:
    """user_data 루트 경로 (생성하지는 않음)."""
    return project_root() / "user_data"


def _sub(*parts: str) -> Path:
    """하위 폴더 경로 반환 + 지연 생성."""
    d = root().joinpath(*parts)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def settings_dir() -> Path:
    return _sub("settings")


def logs_dir() -> Path:
    return _sub("logs")


def chat_dir() -> Path:
    return _sub("chat")


def interpreter_dir(kind: str = "sandbox") -> Path:
    """인터프리터 세션 폴더. kind ∈ {'sandbox','host'} (그 외엔 sandbox 로 폴백)."""
    k = kind if kind in INTERPRETER_KINDS else "sandbox"
    return _sub("interpreter", k)


# ─────────────────────────────────────────────
#  스켈레톤 생성
# ─────────────────────────────────────────────
_README = (
    "이 폴더(user_data)는 프로그램이 종료돼도 보존되는 사용자 데이터 저장소입니다.\n"
    "\n"
    "  settings/            설정값\n"
    "  logs/                실행/세션 로그\n"
    "  chat/                일반챗 대화별 저장소 (예약)\n"
    "  interpreter/sandbox/ [2] 샌드박스 에이전트 세션 (대화/작업 기억 JSON)\n"
    "  interpreter/host/    [3] 호스트직접 에이전트 세션\n"
    "\n"
    "인터프리터 세션 JSON 은 매 턴 자동 저장되며, 다음 실행 시 '이어하기' 로\n"
    "복원할 수 있습니다. 이 폴더를 지우면 모든 작업 기억이 사라집니다.\n"
)


def ensure_all() -> Path:
    """user_data 전체 스켈레톤을 생성하고 루트 경로를 반환. (멱등)"""
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    for rel in _LAYOUT:
        (r / rel).mkdir(parents=True, exist_ok=True)
    readme = r / "README.txt"
    if not readme.exists():
        try:
            readme.write_text(_README, encoding="utf-8")
        except OSError:
            pass
    return r


# ─────────────────────────────────────────────
#  원자적 JSON 입출력
# ─────────────────────────────────────────────
def save_json(path: Any, obj: Any) -> bool:
    """obj 를 JSON 으로 원자적 저장(tmp + os.replace). 성공 시 True."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            if tmp.exists():  # type: ignore[name-defined]
                tmp.unlink()
        except Exception:
            pass
        return False


def load_json(path: Any, default: Any = None) -> Any:
    """JSON 로드. 실패하면 default 반환."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


# ─────────────────────────────────────────────
#  인터프리터 세션 헬퍼
# ─────────────────────────────────────────────
def new_session_id() -> str:
    """타임스탬프 기반 세션 ID (정렬하면 시간순)."""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def session_path(kind: str, session_id: str) -> Path:
    """특정 세션 JSON 파일 경로."""
    return interpreter_dir(kind) / ("session_" + session_id + ".json")


def list_sessions(kind: str) -> List[Path]:
    """해당 종류의 세션 파일을 최신순으로 반환."""
    d = interpreter_dir(kind)
    try:
        files = list(d.glob("session_*.json"))
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def latest_session(kind: str) -> Optional[Path]:
    """가장 최근 세션 파일 (없으면 None)."""
    files = list_sessions(kind)
    return files[0] if files else None


def session_meta(path: Any) -> dict:
    """세션 JSON 에서 사람이 읽을 요약 메타를 추출(복원 메뉴 표시용).

    반환: {id, kind, model, workspace, turns, created, updated, preview}
    누락 필드는 빈 값/0 으로 채운다. 로드 실패 시 최소 정보만.
    """
    p = Path(path)
    data = load_json(p, default={}) or {}
    msgs = data.get("messages") or []
    # user 메시지 첫 줄을 미리보기로
    preview = ""
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            lines = str(m.get("content", "")).strip().splitlines()
            if lines:
                preview = lines[0]
                break
    # 턴 수 = user 메시지 수 (대략)
    turns = sum(1 for m in msgs if isinstance(m, dict) and m.get("role") == "user")
    return {
        "id": data.get("id") or p.stem.replace("session_", ""),
        "kind": data.get("kind", ""),
        "model": data.get("model", ""),
        "workspace": data.get("workspace", ""),
        "turns": turns,
        "created": data.get("created", ""),
        "updated": data.get("updated", ""),
        "preview": preview or "",
    }
