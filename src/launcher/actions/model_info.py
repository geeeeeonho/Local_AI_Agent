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
        _show_file_map(svc, p)
    except Exception as e:
        p.error(f"모델 목록 조회 실패: {e}")

    p.pause()


def _show_file_map(svc, p) -> None:
    """MODEL_FILES_v1: 저장소의 sha256-... 파일이 어느 모델인지 보여 주고 CSV 로 남긴다.

    저장소를 열어 보면 이름 없는 blob 만 있어서, 어느 파일이 무엇인지 · 지워도
    되는지 알 수 없다. 여기서 그 대응을 한 번 보여 주고 표를 갱신한다.
    """
    try:
        from launcher.models import model_files as mf
    except Exception:
        return
    p.info("-" * 40)
    p.info("저장소 파일 -> 모델 (" + str(svc.model_dir) + ")")
    try:
        rows = mf.scan(svc.model_dir)
    except Exception as e:
        p.warn("저장소를 읽지 못했습니다: %r" % e)
        return
    if not rows:
        p.info("  저장소에 모델 파일이 없습니다.")
        return
    for line in mf.summary_lines(rows):
        p.info("  " + line)
    out = mf.write_csv(svc.model_dir, rows=rows)
    if out:
        p.info("  전체 표(CSV): " + str(out))
    else:
        p.warn("  CSV 를 쓰지 못했습니다 (저장소 쓰기 권한 확인).")


# >>> MODELINFO_PURPOSE_v1 helper - 모델 용도 매핑 + 권장 표
def _model_purpose_map() -> dict:
    """모델 태그 -> 용도(라벨) 매핑. model_roles + config 기본 모델."""
    m: dict = {}
    try:
        from launcher.models import model_roles as _mr
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
    """용도별 권장 모델 표를 패널에 표시.

    사다리 1단계(최고 품질)와 '지금 이 PC 에서 실제로 뜰 모델'을 함께 보여준다.
    예전에는 1단계만 찍어서, 그 모델이 미설치라 다른 게 뜨는 상황에서도
    화면은 계속 1단계를 권장 모델이라고 안내했다.
    """
    try:
        from launcher.models import model_roles as _mr
        roles = getattr(_mr, "ROLES", None)
    except Exception:
        _mr, roles = None, None
    p.info("-" * 40)
    p.info("용도별 권장 모델")
    if not roles:
        p.info("  모델 레지스트리를 불러오지 못했습니다 — SETUP.bat --manage 에서 확인하세요.")
        return
    for r in roles:
        p.info("  - " + r.label + " -> " + r.model + _actual_suffix(_mr, r))
        if getattr(r, "description", ""):
            p.info("      " + r.description)


def _actual_suffix(mr, role) -> str:
    """'-> 실제 사용' 꼬리표. 조회 실패 시 조용히 빈 문자열."""
    if mr is None:
        return ""
    try:
        actual = mr.resolve_ladder(role.name)
    except Exception:
        return ""
    if not actual or actual == role.model:
        return ""
    return "   (현재 여유/설치 기준 실제 사용: " + actual + ")"
# <<< MODELINFO_PURPOSE_v1 helper
