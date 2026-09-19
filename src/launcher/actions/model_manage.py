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
    from launcher.models import model_catalog as cat
    return cat


def _installed_tags(svc) -> set:
    """설치된 태그. 모델 확인 정본 하나만 거친다.

    예전에는 `ollama list` 를 프로세스로 띄워 열 맞춘 stdout 을 잘랐다.
    같은 답을 HTTP 로 얻을 수 있는데 프로세스를 하나 더 띄웠고, 출력
    형식이 바뀌면 조용히 빈 집합이 되었다. 서버가 꺼져 있으면 저장소가
    답하므로 이제는 그 경우에도 빈 집합이 아니다.
    """
    try:
        from integrations.ollama import inventory
        found = inventory.read(getattr(svc, "model_dir", None))
        return set(found.tags) if found.known else set()
    except Exception:
        return set()


def _budget_gb():
    """모델에 내줄 수 있는 최대 메모리. '지금 여유' 가 아니라 이 PC 의 상한."""
    try:
        from launcher.models import model_catalog as cat
        return float(cat.MEMORY_BUDGET_GB)
    except Exception:
        return None


def _refresh_file_map(svc, p) -> None:
    """MODEL_FILES_v1: blobs/sha256-... 가 어느 모델인지 적은 CSV 를 다시 쓴다."""
    try:
        from launcher.models import model_files as mf
    except Exception:
        return
    out = mf.refresh(svc.model_dir)
    if out:
        p.info("파일-모델 대응표 갱신: " + str(out))
    else:
        p.warn("파일-모델 대응표를 쓰지 못했습니다 (저장소 쓰기 권한 확인).")


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
    budget_gb = _budget_gb()
    wanted = cat.recommended_for(budget_gb)
    plan = cat.plan_by_level(budget_gb)
    opts = []
    for e in cat.all_entries():
        done = e.tag in installed
        tail = "  [설치됨]" if done else ""
        lvl = cat.level_of(e.tag)
        grp = ("  [%s]" % cat.level_label(lvl)) if lvl else ""
        grp += "" if e.group == "core" else " (선택)"
        # 다운로드 크기와 상주 메모리는 다르다 (gemma4:e4b 는 9.6GB 받아 ~5GB 로 돈다).
        sizes = "~" + format(e.size_gb, ".1f") + "GB 받기"
        if abs(e.memory_gb - e.size_gb) >= 0.2:
            sizes += " / " + format(e.memory_gb, ".1f") + "GB 적재"
        note = ("  ·  " + e.note) if e.note else ""
        opts.append(Option(
            id=e.tag,
            label=e.tag + "  ·  " + e.role + grp + note + "  ·  " + sizes + tail,
            default=(done or e.tag in wanted),
            description=e.desc,
            locked=done,
        ))
    lines = ["메모리 예산 %.0fGB 기준 3단계를 미리 체크했습니다 "
             "(여유는 오르내리므로 세 단계를 모두 둡니다)." % (budget_gb or 0)]
    for key in cat.LEVEL_KEYS:
        tags = plan.get(key) or []
        if tags:
            lines.append("  [%s] %.1fGB — %s"
                         % (cat.level_label(key), cat.download_gb(tags), ", ".join(tags)))
    lines.append("한 번에 하나만 메모리에 적재되므로 RAM 무관, 디스크만 사용합니다.")
    lines.append("(선택) 표시는 같은 등급의 대안 — 필요할 때만 받으세요.")
    sel = p.show_checkbox(
        title="모델 다운로드 선택",
        subtitle="체크한 모델을 받습니다 · 이미 설치된 모델은 잠금(설치됨)",
        options=opts,
        extra_lines=lines,
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
    _refresh_file_map(svc, p)
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
    _refresh_file_map(svc, p)
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
