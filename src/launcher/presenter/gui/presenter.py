"""presenter — 단일 윈도우 Tk Presenter.

설계 핵심
─────────
Presenter 인터페이스는 동기적이지만, 단일 윈도우 GUI 는 비동기 (사용자가
버튼을 눌러야 응답). 두 패러다임을 잇는 다리는 tk.wait_variable 이다:
  - show_menu / show_checkbox / pause 등은 wait_variable 로 블록
  - 패널 안의 버튼이 var.set(...) 으로 깨움
  - 그 사이에도 메인 윈도우는 살아있고 상태바도 갱신됨

Application 의 메인 루프는 이 클래스가 직접 돌린다 (run_app):
  ┌─ run_app() 시작
  ├─ MainWindow 생성, 사이드바 콜백에 _on_sidebar_select 연결
  ├─ root.mainloop() — 사이드바 클릭이 액션을 실행
  └─ 액션은 Presenter API (show_checkbox 등) 호출 → wait_variable 로 응답 대기
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Dict, List, Optional, Set

from ..base import MenuItem, Option, Presenter
from .dialogs import confirm_dangerous as _confirm_dangerous
from .dialogs import prompt_text as _prompt_text_dialog
from .panels import CheckboxPanel, HomePanel, LogPanel
from .window import MainWindow


class _ActionCancelled(Exception):
    """사용자가 사이드바에서 다른 메뉴 클릭 시 발생.

    액션 함수는 이 예외를 명시적으로 처리할 필요 없음 — 그냥 자연스럽게
    함수가 종료되도록 두면 worker 가 catch 해서 조용히 흘려보냄.
    """
    pass


class TkPresenter(Presenter):
    """단일 윈도우 Tk Presenter.

    중요 동작:
      - section() 은 새 LogPanel 을 띄움 (이후 info/ok/warn/error 가 누적)
      - pause() 는 LogPanel 의 [확인] 버튼 누를 때까지 wait_variable
      - show_menu() 는 사이드바 선택 이벤트와 결합 (Application 레이어에서 사용)
      - show_checkbox() 는 CheckboxPanel 을 메인에 띄우고 결과 대기

    Application.run() 대신 이 클래스의 run_app(items, action_runner) 사용 권장:
      → 사이드바 + 패널 호스트 일체 실행
    """

    def __init__(self):
        self._window: Optional[MainWindow] = None
        self._current_log_panel: Optional[LogPanel] = None
        self._current_log_done: Optional[tk.BooleanVar] = None

        # 액션 취소 메커니즘
        # — 사이드바에서 다른 메뉴 클릭 시 현재 진행 중인 액션을 취소시킴
        import threading
        self._action_cancel = threading.Event()
        # 현재 액션이 wait 중인 BooleanVar 들 — cancel 시 모두 깨움
        self._pending_vars: list = []
        self._pending_lock = threading.Lock()

    def _register_wait(self, var):
        """액션이 wait 중인 변수 등록 — cancel 시 깨우기 위함."""
        with self._pending_lock:
            self._pending_vars.append(var)

    def _unregister_wait(self, var):
        with self._pending_lock:
            try:
                self._pending_vars.remove(var)
            except ValueError:
                pass

    def _cancel_pending_waits(self):
        """모든 대기 중인 변수를 깨움 — 현재 진행 중 액션을 취소."""
        with self._pending_lock:
            vars_copy = list(self._pending_vars)
        for v in vars_copy:
            try:
                # tk.BooleanVar 면 .set, threading.Event 면 .set
                if hasattr(v, "set") and not callable(getattr(v, "set", None)) is False:
                    if isinstance(v, tk.BooleanVar) or isinstance(v, tk.StringVar):
                        # main 스레드에서 set 해야 안전
                        if self._window is not None:
                            try:
                                self._window.root.after(0, lambda var=v: self._safe_set(var))
                            except (tk.TclError, AttributeError):
                                pass
                    else:
                        v.set()
            except Exception:
                pass

    @staticmethod
    def _safe_set(var):
        try:
            if isinstance(var, tk.BooleanVar):
                var.set(True)
            elif isinstance(var, tk.StringVar):
                var.set("__cancelled__")
        except tk.TclError:
            pass

    def is_cancelled(self) -> bool:
        """액션이 외부에서 취소되었는지."""
        return self._action_cancel.is_set()

    # ─────────────────────────────────────────
    #  앱 실행 진입점
    # ─────────────────────────────────────────
    def run_app(
        self,
        items: List[MenuItem],
        action_runner: Callable[[str], None],
        env_path_str: str = "",
        pollers: Optional[Dict[str, Callable]] = None,
        initial_panel: str = "home",
    ):
        """메인 루프 시작.

        Args:
          items:         사이드바에 표시할 메뉴 항목.
          action_runner: 사이드바 선택 시 호출할 함수.
                         action_runner(key) 는 메뉴 키를 받아 액션 실행.
          env_path_str:  사이드바 푸터에 표시할 경로.
          pollers:       상태바 폴러 (ollama_check / docker_check / searxng_check).
          initial_panel: 'home' | <key> 시작 시 보일 패널.
        """
        self._window = MainWindow(
            items=items,
            on_select=lambda key: self._handle_sidebar(key, action_runner),
            env_path_str=env_path_str,
        )
        if pollers:
            self._window.set_pollers(**pollers)

        # 시작 패널
        if initial_panel == "home":
            self._show_home(env_path_str)
        # 종료 단축키 — v6_3_comprehensive: lifelog hook 도 chain
        def _v63_on_close():
            try:
                from launcher.core import lifelog as _ll
                _ll.log("CLEANUP", "GUI WM_DELETE_WINDOW 트리거 (TkPresenter)")
                _ll.shutdown_then_exit()
            except Exception:
                pass
            try:
                self._window.quit()
            except Exception:
                pass
        self._window.root.protocol("WM_DELETE_WINDOW", _v63_on_close)

        self._window.start()

    def _handle_sidebar(self, key: str, action_runner: Callable[[str], None]):
        # v6_4_orphan: 사이드바 클릭 dispatch 추적
        try:
            from launcher.core import lifelog as _ll
            _ll.log("TRACE", "[sidebar] _handle_sidebar 진입 key=" + repr(key))
        except Exception:
            pass
        """사이드바 선택 시 호출.

        진행 중인 액션이 있어도 즉시 취소하고 새 액션 시작.
        — TUI 식 'while True: show_menu' 루프가 사이드바를 막던 문제 해결.
        """
        if key in ("q", "quit", "exit"):
            self._window.quit()
            return

        # 이미 액션 중이면 — 현재 액션을 취소시키고 잠시 대기 후 새 액션 시작
        if getattr(self, "_action_busy", False):
            self._action_cancel.set()
            self._cancel_pending_waits()
            # 짧은 대기 후 새 액션 시작 (worker 가 정리할 시간)
            self._window.root.after(
                150,
                lambda k=key, ar=action_runner: self._start_action(k, ar),
            )
            return

        self._start_action(key, action_runner)

    def _start_action(self, key: str, action_runner: Callable[[str], None]):
        # v6_4_orphan: _start_action 추적
        try:
            from launcher.core import lifelog as _ll
            _ll.log("TRACE", "[sidebar] _start_action 진입 key=" + repr(key))
        except Exception:
            pass
        """새 액션 시작 (이전 액션이 정리된 후 호출)."""
        # 이전 액션이 아직 안 끝났으면 한번 더 대기
        if getattr(self, "_action_busy", False):
            self._window.root.after(
                100,
                lambda: self._start_action(key, action_runner),
            )
            return

        # 취소 플래그 리셋
        self._action_cancel.clear()

        self._window.sidebar.set_selected(key)
        self._window.sidebar.set_disabled(False)  # GUI 모드에선 항상 활성화
        self._action_busy = True

        import threading

        def worker():
            # v6_4_orphan: worker 진입 trace
            try:
                from launcher.core import lifelog as _ll_w
                _ll_w.log("TRACE", "[sidebar] worker 시작 key=" + repr(key))
            except Exception:
                pass
            try:
                try:
                    from launcher.core import lifelog as _ll_w2
                    _ll_w2.log("TRACE", "[sidebar] action_runner 호출 직전 key=" + repr(key))
                except Exception:
                    pass
                action_runner(key)
                try:
                    from launcher.core import lifelog as _ll_w3
                    _ll_w3.log("TRACE", "[sidebar] action_runner 정상 반환 key=" + repr(key))
                except Exception:
                    pass
            except _ActionCancelled:
                # 정상 취소 — 무시
                pass
            except Exception as e:
                if self._action_cancel.is_set():
                    # 취소 중 발생한 예외는 무시
                    pass
                else:
                    import traceback
                    self.error(f"액션 실행 오류: {type(e).__name__}: {e}")
                    self.error(traceback.format_exc())
                    try:
                        self.pause()
                    except _ActionCancelled:
                        pass
            finally:
                self._action_busy = False
                # 정리: 사이드바 selection 해제 (취소된 경우만 — 정상 종료 시 다음 액션이 처리)
                if not self._action_cancel.is_set():
                    def _post_action():
                        try:
                            self._window.sidebar.set_selected(None)
                        except Exception:
                            pass
                    try:
                        self._window.root.after(0, _post_action)
                    except Exception:
                        pass

        t = threading.Thread(target=worker, daemon=True, name=f"action-{key}")
        t.start()

    def _show_home(self, env_path_str: str):
        self._window.host.replace(
            lambda parent: HomePanel(parent, env_path_str)
        )

    # ─────────────────────────────────────────
    #  Thread-safe 마샬링
    # ─────────────────────────────────────────
    def _ui_call(self, fn):
        """현재 스레드에 따라 fn() 을 안전하게 호출.

        메인 스레드면 즉시, 아니면 root.after(0, fn) 로 마샬링.
        Tk 위젯은 메인 스레드에서만 만져야 하기 때문.
        """
        import threading
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            try:
                self._window.root.after(0, fn)
            except (tk.TclError, AttributeError):
                pass

    # ─────────────────────────────────────────
    #  Presenter 인터페이스 — 정보 출력
    # ─────────────────────────────────────────
    def info(self, msg: str) -> None:
        def _do():
            self._ensure_log("결과")
            self._current_log_panel.append("info", msg)
            self._window.set_message(msg, "info")
        self._ui_call(_do)

    def ok(self, msg: str) -> None:
        def _do():
            self._ensure_log("결과")
            self._current_log_panel.append("ok", msg)
            self._window.set_message(msg, "ok")
        self._ui_call(_do)

    def warn(self, msg: str) -> None:
        def _do():
            self._ensure_log("결과")
            self._current_log_panel.append("warn", msg)
            self._window.set_message(msg, "warn")
        self._ui_call(_do)

    def error(self, msg: str) -> None:
        def _do():
            self._ensure_log("결과")
            self._current_log_panel.append("error", msg)
            self._window.set_message(msg, "error")
        self._ui_call(_do)

    def section(self, title: str, subtitle: str = "") -> None:
        """새 로그 패널을 시작 — 스피너가 자동으로 돌기 시작.

        취소 버튼이 자동으로 활성화됨 (사용자가 누르면 _ActionCancelled).
        """
        def _do():
            self._current_log_done = tk.BooleanVar(value=False)
            done_var = self._current_log_done
            panel = self._window.host.replace(
                lambda parent: LogPanel(
                    parent, title=title, subtitle=subtitle,
                    on_done=lambda: done_var.set(True),
                )
            )
            self._current_log_panel = panel
            # 취소 버튼 활성화 — 누르면 진행 중 액션을 취소
            panel.set_cancel_callback(self._on_user_cancel)
        self._ui_call(_do)

    def _on_user_cancel(self):
        """사용자가 [취소] 버튼 누름 — 사이드바에서 다른 항목 클릭한 것과 동일 효과."""
        if self._action_cancel.is_set():
            return  # 이미 취소 중
        self._action_cancel.set()
        self._cancel_pending_waits()
        # 시각적 피드백
        try:
            if self._current_log_panel is not None:
                self._current_log_panel.append("warn", "사용자가 취소함")
                self._current_log_panel.set_cancel_callback(None)  # 더 못 누르게
        except Exception:
            pass

    def pause(self, msg: str = "") -> None:
        """[확인] 버튼이 눌릴 때까지 대기.

        취소 시 _ActionCancelled 예외 발생.
        """
        import threading

        # 취소 사전 체크
        if self._action_cancel.is_set():
            raise _ActionCancelled()

        def _setup():
            if self._current_log_panel is None:
                self._current_log_done = tk.BooleanVar(value=False)
                done_var = self._current_log_done
                self._current_log_panel = self._window.host.replace(
                    lambda parent: LogPanel(
                        parent, title="결과", subtitle="",
                        on_done=lambda: done_var.set(True),
                    )
                )
            if msg:
                self._current_log_panel.append("info", msg)
            self._current_log_panel.mark_done()
            # 대기 변수 등록 (취소 시 깨우기 위함)
            if self._current_log_done is not None:
                self._register_wait(self._current_log_done)

        if threading.current_thread() is threading.main_thread():
            _setup()
            if self._current_log_done is not None:
                try:
                    self._window.root.wait_variable(self._current_log_done)
                finally:
                    self._unregister_wait(self._current_log_done)
        else:
            done_event = threading.Event()
            done_var_holder = {"var": None}

            def _setup_and_track():
                _setup()
                done_var_holder["var"] = self._current_log_done
                if self._current_log_done is not None:
                    self._current_log_done.trace_add(
                        "write",
                        lambda *_a: done_event.set()
                    )

            self._window.root.after(0, _setup_and_track)
            done_event.wait()
            if done_var_holder["var"] is not None:
                self._unregister_wait(done_var_holder["var"])

        # 정리 — 동기적으로
        cleanup_done = threading.Event()

        def _cleanup():
            self._current_log_panel = None
            self._current_log_done = None
            cleanup_done.set()

        if threading.current_thread() is threading.main_thread():
            _cleanup()
        else:
            self._window.root.after(0, _cleanup)
            cleanup_done.wait(timeout=2.0)

        # 취소 사후 체크
        if self._action_cancel.is_set():
            raise _ActionCancelled()

    # ─────────────────────────────────────────
    #  Presenter 인터페이스 — 입력
    # ─────────────────────────────────────────
    def prompt_text(self, prompt: str = "> ", default: str = "") -> str:
        """자유 텍스트 입력. 백그라운드 스레드에서 호출 가능."""
        import threading

        if threading.current_thread() is threading.main_thread():
            result = _prompt_text_dialog(self._window.root, prompt, default)
            return (result or "").strip()

        # 백그라운드: 메인 스레드에서 다이얼로그 띄우고 결과 동기 대기
        done = threading.Event()
        result_holder = {"value": ""}

        def _do():
            r = _prompt_text_dialog(self._window.root, prompt, default)
            result_holder["value"] = (r or "").strip()
            done.set()

        self._window.root.after(0, _do)
        done.wait()
        return result_holder["value"]

    def prompt_choice(self, prompt: str, choices: List[str]) -> Optional[str]:
        items = [MenuItem(key=c, title=c) for c in choices]
        choice = self.show_menu(prompt, "", items)
        return choice if choice not in (None, "q") else None

    def prompt_path(
        self, title: str, default: Path,
        last_used: Optional[Path] = None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        import threading

        def _do_dialog():
            initial = str(last_used or default)
            return filedialog.askdirectory(
                title=title,
                initialdir=initial,
                mustexist=must_exist,
                parent=self._window.root,
            )

        if threading.current_thread() is threading.main_thread():
            path_str = _do_dialog()
        else:
            done = threading.Event()
            holder = {"path": ""}

            def _do():
                holder["path"] = _do_dialog()
                done.set()
            self._window.root.after(0, _do)
            done.wait()
            path_str = holder["path"]

        if not path_str:
            return None
        return Path(path_str)

    # ─────────────────────────────────────────
    #  Presenter 인터페이스 — 메뉴 / 체크박스
    # ─────────────────────────────────────────
    def show_menu(
        self, title: str, subtitle: str,
        items: List[MenuItem],
        last_choice: Optional[str] = None,
    ) -> str:
        """메인 루프 외부에서 호출되는 하위 메뉴 (액션 내부).

        백그라운드 스레드에서 호출 가능 — 메인 스레드에 마샬링.
        사이드바 클릭으로 취소되면 _ActionCancelled 예외 발생.
        """
        import threading
        from .menu_panel import MenuPanel

        # 취소 사전 체크
        if self._action_cancel.is_set():
            raise _ActionCancelled()

        result_holder = {"value": "q"}
        done_event = threading.Event()

        def _setup():
            result_var = tk.StringVar(value="")
            self._window.host.replace(
                lambda parent: MenuPanel(
                    parent, title=title, subtitle=subtitle,
                    items=items, last_choice=last_choice,
                    on_select=lambda k: result_var.set(k),
                )
            )
            self._register_wait(result_var)

            def _on_set(*_a):
                result_holder["value"] = result_var.get() or "q"
                done_event.set()
            result_var.trace_add("write", _on_set)

        if threading.current_thread() is threading.main_thread():
            result_var = tk.StringVar(value="")
            self._window.host.replace(
                lambda parent: MenuPanel(
                    parent, title=title, subtitle=subtitle,
                    items=items, last_choice=last_choice,
                    on_select=lambda k: result_var.set(k),
                )
            )
            self._register_wait(result_var)
            try:
                self._window.root.wait_variable(result_var)
            finally:
                self._unregister_wait(result_var)

            if self._action_cancel.is_set():
                raise _ActionCancelled()
            value = result_var.get()
            if value == "__cancelled__":
                raise _ActionCancelled()
            return value or "q"
        else:
            self._window.root.after(0, _setup)
            done_event.wait()
            # 정리
            try:
                self._window.root.after(0, lambda: None)  # 메인 스레드 깨우기
            except Exception:
                pass
            if self._action_cancel.is_set():
                raise _ActionCancelled()
            value = result_holder["value"]
            if value == "__cancelled__":
                raise _ActionCancelled()
            return value

    def show_checkbox(
        self, title: str, subtitle: str,
        options: List[Option],
        extra_lines: Optional[List[str]] = None,
        override_defaults: Optional[Set[str]] = None,
    ) -> Optional[Set[str]]:
        if not options:
            return set()
        if self._action_cancel.is_set():
            raise _ActionCancelled()

        import threading

        result_holder = {"value": None}
        done_event = threading.Event()
        ready_var_holder: dict = {"var": None}

        def _setup():
            ready_var = tk.BooleanVar(value=False)
            ready_var_holder["var"] = ready_var
            self._register_wait(ready_var)

            def on_done(selected):
                result_holder["value"] = selected
                ready_var.set(True)
                done_event.set()

            self._window.host.replace(
                lambda parent: CheckboxPanel(
                    parent, title=title, subtitle=subtitle,
                    options=options, extra_lines=extra_lines,
                    override_defaults=override_defaults,
                    on_done=on_done,
                    parent_window=self._window.root,
                )
            )
            # cancel 시에도 깨우기 위해 ready_var 의 trace 등록
            def _on_set(*_a):
                done_event.set()
            ready_var.trace_add("write", _on_set)

        if threading.current_thread() is threading.main_thread():
            ready_var = tk.BooleanVar(value=False)
            self._register_wait(ready_var)

            def on_done(selected):
                result_holder["value"] = selected
                ready_var.set(True)

            self._window.host.replace(
                lambda parent: CheckboxPanel(
                    parent, title=title, subtitle=subtitle,
                    options=options, extra_lines=extra_lines,
                    override_defaults=override_defaults,
                    on_done=on_done,
                    parent_window=self._window.root,
                )
            )
            try:
                self._window.root.wait_variable(ready_var)
            finally:
                self._unregister_wait(ready_var)
            if self._action_cancel.is_set():
                raise _ActionCancelled()
            return result_holder["value"]
        else:
            self._window.root.after(0, _setup)
            done_event.wait()
            if ready_var_holder["var"] is not None:
                self._unregister_wait(ready_var_holder["var"])
            if self._action_cancel.is_set():
                raise _ActionCancelled()
            return result_holder["value"]

    def confirm_dangerous(
        self, label: str, description: str, risk: int,
    ) -> bool:
        import threading

        if threading.current_thread() is threading.main_thread():
            return _confirm_dangerous(
                self._window.root, label, description, risk,
            )

        # 백그라운드: 메인 스레드에서 다이얼로그
        done = threading.Event()
        holder = {"ok": False}

        def _do():
            holder["ok"] = _confirm_dangerous(
                self._window.root, label, description, risk,
            )
            done.set()

        self._window.root.after(0, _do)
        done.wait()
        return holder["ok"]

    # ─────────────────────────────────────────
    #  진입점 (entrypoint) API
    # ─────────────────────────────────────────
    def reserve_entrypoint(self, label: str) -> None:
        """액션 시작 시 호출 — 회색 placeholder 버튼 만들기.

        예: p.reserve_entrypoint("브라우저 (http://localhost:8080)")
        → 화면에 "⏳ 브라우저 (...) (준비 중...)" 회색 버튼 표시
        """
        def _do():
            self._ensure_log("결과")
            if self._current_log_panel is not None:
                self._current_log_panel.reserve_entrypoint(label)
        self._ui_call(_do)

    def enable_entrypoint(
        self, callback: Callable, button_text: Optional[str] = None,
    ) -> None:
        """진입점 활성화 — 버튼이 파란색으로 변하고 클릭 가능."""
        def _do():
            if self._current_log_panel is not None:
                self._current_log_panel.enable_entrypoint(callback, button_text)
        self._ui_call(_do)

    def watch_process(
        self, proc, on_terminated: Optional[Callable] = None,
        restart_callback: Optional[Callable] = None,
    ) -> None:
        """외부 프로세스 종료를 백그라운드에서 감지.

        proc: subprocess.Popen 객체
        on_terminated: 종료 시 호출 (옵션)
        restart_callback: 재시작 콜백 — 주어지면 진입점 버튼이 '다시 시작' 으로 변함
        """
        import threading

        # 현재 패널 캡처 (나중에 다른 패널로 바뀌어도 이 패널에 알림)
        target_panel = self._current_log_panel

        def watcher():
            try:
                proc.wait()
            except Exception:
                pass
            # 메인 스레드에 알림
            def _notify():
                if on_terminated:
                    try:
                        on_terminated()
                    except Exception:
                        pass
                if target_panel is not None:
                    try:
                        target_panel.mark_entrypoint_terminated(
                            restart_callback=restart_callback,
                        )
                        target_panel.append(
                            "warn",
                            f"외부 프로세스 종료됨 (PID 였음)",
                        )
                    except Exception:
                        pass
            try:
                self._window.root.after(0, _notify)
            except (tk.TclError, AttributeError):
                pass

        t = threading.Thread(target=watcher, daemon=True, name="proc-watcher")
        t.start()

    # ─────────────────────────────────────────
    #  내부
    # ─────────────────────────────────────────
    def _ensure_log(self, default_title: str = "결과"):
        """로그 패널이 없으면 새로 만든다."""
        if self._current_log_panel is None:
            self.section(default_title)
