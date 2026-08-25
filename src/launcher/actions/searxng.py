"""actions.searxng — [7] SearXNG 검색 엔진 제어."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from .. import config
from ..presenter.base import MenuItem, Presenter
from ..services.docker import DockerService


def _build_menu_items(running: bool) -> list[MenuItem]:
    items = []
    if running:
        items.append(MenuItem(
            key="1", title="정지",
            description=f"실행 중: {config.SEARXNG_URL}",
        ))
        items.append(MenuItem(
            key="2", title="브라우저에서 열기",
        ))
    else:
        items.append(MenuItem(
            key="1", title="시작",
        ))
    items.append(MenuItem(
        key="3", title="컨테이너 삭제 + 재생성",
        separator_above=True,
    ))
    items.append(MenuItem(
        key="4", title="settings.yml 위치 표시",
    ))
    items.append(MenuItem(
        key="5", title="컨테이너 로그 보기 (마지막 50줄)",
    ))
    items.append(MenuItem(
        key="b", title="뒤로", separator_above=True,
    ))
    return items


def run(env: Path, p: Presenter) -> None:
    """SearXNG 제어 메뉴 (루프)."""
    try:
        from .. import searxng_runtime
    except ImportError:
        p.error("searxng_runtime 모듈 없음")
        p.pause()
        return

    while True:
        if not searxng_runtime.image_exists():
            p.section("SearXNG 검색 엔진")
            p.error("이미지 미설치")
            p.warn("install 을 다시 실행하면 SearXNG 가 자동 추가됩니다")
            p.pause()
            return

        running = searxng_runtime.is_running()
        status_label = (
            f"실행 중: {config.SEARXNG_URL}" if running else "정지됨"
        )
        cfg_path = env / "searxng" / "config" / "settings.yml"
        subtitle = (
            f"상태: {status_label}\n"
            f"설정: {cfg_path}\n"
            f"포트: {config.SEARXNG_HOST_PORT}"
        )

        choice = p.show_menu(
            title="SearXNG 검색 엔진 제어",
            subtitle=subtitle,
            items=_build_menu_items(running),
        )

        if choice in ("b", "q"):
            return

        if choice == "1":
            if running:
                searxng_runtime.stop()
                p.ok("정지됨")
            else:
                # Docker 자동 시작 (취소 가능)
                cancel_check = getattr(p, "is_cancelled", lambda: False)
                if not DockerService.ensure_daemon(
                    logger=p, timeout=60, cancel_check=cancel_check,
                ):
                    p.pause()
                    continue

                p.reserve_entrypoint(f"브라우저 ({config.SEARXNG_URL})")
                if searxng_runtime.start(env):
                    p.ok(f"시작됨: {config.SEARXNG_URL}")
                    p.enable_entrypoint(
                        callback=lambda: webbrowser.open(config.SEARXNG_URL),
                        button_text=f"▶ 브라우저 열기 ({config.SEARXNG_URL})",
                    )
                else:
                    p.error("시작 실패")
            p.pause()

        elif choice == "2" and running:
            webbrowser.open(config.SEARXNG_URL)

        elif choice == "3":
            searxng_runtime.remove()
            p.info("재생성 중…")
            if searxng_runtime.start(env):
                p.ok("재생성 완료")
            p.pause()

        elif choice == "4":
            p.info(f"설정 파일: {cfg_path}")
            p.info("주요 키:")
            p.info("  - safe_search: 0 (필터 없음)")
            p.info("  - engines: google/bing/duckduckgo/brave")
            p.warn("수정 후엔 [3] 재생성 메뉴로 컨테이너를 다시 만드세요")
            p.pause()

        elif choice == "5":
            if not searxng_runtime.container_exists():
                p.warn("컨테이너가 아직 생성되지 않았습니다")
                p.pause()
                continue
            logs = DockerService.container_logs(
                config.SEARXNG_CONTAINER, tail=50,
            )
            p.section("SearXNG 컨테이너 로그 (마지막 50줄)")
            print(logs)
            p.pause()
