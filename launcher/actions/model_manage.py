# -*- coding: utf-8 -*-
"""actions.model_manage — [9] 모델 관리 (다운로드/삭제 GUI).

카탈로그(model_catalog)에서 받을 모델을 체크로 고르고,
설치된 모델 중 삭제할 것을 체크로 고른다. TUI/GUI 공통(Presenter API).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import config
from ..presenter.base import MenuItem, Option, Presenter, RISK_MEDIUM
from ..services.ollama import OllamaService

_NO_WINDOW_KW: dict = {}
if os.name == "nt":
    _NO_WINDOW_KW["creationflags"] = getattr(config, "WIN_CREATE_NO_WINDOW", 0x08000000)


def _catalog():
    from .. import model_catalog as cat
    return cat


def _installed_tags(svc) -> set:
    try:
        r = subprocess.run([str(svc.exe), "list"], env=svc.env_vars(),
                           capture_output=True, text=True, timeout=30, **_NO_WINDOW_KW)
        out = set()
        for line in (r.stdout or "").splitlines()[1:]:  # 헤더 스킵
            tok = line.split()
            if tok:
                out.add(tok[0])
        return out
    except Exception:
        return set()


def _download_flow(env, p) -> None:
    cat = _catalog()
    svc = OllamaService(env, logger=p)
    if not svc.is_installed():
        p.error("Ollama 가 설치되어 있지 않습니다. 먼저 INSTALL 을 실행하세요.")
        p.pause()
        return
    if not svc.ensure_running():
        p.pause()
        return

    installed = _installed_tags(svc)
    opts = []
    for e in cat.all_entries():
        done = e.tag in installed
        tail = "  [설치됨]" if done else ""
        grp = "" if e.group == "core" else " (선택)"
        opts.append(Option(
            id=e.tag,
            label=e.tag + "  ·  " + e.role + grp + "  ·  ~" + format(e.size_gb, ".1f") + "GB" + tail,
            default=(done or (e.recommended and not done)),
            description=e.desc,
            locked=done,
        ))
    sel = p.show_checkbox(
        title="모델 다운로드 선택",
        subtitle="체크한 모델을 받습니다 · 이미 설치된 모델은 잠금(설치됨)",
        options=opts,
        extra_lines=[
            "한 번에 하나만 메모리에 적재되므로 RAM 무관, 디스크만 사용합니다.",
            "(선택) 표시는 상위/특수 모델 — 필요할 때만 받으세요.",
        ],
    )
    if sel is None:
        return
    to_pull = [t for t in sel if t not in installed]
    if not to_pull:
        p.info("받을 새 모델이 없습니다.")
        p.pause()
        return

    p.section("모델 다운로드")
    okc = failc = 0
    for tag in to_pull:
        p.info("받는 중: " + tag + "  (수 분 소요, 네트워크 영향)")
        try:
            rc = subprocess.run([str(svc.exe), "pull", tag], env=svc.env_vars(),
                                check=False, **_NO_WINDOW_KW).returncode
        except Exception as ex:
            p.error("  실패: " + tag + " (" + repr(ex) + ")")
            failc += 1
            continue
        if rc == 0:
            p.ok("  완료: " + tag)
            okc += 1
        else:
            p.error("  실패: " + tag + " (rc=" + str(rc) + ")")
            failc += 1
    p.info("요약 — 받음 " + str(okc) + " · 실패 " + str(failc))
    p.pause()


def _remove_flow(env, p) -> None:
    cat = _catalog()
    svc = OllamaService(env, logger=p)
    if not svc.is_installed():
        p.error("Ollama 가 설치되어 있지 않습니다.")
        p.pause()
        return
    if not svc.ensure_running():
        p.pause()
        return

    installed = sorted(_installed_tags(svc))
    if not installed:
        p.info("삭제할 설치된 모델이 없습니다.")
        p.pause()
        return

    ctags = cat.catalog_tags()
    replaced = set(cat.replaced_tags())
    opts = []
    for tag in installed:
        if tag in replaced:
            note = "대체됨 — 삭제 권장"
        elif tag not in ctags:
            note = "카탈로그 외 — 미사용"
        else:
            note = "현재 사용 중"
        opts.append(Option(
            id=tag, label=tag + "  [" + note + "]",
            default=False, risk=RISK_MEDIUM, description=note,
        ))
    sel = p.show_checkbox(
        title="모델 삭제 선택",
        subtitle="체크한 모델을 디스크에서 제거합니다 · 복구하려면 다시 다운로드",
        options=opts,
        extra_lines=[
            "'대체됨'은 새 세트로 교체되어 지워도 안전합니다.",
            "'현재 사용 중'을 지우면 해당 역할이 폴백으로 내려갑니다.",
        ],
    )
    if not sel:
        return
    if not p.confirm_dangerous(
        label="모델 삭제 진행",
        description="선택한 " + str(len(sel)) + "개 모델을 디스크에서 제거합니다.",
        risk=RISK_MEDIUM,
    ):
        p.info("취소했습니다.")
        p.pause()
        return

    p.section("모델 삭제")
    okc = failc = 0
    for tag in sel:
        try:
            rc = subprocess.run([str(svc.exe), "rm", tag], env=svc.env_vars(),
                                check=False, **_NO_WINDOW_KW).returncode
        except Exception as ex:
            p.error("  실패: " + tag + " (" + repr(ex) + ")")
            failc += 1
            continue
        if rc == 0:
            p.ok("  삭제: " + tag)
            okc += 1
        else:
            p.error("  실패: " + tag + " (rc=" + str(rc) + ")")
            failc += 1
    p.info("요약 — 삭제 " + str(okc) + " · 실패 " + str(failc))
    p.pause()


def run(env: Path, p: Presenter) -> None:
    """[9] 모델 관리 — 다운로드/삭제 루프."""
    while True:
        p.section("모델 관리")
        choice = p.show_menu(
            title="모델 관리",
            subtitle="받을 모델을 고르거나, 사용하지 않는 모델을 삭제하세요",
            items=[
                MenuItem(key="1", title="모델 다운로드",
                         description="카탈로그에서 받을 모델 선택 (권장 세트 미리 체크)"),
                MenuItem(key="2", title="모델 삭제",
                         description="설치된 모델 중 제거할 것 선택",
                         badge="주의", badge_kind="warn"),
                MenuItem(key="b", title="뒤로", separator_above=True),
            ],
        )
        if choice in ("b", "q"):
            return
        if choice == "1":
            _download_flow(env, p)
        elif choice == "2":
            _remove_flow(env, p)
