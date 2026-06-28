# -*- coding: utf-8 -*-
"""actions.docker_clean — [10] 도커 정리 (누적 컨테이너/이미지/캐시 청소).

반복 빌드·실행으로 쌓인 것을 체크로 골라 정리하고, 종료 시 자동정리도 토글한다.
"""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import Option, Presenter, RISK_SAFE, RISK_MEDIUM, RISK_HIGH


def _maint():
    from .. import docker_maint as m
    return m


def run(env: Path, p: Presenter) -> None:
    m = _maint()
    p.section("도커 정리")

    if not m.docker_available():
        p.error("Docker 데몬에 연결할 수 없습니다. Docker Desktop 을 켜고 다시 시도하세요.")
        p.pause()
        return

    # 현재 사용량 요약
    p.info("현재 도커 사용량:")
    for line in m.system_df().splitlines():
        p.info("  " + line)

    exited = m.list_our_exited()
    auto_on = m.autoclean_enabled(env)

    opts = [
        Option(id="exited", risk=RISK_SAFE,
               label="중지된 우리 컨테이너 제거 (" + str(len(exited)) + "개)",
               default=bool(exited),
               description="에이전트/검색 실행 후 남은 exited 컨테이너. 안전."),
        Option(id="dangling", risk=RISK_SAFE,
               label="dangling 이미지 제거",
               default=True,
               description="반복 빌드로 생긴 이름 없는 <none> 이미지. 안전."),
        Option(id="cache", risk=RISK_MEDIUM,
               label="빌드 캐시 정리",
               default=False,
               description="docker builder 캐시. 공간 많이 회수하나 다음 빌드가 느려짐."),
        Option(id="images_all", risk=RISK_HIGH,
               label="(위험) 미사용 이미지 전체 제거",
               default=False,
               description="컨테이너가 안 쓰는 모든 이미지 삭제(-a). 다시 받아야 할 수 있음."),
        Option(id="volumes", risk=RISK_HIGH,
               label="(위험) 미사용 볼륨 제거",
               default=False,
               description="미사용 볼륨 삭제. 볼륨에 보관된 데이터가 사라질 수 있음."),
        Option(id="auto", risk=RISK_SAFE,
               label="종료 시 자동 정리 " + ("[현재 켜짐]" if auto_on else "[현재 꺼짐]"),
               default=auto_on,
               description="런처 종료 때마다 안전 정리(exited 컨테이너 + dangling 이미지) 자동 실행."),
    ]
    sel = p.show_checkbox(
        title="도커 정리 선택",
        subtitle="누적된 항목을 골라 정리합니다 · (위험) 항목은 확인을 거칩니다",
        options=opts,
        extra_lines=["종료 시 컨테이너 강제정리·모델 unload 는 이미 자동입니다.",
                     "여기서는 '쌓이는' 이미지/캐시/exited 를 청소합니다."],
    )
    if sel is None:
        return

    # 자동정리 토글 (플래그)
    want_auto = "auto" in sel
    if want_auto != auto_on:
        m.set_autoclean(env, want_auto)
        p.ok("종료 시 자동 정리 " + ("켜짐" if want_auto else "꺼짐"))

    risky = [k for k in ("images_all", "volumes") if k in sel]
    targets = [k for k in ("exited", "dangling", "cache", "images_all", "volumes") if k in sel]
    if not targets:
        p.info("정리할 항목을 선택하지 않았습니다.")
        p.pause()
        return

    if risky:
        if not p.confirm_dangerous(
            label="위험 정리 확인",
            description="선택에 위험 항목(미사용 이미지/볼륨 전체 삭제)이 포함됩니다. 진행할까요?",
            risk=RISK_HIGH,
        ):
            p.info("위험 항목을 건너뜁니다.")
            targets = [t for t in targets if t not in risky]

    p.section("도커 정리 실행")
    if "exited" in targets:
        cnt, logs = m.prune_exited_ours()
        for ln in logs:
            p.info("  " + ln)
        p.ok("중지 컨테이너 제거: " + str(cnt) + "개")
    if "dangling" in targets:
        msg, _ = m.prune_dangling_images()
        p.ok("dangling 이미지: " + msg)
    if "cache" in targets:
        msg, _ = m.prune_build_cache()
        p.ok("빌드 캐시: " + msg)
    if "images_all" in targets:
        msg, _ = m.prune_unused_images()
        p.ok("미사용 이미지: " + msg)
    if "volumes" in targets:
        msg, _ = m.prune_volumes()
        p.ok("미사용 볼륨: " + msg)

    p.info("정리 후 사용량:")
    for line in m.system_df().splitlines():
        p.info("  " + line)
    p.pause()
