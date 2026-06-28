"""model — 역할별 모델 다운로드 (model_roles 레지스트리 기반, 멱등).

기존 단일 Gemma 모델 대신, 4개 역할(무검열 검색/번역 · 코딩 · 맥락 · 균형)에
필요한 모델을 순회 설치한다. 코딩 역할은 14b(기본) + 7b(대체)를 모두 받는다.
이미 설치된 모델은 `ollama list` 로 확인해 건너뛴다(멱등 — 재실행 안전).

설치기의 다른 단계와 동일하게 installer.core 콘솔 출력을 쓰고,
인터페이스(download(paths))는 기존과 동일하게 유지해 __main__ 호출부를 보존한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import utils, ollama
from .i18n import get_language

# model_roles 가 없을 때를 대비한 인라인 폴백 (역할 라벨, 모델)
# MODEL_FINAL_v8 inline 폴백 (model_roles import 실패 시)
_INLINE: List[Tuple[str, str]] = [
    ("무검열 검색/번역", "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"),
    ("무검열 검색/번역 (대체)", "huihui_ai/qwen3-abliterated:8b"),
    ("코딩 (기본)", "qwen3-coder:30b"),  # CATALOG_ALIGN_v9
    ("코딩 (대체 7b)", "qwen2.5-coder:7b"),
    ("맥락/균형", "gemma4:12b"),
    ("자동화 에이전트", "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"),
]

# 자체 ko/en 메시지 (i18n.py 를 건드리지 않기 위해 모듈 로컬)
_MSG = {
    "ko": {
        "section": "역할별 모델 다운로드 (5역할)",
        "intro": "한 번에 하나만 메모리에 적재되므로 RAM 무관, 디스크만 사용합니다.",
        "list_head": "현재 설치된 모델: ",
        "skip": "  [건너뜀] {label} :: {tag} (이미 설치됨)",
        "pull": "  [받는 중] {label} :: {tag}",
        "done": "  [완료] {tag}",
        "fail": "  [실패] {tag} (rc={rc})",
        "summary": "요약 — 받음 {pulled} · 건너뜀 {skipped} · 실패 {failed}",
        "all_ok": "모든 역할 모델 준비 완료.",
        "some_fail": "일부 모델을 받지 못했습니다. 네트워크 확인 후 INSTALL.bat 재실행 시 받지 못한 것만 다시 시도합니다.",
        "no_exe": "ollama.exe 를 찾을 수 없어 모델 단계를 건너뜁니다.",
    },
    "en": {
        "section": "Download role models (5 roles)",
        "intro": "Only one model is loaded at a time, so disk is used (not extra RAM).",
        "list_head": "Currently installed: ",
        "skip": "  [SKIP] {label} :: {tag} (already installed)",
        "pull": "  [PULL] {label} :: {tag}",
        "done": "  [DONE] {tag}",
        "fail": "  [FAIL] {tag} (rc={rc})",
        "summary": "Summary - pulled {pulled} / skipped {skipped} / failed {failed}",
        "all_ok": "All role models are ready.",
        "some_fail": "Some models failed. Re-running INSTALL.bat will retry only the missing ones.",
        "no_exe": "ollama.exe not found - skipping model step.",
    },
}


def _m(key: str, **kw) -> str:
    d = _MSG.get(get_language(), _MSG["en"])
    return d.get(key, _MSG["en"].get(key, key)).format(**kw) if kw else d.get(key, key)


def _load_models() -> List[Tuple[str, str]]:
    """역할 라벨이 붙은 (label, model) 목록. 카탈로그 > model_roles > 인라인."""
    # MODEL_CATALOG_v1: 카탈로그 설치 세트 우선
    try:
        from launcher import model_catalog as _cat  # type: ignore
        _pairs = _cat.install_pairs()
        if _pairs:
            return _pairs
    except Exception:
        pass
    try:
        from launcher import model_roles as mr  # type: ignore
        pairs: List[Tuple[str, str]] = []
        for r in mr.ROLES:
            pairs.append((r.label, r.model))
            if getattr(r, "fallback", None):
                pairs.append((r.label + " (대체)", r.fallback))
        # 모델 기준 중복 제거 (첫 라벨 유지)
        seen, out = set(), []
        for label, model in pairs:
            if model and model not in seen:
                seen.add(model)
                out.append((label, model))
        return out
    except Exception:
        return list(_INLINE)


def _installed(exe: Path, env: dict) -> set:
    """`ollama list` 파싱 → 설치된 모델 이름 set."""
    try:
        r = subprocess.run([str(exe), "list"], env=env,
                           capture_output=True, text=True, timeout=30)
        names = set()
        for line in (r.stdout or "").splitlines()[1:]:  # 헤더 스킵
            tok = line.split()
            if tok:
                names.add(tok[0])
        return names
    except Exception:
        return set()


def _present(tag: str, installed: set) -> bool:
    if tag in installed:
        return True
    # 태그 없는 베이스가 같고 동일 quant 로 끝나면 동일로 간주 (보수적)
    base = tag.split(":")[0]
    return tag in installed  # PRESENT_FIX_v1 (base-match 분기는 비활성 상태였음 — 현행 동작 보존)


def download(paths: Dict[str, Path]) -> Optional[List[str]]:
    utils.section(_m("section"))
    utils.info(_m("intro"))

    exe = paths["ollama"] / "ollama.exe"
    if not exe.exists():
        utils.warn(_m("no_exe"))
        return None

    env = ollama.env_for(paths)
    models = _load_models()
    installed = _installed(exe, env)
    utils.info(_m("list_head") + (", ".join(sorted(installed)) if installed else "(none)"))

    # MODEL_SELECT_GUI_v1: 설치 전용 선택 GUI (Tk 불가/취소 처리)
    try:
        from launcher import model_catalog as _cat
        _entries = _cat.all_entries()
    except Exception:
        _entries = None
    if _entries:
        try:
            from installer import model_select_gui as _msg_gui
            utils.info("모델 선택 창을 띄웁니다. 창이 안 보이면 작업표시줄/Alt+Tab 에서 '설치할 모델 선택' 창을 확인하세요.")
            _picked = _msg_gui.select_models(_entries, installed, lang=get_language())
        except Exception as _ge:
            utils.warn("선택 GUI 불가 — 권장 세트 자동 설치 (" + repr(_ge) + ")")
            _picked = "AUTO"
        if _picked is None:
            utils.warn("모델 선택 취소 — 나중에 RUN.bat -> [9] 모델 관리 에서 받으세요.")
            return []
        if _picked != "AUTO":
            _desired = set(_picked)
            _role = {e.tag: e.role for e in _entries}
            models = [(_role.get(_t, _t), _t) for _t in sorted(_desired - installed)]
            for _dt in sorted(installed - _desired):
                utils.info("삭제: " + _dt)
                try:
                    subprocess.run([str(exe), "rm", _dt], env=env, check=False)
                except Exception as _de:
                    utils.warn("삭제 실패: " + _dt + " (" + repr(_de) + ")")

    pulled = skipped = failed = 0
    ok_tags: List[str] = []
    for label, tag in models:
        if tag in installed:
            utils.ok(_m("skip", label=label, tag=tag))
            skipped += 1
            ok_tags.append(tag)
            continue
        utils.info(_m("pull", label=label, tag=tag))
        try:
            r = subprocess.run([str(exe), "pull", tag], env=env, check=False)
            if r.returncode == 0:
                utils.ok(_m("done", tag=tag))
                pulled += 1
                ok_tags.append(tag)
            else:
                utils.err(_m("fail", tag=tag, rc=r.returncode))
                failed += 1
        except Exception as e:
            utils.err(_m("fail", tag=tag, rc=repr(e)))
            failed += 1

    utils.info(_m("summary", pulled=pulled, skipped=skipped, failed=failed))
    if failed == 0:
        utils.ok(_m("all_ok"))
    else:
        utils.warn(_m("some_fail"))
    return ok_tags


# 하위호환: 과거 단일 모델 태그를 참조하던 코드가 있을 경우를 위한 표시용 상수
PRIMARY = "qwen2.5-coder:14b"
FALLBACK = "qwen2.5-coder:7b"
