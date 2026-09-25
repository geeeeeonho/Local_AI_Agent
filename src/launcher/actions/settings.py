"""actions.settings — [8] 설정 관리 (보기/초기화/언어)."""
from __future__ import annotations

from pathlib import Path

from ..presenter.base import MenuItem, Presenter


def _menu_items() -> list[MenuItem]:
    try:
        from .. import settings_store
        _log_state = "ON" if settings_store.logging_enabled() else "OFF"
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
        from installer.i18n import set_language
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
    """세션 상세 로그 기록 on/off 토글."""
    try:
        from .. import settings_store
    except Exception as e:
        p.error("로그 설정 모듈을 불러올 수 없습니다: " + str(e))
        p.pause()
        return
    try:
        cur = settings_store.logging_enabled()
        if settings_store.set_logging_enabled(not cur):
            p.ok("로그 기록: " + ("ON" if cur else "OFF") + " -> " + ("OFF" if cur else "ON"))
            if cur:
                p.info("세부 입출력이 세션 로그에 더 이상 기록되지 않습니다. 진단 시 다시 켜세요.")
                p.info("다음 에이전트 세션부터 적용됩니다 (실행 중인 세션은 그대로).")
            else:
                p.info("입력/출력/도구 호출이 세션 로그에 기록됩니다 (디버그에 유용).")
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
            try:
                from launcher.core import user_data
                cfg_path = user_data.settings_dir() / "user_config.json"
            except Exception:
                import project_paths
                cfg_path = (project_paths.user_data_dir()
                            / "settings" / "user_config.json")

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
