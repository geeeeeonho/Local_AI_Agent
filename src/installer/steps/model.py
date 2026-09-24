"""model — 모델 다운로드 (model_catalog 기반, 멱등).

설치 세트의 정본은 launcher.models.model_catalog.CORE 다.
카탈로그를 못 읽을 때만 model_roles → 인라인 목록 순으로 내려간다.
이미 설치된 모델은 `ollama list` 로 확인해 건너뛴다(멱등 — 재실행 안전).

설치기의 다른 단계와 동일하게 installer.core 콘솔 출력을 쓰고,
인터페이스(download(paths))는 기존과 동일하게 유지해 __main__ 호출부를 보존한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from installer import utils
from installer.steps import ollama
from installer.i18n import get_language

# model_roles 가 없을 때를 대비한 인라인 폴백 (역할 라벨, 모델)
# MODEL_FINAL_v8 inline 폴백 (model_roles import 실패 시)
# model_catalog.CORE 와 같은 세트여야 한다 (test_model_catalog_tiers 가 확인).
_INLINE: List[Tuple[str, str]] = [
    # 상 (14~18GB)
    ("Gemma 정식 26B (사무·범용)", "gemma4:26b"),
    ("에이전트 코딩 특화", "devstral-small-2:24b"),
    ("무검열·범용·에이전트 (Gemma ARA)", "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"),
    ("에이전트·추론 (MoE)", "gpt-oss:20b"),
    # 중 (9GB 급)
    ("코딩 중간", "qwen2.5-coder:14b"),
    ("무검열 중간 (번역 주력)", "huihui_ai/qwen3-abliterated:14b"),
    ("맥락/범용 + Gemma 폴백", "gemma4:12b"),
    # 하 (5GB 급)
    ("최저사양 폴백 (QAT)", "gemma4:e4b-it-qat"),
    ("무검열 경량 폴백", "huihui_ai/qwen3-abliterated:8b"),
    ("코딩 폴백", "qwen2.5-coder:7b"),
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
        "some_fail": "일부 모델을 받지 못했습니다. 네트워크 확인 후 RUN.bat --install 재실행 시 받지 못한 것만 다시 시도합니다.",
        "no_exe": "ollama.exe 를 찾을 수 없어 모델 단계를 건너뜁니다.",
        "mem_fit": "메모리 예산 {budget:.0f}GB 기준 3단계(상/중/하) {n}개(~{gb:.1f}GB):",
        "csv": "파일-모델 대응표: {path}",
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
        "some_fail": "Some models failed. Re-running RUN.bat --install will retry only the missing ones.",
        "no_exe": "ollama.exe not found - skipping model step.",
        "mem_fit": "3 levels, {n} model(s) (~{gb:.1f} GB) for a {budget:.0f} GB memory budget:",
        "csv": "File-to-model map: {path}",
    },
}


def _m(key: str, **kw) -> str:
    d = _MSG.get(get_language(), _MSG["en"])
    return d.get(key, _MSG["en"].get(key, key)).format(**kw) if kw else d.get(key, key)


def _budget_gb() -> Optional[float]:
    """이 PC 가 모델에 내줄 수 있는 최대 메모리.

    ★ '지금 여유' 가 아니다. 브라우저를 켜 둔 채 설치했다는 이유로 상 등급을
      영영 못 받게 되면 안 된다. 실행 시점의 선택만 실제 여유를 본다.
    """
    try:
        from launcher.models import model_catalog as _cat  # type: ignore
        return float(_cat.MEMORY_BUDGET_GB)
    except Exception:
        return None


def _load_models() -> List[Tuple[str, str]]:
    """역할 라벨이 붙은 (label, model) 목록. 카탈로그 > model_roles > 인라인.

    카탈로그가 있으면 메모리 예산 안에서 역할마다 3단계(상/중/하) 기본단계를
    고른다. 예전에는 CORE 를 통째로 받아서, 저사양 PC 도 돌릴 수 없는 모델을
    내려받고 정작 그 PC 의 사다리가 쓰는 단계는 하나도 받지 않았다.
    """
    try:
        from launcher.models import model_catalog as _cat  # type: ignore
        _budget = _budget_gb()
        _plan = _cat.plan_by_level(_budget)
        _wanted = {t for tags in _plan.values() for t in tags}
        if _wanted:
            _role = {e.tag: e.role for e in _cat.all_entries()}
            utils.info(_m("mem_fit", budget=_budget or 0.0, n=len(_wanted),
                          gb=_cat.download_gb(_wanted)))
            for _k in _cat.LEVEL_KEYS:
                _tags = _plan.get(_k) or []
                if _tags:
                    utils.info("    [%s] %.1fGB — %s" % (
                        _cat.level_label(_k), _cat.download_gb(_tags), ", ".join(_tags)))
            return [(_role.get(t, t), t) for t in sorted(_wanted)]
        _pairs = _cat.install_pairs()
        if _pairs:
            return _pairs
    except Exception:
        pass
    try:
        from launcher.models import model_roles as mr  # type: ignore
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
        return _canonical(names)
    except Exception:
        return set()


def _canonical(names: set) -> set:
    """설치 목록을 카탈로그 표기로 맞춘다. 대소문자만 달라도 '미설치'로 보고
    18GB 짜리를 다시 받는 일을 막는다."""
    try:
        from launcher.models import model_catalog as _cat  # type: ignore
        return _cat.canonicalize_installed(names)
    except Exception:
        return set(names)


def download(paths: Dict[str, Path]) -> Optional[List[str]]:
    utils.section(_m("section"))
    utils.info(_m("intro"))

    # Official Ollama is preferred and normally lives outside
    # llm_environment. The portable copy under paths["ollama"] is only a
    # fallback, so asking that directory directly skips model downloads after
    # a perfectly successful official install.
    exe = ollama.find_existing(paths)
    if exe is None:
        utils.warn(_m("no_exe"))
        return None

    env = ollama.env_for(paths)
    models = _load_models()
    installed = _installed(exe, env)
    utils.info(_m("list_head") + (", ".join(sorted(installed)) if installed else "(none)"))

    # MODEL_SELECT_GUI_v1: 설치 전용 선택 GUI (Tk 불가/취소 처리)
    try:
        from launcher.models import model_catalog as _cat
        _entries = _cat.all_entries()
    except Exception:
        _entries = None
    if _entries:
        try:
            from installer.steps import model_select_gui as _msg_gui
            utils.info("모델 선택 창을 띄웁니다. 창이 안 보이면 작업표시줄/Alt+Tab 에서 '설치할 모델 선택' 창을 확인하세요.")
            _picked = _msg_gui.select_models(_entries, installed, lang=get_language(),
                                             budget_gb=_budget_gb())
        except Exception as _ge:
            # Tk 가 없거나 화면이 없는 환경은 예상된 폴백이다. 그 밖의 예외는
            # 코드 결함일 가능성이 높은데, 조용히 넘어가면 선택 창이 영영 안 뜨고
            # 매번 권장 세트(100GB+)가 통째로 받아진다. 실제로 그런 적이 있다.
            _kind = type(_ge).__name__
            if _kind in ("ImportError", "ModuleNotFoundError", "TclError"):
                utils.warn("선택 GUI 사용 불가 — 권장 세트 자동 설치 (" + _kind + ")")
            else:
                utils.err("모델 선택 창 오류 — 권장 세트로 자동 설치합니다: " + repr(_ge))
                utils.err("이 메시지가 보이면 버그입니다. 위 내용을 그대로 알려 주세요.")
            _picked = "AUTO"
        if _picked is None:
            utils.warn("모델 선택 취소 — 나중에 RUN.bat --manage 에서 받으세요.")
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
                utils.warn("[HINT] pull 실패. '412 requires a newer version of Ollama' 라면 Ollama 가 오래된 것입니다. https://ollama.com/download 에서 최신 Ollama 로 업데이트 후 다시 받으세요. (gemma4 계열 등 최신 모델은 새 Ollama 필요)")
                failed += 1
        except Exception as e:
            utils.err(_m("fail", tag=tag, rc=repr(e)))
            failed += 1

    # MODEL_FILES_v1: blobs/sha256-... 가 어느 모델인지 알 수 있게 표를 남긴다.
    try:
        from launcher.models import model_files as _mfiles  # type: ignore
        _csv = _mfiles.refresh(paths["models"])
        if _csv:
            utils.info(_m("csv", path=str(_csv)))
    except Exception:
        pass

    utils.info(_m("summary", pulled=pulled, skipped=skipped, failed=failed))
    if failed == 0:
        utils.ok(_m("all_ok"))
        return ok_tags
    utils.warn(_m("some_fail"))
    # None means the selected model set was not fully prepared. The installer
    # records that as a partial installation instead of claiming models ready
    # because one of several pulls happened to succeed.
    return None
