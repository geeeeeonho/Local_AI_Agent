# -*- coding: utf-8 -*-
"""model_classes — 모델 클래스별 '티어 폴백' 뷰 (단일 진실원). MODEL_CLASSES_v2.

model_roles.TIERS(역할 -> 티어[기본+대안]) + model_catalog(크기/설명) + 현재 여유 메모리로,
클래스마다 티어를 1 / 1-1 / 1-2 / 2 / 2-1 ... 로 번호 매겨 폴백 순서를 보여준다.
TIERS 가 없으면 LADDERS 를 need 로 그룹핑해 티어를 만든다(하위호환).

순수 로직(헤드리스). tkinter 등 UI 의존 없음.
"""
from __future__ import annotations

from typing import List, Optional

# 상위->하위 클래스 (요청 순서)
CLASSES = [
    ("coding", "일반 코딩", "코드 작성·실행·파일 작업"),
    ("uncensored", "무검열", "검열 없는 검색·번역·범용"),
    ("agent", "관리 특화 (에이전트·다중폴더)", "도구 호출·자율 실행·폴더 정책"),
    ("balanced", "범용 / 타협 (특화 없는 올라운더)", "코딩·대화·추론 균형, 안전 학습 유지"),
]


def _model_roles():
    try:
        from . import model_roles as mr
        return mr
    except Exception:
        pass
    try:
        from launcher.models import model_roles as mr
        return mr
    except Exception:
        pass
    from launcher import model_roles as mr
    return mr


def _catalog_by_tag():
    mc = None
    try:
        from . import model_catalog as mc  # noqa
    except Exception:
        try:
            from launcher.models import model_catalog as mc  # noqa
        except Exception:
            try:
                from launcher import model_catalog as mc  # noqa
            except Exception:
                mc = None
    if mc is None:
        return {}
    try:
        return {e.tag: e for e in mc.all_entries()}
    except Exception:
        return {}


def _tiers_for(mr, key):
    """[(primary, need, [alts...]), ...]. TIERS 우선, 없으면 LADDERS 를 need 로 그룹핑."""
    tiers = getattr(mr, "TIERS", None)
    if tiers and key in tiers:
        return [(t["primary"], float(t["need"]), list(t.get("alts", [])))
                for t in tiers[key]]
    lad = (getattr(mr, "LADDERS", {}) or {}).get(key) or []
    out = []
    idx_by_need = {}
    for m, need in lad:
        need = float(need)
        if need in idx_by_need:
            out[idx_by_need[need]][2].append(m)
        else:
            idx_by_need[need] = len(out)
            out.append((m, need, []))
    return out


def build_view(free_gb: Optional[float] = None, installed=None) -> List[dict]:
    mr = _model_roles()
    cat = _catalog_by_tag()

    if free_gb is None:
        try:
            free_gb = mr.detect_free_memory_gb()
        except Exception:
            free_gb = None
    installed_known = installed is not None
    if installed is None:
        try:
            installed = mr.installed_models()
            installed_known = installed is not None
        except Exception:
            installed, installed_known = None, False
    inst = set(installed) if installed else set()

    safety = float(getattr(mr, "_SAFETY", 0.92))
    usable = (float(free_gb) * safety) if free_gb else 0.0

    view = []
    for key, title, desc in CLASSES:
        tiers = _tiers_for(mr, key)

        # 추천 티어 = need <= usable 인 첫 티어(없으면 마지막)
        rec_t = None
        for ti, (_p, need, _a) in enumerate(tiers):
            if usable and need <= usable:
                rec_t = ti
                break
        if rec_t is None and tiers:
            rec_t = len(tiers) - 1

        # 순서대로 후보 나열 (티어별 [기본]+대안)
        ordered = []
        for ti, (p, need, alts) in enumerate(tiers):
            for si, tag in enumerate([p] + alts):
                ordered.append((ti, si, tag, need))
        # 실제 사용 후보 = 조건 맞으면서 설치된 첫 후보 (없으면 설치된 첫 후보)
        act = None
        if installed_known:
            for ti, si, tag, need in ordered:
                if usable and need <= usable and tag in inst:
                    act = (ti, si)
                    break
            if act is None:
                for ti, si, tag, need in ordered:
                    if tag in inst:
                        act = (ti, si)
                        break

        rungs = []
        for ti, (p, need, alts) in enumerate(tiers):
            for si, tag in enumerate([p] + alts):
                e = cat.get(tag)
                label = ("%d" % (ti + 1)) if si == 0 else ("%d-%d" % (ti + 1, si))
                rungs.append({
                    "label": label, "tier": ti + 1, "sub": si, "is_primary": si == 0,
                    "tag": tag, "size_gb": getattr(e, "size_gb", None), "need_gb": need,
                    "desc": getattr(e, "desc", "") or "",
                    "installed": (tag in inst) if installed_known else None,
                    "fits": bool(usable and need <= usable),
                    "recommended": (ti == rec_t and si == 0),
                    "actual": (act == (ti, si)),
                })
        view.append({
            "key": key, "title": title, "desc": desc, "rungs": rungs,
            "free_gb": free_gb, "usable_gb": usable, "installed_known": installed_known,
        })
    return view


def format_text(view: Optional[List[dict]] = None, free_gb: Optional[float] = None,
                width: int = 40) -> str:
    if view is None:
        view = build_view(free_gb=free_gb)
    lines = []
    fg = view[0]["free_gb"] if view else free_gb
    if fg:
        lines.append("현재 여유 메모리 %.1fGB 기준 (숫자=티어, 1-1/1-2=같은 티어 대안)" % fg)
    else:
        lines.append("여유 메모리 감지 실패 — 아래는 티어 구조만")
    for c in view:
        lines.append("")
        lines.append("[%s] %s" % (c["title"], c["desc"]))
        if not c["rungs"]:
            lines.append("  (사다리 없음)")
            continue
        for r in c["rungs"]:
            size = ("%.1fGB" % r["size_gb"]) if r["size_gb"] else "  ? "
            if r["installed"] is None:
                badge = "설치?"
            else:
                badge = "설치됨" if r["installed"] else "미설치"
            mark = ""
            if not r["is_primary"]:
                mark += "  · 대안"
            if r["recommended"]:
                mark += "  ★추천(현재)"
            if r["actual"] and not r["recommended"]:
                mark += "  <=실제 사용"
            lines.append("  %-4s %-*s %7s  여유>=%.0fGB  [%s]%s"
                         % (r["label"], width, r["tag"], size, r["need_gb"], badge, mark))
        if c["installed_known"]:
            miss = [r["label"] for r in c["rungs"]
                    if r["installed"] is False and r["is_primary"]]
            if miss:
                lines.append("     -> 미설치 기본단계 %s 는 대안/하위로 폴백"
                             % ",".join(miss))
            else:
                lines.append("     -> 메모리 부족 시 티어 1->2->3 순 자동 폴백")
        else:
            lines.append("     -> 메모리 부족 시 티어 1->2->3 순 자동 폴백")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_text())
