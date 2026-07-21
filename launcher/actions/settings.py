"""actions.settings — [8] 설정 관리 (보기/초기화/언어)."""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import MenuItem, Presenter


def _menu_items() -> list[MenuItem]:
    # LLM_LOG_GUI_TOGGLE_v1: 현재 로그 상태 표시
    try:
        from launcher.agent.agent_runner import logging_enabled as _le
        _log_state = "ON" if _le() else "OFF"
    except Exception:
        _log_state = "?"
    return [
        MenuItem(key="1", title="현재 설정 보기"),
        MenuItem(key="2", title="저장된 워크스페이스 경로 초기화"),
        MenuItem(key="3", title="언어 변경 (English / 한국어)"),
        MenuItem(key="5", title="로그 기록 켜기/끄기 (현재: " + _log_state + ")"),
        MenuItem(key="4", title="설정 전체 초기화"),
        MenuItem(key="b", title="뒤로", separator_above=True),
    ]


def _change_language(p: Presenter) -> None:
    items = [
        MenuItem(key="1", title="English"),
        MenuItem(key="2", title="한국어 (Korean)"),
        MenuItem(key="b", title="뒤로", separator_above=True),
    ]
    choice = p.show_menu("언어 변경", "", items)
    if choice in ("b", "q"):
        return
    new_lang = {"1": "en", "2": "ko"}.get(choice)
    if not new_lang:
        return

    try:
        from ..i18n import set_language
        from .. import settings_store
        set_language(new_lang)
        cfg = settings_store.load()
        settings_store.update_language(cfg, new_lang)
        settings_store.save(cfg)
        label = {"en": "English", "ko": "한국어"}[new_lang]
        p.ok(f"언어 설정 저장: {label}")
    except Exception as e:
        p.error(f"언어 설정 실패: {e}")
    p.pause()


def _toggle_logging(p: Presenter) -> None:
    """LLM_LOG_GUI_TOGGLE_v1: 세션 로그 기록 on/off 토글."""
    try:
        from launcher.agent.agent_runner import logging_enabled
        from launcher.agent.agent_runner import set_logging_enabled
    except Exception as e:
        p.error("로그 토글 불가 — 먼저 PATCH_VERBOSE_LOG 적용 필요: " + str(e))
        p.pause()
        return
    try:
        cur = logging_enabled()
        if set_logging_enabled(not cur):
            p.ok("로그 기록: " + ("ON" if cur else "OFF") + " -> " + ("OFF" if cur else "ON"))
            if cur:
                p.info("세부 입출력이 세션 로그에 더 이상 기록되지 않습니다. 진단 시 다시 켜세요.")
            else:
                p.info("입력/출력/턴 번호가 세션 로그에 기록됩니다 (디버그에 유용).")
        else:
            p.error("로그 설정 저장 실패")
    except Exception as e:
        p.error("로그 토글 실패: " + str(e))
    p.pause()


def run(env: Path, p: Presenter) -> None:
    while True:
        try:
            from .. import settings_store
            cfg = settings_store.load()
            cfg_path = settings_store.path()
        except Exception:
            cfg = None
            cfg_path = env.parent / "launcher" / "settings" / "user_config.json"

        choice = p.show_menu(
            title="설정 관리",
            subtitle=f"파일: {cfg_path}",
            items=_menu_items(),
        )

        if choice in ("b", "q"):
            return

        if choice == "1":
            if cfg_path.exists():
                p.section("현재 설정")
                # SETTINGS_VIEW_v1: GUI 엔 print 가 안 보이므로 p.info 로 표시
                p.info("설정 파일: " + str(cfg_path))
                for _ln in cfg_path.read_text(encoding="utf-8").splitlines():
                    p.info(_ln if _ln.strip() else " ")
            else:
                p.warn("설정 파일이 아직 없습니다 (기본값 사용 중)")
            p.pause()

        elif choice == "2":
            try:
                from .. import settings_store
                if cfg:
                    cfg.last_workspace = None
                    settings_store.save(cfg)
                    p.ok("워크스페이스 경로 초기화 완료")
                else:
                    p.warn("설정 모듈을 불러올 수 없습니다")
            except Exception as e:
                p.error(f"실패: {e}")
            p.pause()

        elif choice == "3":
            _change_language(p)

        elif choice == "4":
            p.warn("모든 설정이 기본값으로 돌아갑니다")
            confirm = p.prompt_text(
                "초기화하려면 정확히 'RESET' 입력: ",
            )
            if confirm == "RESET":
                try:
                    from .. import settings_store
                    settings_store.reset()
                    p.ok("초기화 완료")
                except Exception as e:
                    p.error(f"실패: {e}")
            else:
                p.info("취소")
            p.pause()

        elif choice == "5":
            _toggle_logging(p)
