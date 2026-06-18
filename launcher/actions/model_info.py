"""actions.model_info — [5] 설치된 모델 정보."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import config
from ..presenter.base import Presenter
from ..services.ollama import OllamaService


# Windows pythonw.exe 환경에서 콘솔 깜빡임 차단
_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = config.WIN_CREATE_NO_WINDOW


def run(env: Path, p: Presenter) -> None:
    p.section("설치된 모델 정보")

    svc = OllamaService(env, logger=p)
    if not svc.is_installed():
        p.error(f"Ollama 미설치: {svc.exe}")
        p.pause()
        return

    if not svc.ensure_running():
        p.pause()
        return

    try:
        result = subprocess.run(
            [str(svc.exe), "list"],
            env=svc.env_vars(),
            capture_output=True, text=True, check=False,
            **_NO_WINDOW_KW,
        )
        # 결과를 Presenter 로 전달 (GUI 에선 패널에 표시, TUI 에선 콘솔)
        # MODELINFO_PURPOSE_v1: 각 모델에 용도 주석 + 용도별 권장 표
        _purpose = _model_purpose_map()
        for line in (result.stdout or "").splitlines():
            if not line.strip():
                continue
            _tok = line.split()
            _nm = _tok[0] if _tok else ""
            _use = _purpose.get(_nm) or _purpose.get(_nm.split(":")[0])
            p.info(line + ("    <- " + _use if _use else ""))
        if result.stderr and result.stderr.strip():
            p.warn(result.stderr.strip())
        _show_role_table(p)
    except Exception as e:
        p.error(f"모델 목록 조회 실패: {e}")

    p.pause()


# >>> MODELINFO_PURPOSE_v1 helper - 모델 용도 매핑 + 권장 표
def _model_purpose_map() -> dict:
    """모델 태그 -> 용도(라벨) 매핑. model_roles + config 기본 모델."""
    m: dict = {}
    try:
        from .. import model_roles as _mr
        for r in _mr.ROLES:
            for tag in (r.model, getattr(r, "fallback", None)):
                if tag:
                    m[tag] = r.label
                    m[tag.split(":")[0]] = r.label
    except Exception:
        pass
    try:
        from .. import config as _c
        mt = getattr(_c, "MODEL_TAG", None)
        if mt:
            m.setdefault(mt, "자동화 에이전트 기본")
            m.setdefault(mt.split(":")[0], "자동화 에이전트 기본")
    except Exception:
        pass
    return m


def _show_role_table(p) -> None:
    """용도별 권장 모델 표를 패널에 표시."""
    try:
        from .. import model_roles as _mr
        roles = getattr(_mr, "ROLES", None)
    except Exception:
        roles = None
    p.info("-" * 40)
    p.info("용도별 권장 모델")
    if not roles:
        p.info("  - 코딩: qwen2.5-coder:14b (부족 시 7b)")
        p.info("  - 무검열 검색/번역: huihui_ai/qwen3-abliterated:8b")
        p.info("  - 맥락/범용: qwen3:8b")
        return
    for r in roles:
        line = "  - " + r.label + " -> " + r.model
        if getattr(r, "fallback", None):
            line += " (부족 시 " + r.fallback + ")"
        p.info(line)
        if getattr(r, "description", ""):
            p.info("      " + r.description)
# <<< MODELINFO_PURPOSE_v1 helper
