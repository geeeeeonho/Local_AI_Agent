"""actions.chat — [1] 채팅 UI (Open WebUI + SearXNG).

이전: handlers.start_chat (300+ 라인) → 본 모듈로 분리.
Presenter 인터페이스만 사용 → GUI/TUI 무관.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from .. import config
from ..presenter.base import Presenter
from ..services.ollama import OllamaService


# ─── 디버그 로그 ───
def _log_write(log_path: Path, level: str, msg: str) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] [{level:5}] {msg}\n")
    except OSError:
        pass


def _resolve_webui_argv(env: Path, log_path: Path, p: Presenter):
    """Open WebUI 진입점 결정.

    1순위: Scripts/open-webui.exe (pip 콘솔 스크립트)
    2순위: venv python -m uvicorn open_webui.main:app
    """
    scripts = env / "chat_ui" / "venv" / "Scripts"
    webui_exe = scripts / "open-webui.exe"
    venv_py = scripts / "python.exe"

    if webui_exe.exists():
        _log_write(log_path, "INFO", f"primary: {webui_exe}")
        return [str(webui_exe), "serve"]

    if venv_py.exists():
        _log_write(log_path, "WARN", f"fallback uvicorn: {venv_py}")
        p.warn("open-webui.exe 없음 — uvicorn 직접 호출로 폴백")
        return [
            str(venv_py), "-m", "uvicorn", "open_webui.main:app",
            "--host", "0.0.0.0", "--port", str(config.OPEN_WEBUI_PORT),
        ]

    _log_write(log_path, "FAIL",
               f"no launcher: {webui_exe} / {venv_py}")
    p.error(f"Open WebUI 미설치: {webui_exe}")
    p.warn("install 을 다시 실행하세요")
    return None


def run(env: Path, p: Presenter) -> None:
    """채팅 UI 시작."""
    p.section("Chat UI 시작 (Open WebUI + SearXNG)")

    log_path = env / "logs" / "chat_ui.log"
    _log_write(log_path, "INFO", "=" * 60)
    _log_write(log_path, "INFO", f"Chat UI session start, env={env}")

    # ── Ollama 보장 ──
    ollama_svc = OllamaService(env, logger=p)
    if not ollama_svc.ensure_running():
        _log_write(log_path, "FAIL", "Ollama not available")
        p.info(f"세션 로그: {log_path}")
        p.pause()
        return
    _log_write(log_path, "INFO", "Ollama ready")

    # ── 진입점 결정 ──
    argv = _resolve_webui_argv(env, log_path, p)
    if argv is None:
        p.info(f"세션 로그: {log_path}")
        p.pause()
        return

    # ── SearXNG 자동 시작 (선택) ──
    search_enabled = _try_start_searxng(env, log_path, p)

    # ── 환경변수 구성 ──
    new_env = ollama_svc.env_vars()
    new_env["OLLAMA_BASE_URL"] = config.OLLAMA_URL
    new_env["DEFAULT_MODELS"] = config.MODEL_TAG

    # 런타임 가드 적용 (선택)
    try:
        from .. import runtime_guard  # legacy
        rt = runtime_guard.compute_runtime_params()
        runtime_guard.apply_to_env(rt, new_env)
        _log_write(log_path, "INFO", f"runtime params: {rt}")
    except Exception as e:
        _log_write(log_path, "WARN", f"runtime_guard skip: {e}")

    if search_enabled:
        new_env.update(_search_env_vars())
        p.ok(f"검색 자동 연결: {config.SEARXNG_URL}")

    # ── URL 강조 안내 + 실행 ──
    p.info(f"브라우저: {config.OPEN_WEBUI_URL}")
    if search_enabled:
        p.info("검색 사용: 채팅 입력 옆 + 버튼 → 'Web Search' 토글")
    p.info("종료: Ctrl+C")
    p.info(f"세션 로그: {log_path}")

    _launch_webui(argv, new_env, log_path, p)
    p.pause()


def _try_start_searxng(env: Path, log_path: Path, p: Presenter) -> bool:
    """SearXNG 시작 시도. 실패해도 채팅은 계속."""
    try:
        from .. import searxng_runtime
    except ImportError:
        p.warn("SearXNG 모듈 없음 — 검색 비활성")
        return False

    if not searxng_runtime.image_exists():
        p.warn("SearXNG 미설치 — 검색 비활성")
        p.info("(install 재실행 시 SearXNG 자동 추가)")
        return False

    # Docker 데몬 보장 (이미 살아있으면 즉시 통과)
    from ..services.docker import DockerService
    if not DockerService.daemon_alive():
        p.info("SearXNG 를 위해 Docker 데몬 자동 시작...")
        cancel_check = getattr(p, "is_cancelled", lambda: False)
        if not DockerService.ensure_daemon(
            logger=p, timeout=60, cancel_check=cancel_check,
        ):
            p.warn("Docker 시작 실패 — 검색 없이 채팅만 진행")
            return False

    p.info("SearXNG 검색 엔진 시작 중…")
    if searxng_runtime.start(env, log_path=log_path):
        _log_write(log_path, "INFO", "SearXNG started")
        return True

    _log_write(log_path, "WARN", "SearXNG start failed")
    p.warn("SearXNG 시작 실패 — 검색 없이 진행")
    return False


def _search_env_vars() -> dict:
    return {
        "ENABLE_RAG_WEB_SEARCH": "true",
        "RAG_WEB_SEARCH_ENGINE": "searxng",
        "SEARXNG_QUERY_URL":
            f"{config.SEARXNG_URL}/search?q=<query>&format=json",
        "RAG_WEB_SEARCH_RESULT_COUNT": "5",
        "RAG_WEB_SEARCH_CONCURRENT_REQUESTS": "5",
    }


def _launch_webui(argv, new_env, log_path: Path, p: Presenter) -> None:
    """Open WebUI 실행 + 워치독."""
    proc_holder = {"proc": None}
    kill_timer = {"t": None}

def _wait_for_url(url: str, timeout: int = 30) -> bool:
    """URL 이 응답할 때까지 폴링. timeout 초 내에 200/30x 받으면 True."""
    import time
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def _launch_webui(argv, new_env, log_path: Path, p: Presenter) -> None:
    """Open WebUI 실행.

    GUI 모드: 새 콘솔창에서 실행 + 진입점(브라우저 링크) 버튼 활성화
    TUI 모드: 같은 콘솔에서 동기 실행
    """
    import webbrowser

    _log_write(log_path, "INFO", f"launching: {argv}")

    # GUI (pythonw) 환경 감지
    is_gui_env = (sys.stdout is None or
                  not getattr(sys.stdout, 'isatty', lambda: False)())

    # GUI 모드: 진입점 placeholder 등록 (회색 버튼)
    url = config.OPEN_WEBUI_URL
    if is_gui_env:
        p.reserve_entrypoint(f"브라우저 ({url})")

    kwargs = {"env": new_env}
    if os.name == "nt" and is_gui_env:
        from .. import config as _cfg
        kwargs["creationflags"] = _cfg.WIN_CREATE_NEW_CONSOLE

    try:
        proc = subprocess.Popen(argv, **kwargs)
        _log_write(log_path, "INFO", f"started pid={proc.pid}")

        if is_gui_env:
            p.ok(f"Open WebUI 시작됨 (PID={proc.pid})")
            p.info("Open WebUI 가 응답할 때까지 대기 중...")

            # URL 응답 대기 (백그라운드 스레드 안에서 동기 호출 OK)
            ready = _wait_for_url(url, timeout=30)

            if ready:
                p.ok("Open WebUI 가 응답합니다 — 브라우저를 열 수 있습니다")

                # 진입점 활성화 (파란 버튼)
                def open_browser():
                    try:
                        webbrowser.open(url)
                    except Exception as e:
                        p.warn(f"브라우저 열기 실패: {e}")

                p.enable_entrypoint(
                    callback=open_browser,
                    button_text=f"▶ 브라우저 열기 ({url})",
                )
            else:
                p.warn("Open WebUI 응답 시간 초과 — 수동으로 브라우저에서 접속해보세요")
                # 그래도 버튼은 활성화 (사용자가 직접 시도 가능)
                p.enable_entrypoint(
                    callback=lambda: webbrowser.open(url),
                    button_text=f"▶ 브라우저 열기 ({url})",
                )

            # 외부 프로세스 종료 감지
            p.watch_process(proc)

            p.info(f"세션 로그: {log_path}")
            p.info("외부 콘솔창을 닫으면 Open WebUI 가 종료됩니다.")

        else:
            # 터미널 모드: 동기 대기
            rc = proc.wait()
            _log_write(log_path, "INFO", f"exited rc={rc}")
            if rc != 0:
                p.warn(f"Open WebUI 비정상 종료: 코드={rc}")
                p.info(f"자세한 로그: {log_path}")

    except FileNotFoundError as e:
        _log_write(log_path, "FAIL", f"FileNotFound: {e}")
        p.error(f"실행 파일을 찾을 수 없습니다: {e}")
    except OSError as e:
        _log_write(log_path, "FAIL", f"OSError: {e}")
        p.error(f"OS 오류: {e}")
    except KeyboardInterrupt:
        _log_write(log_path, "INFO", "KeyboardInterrupt")
    except Exception as e:
        _log_write(log_path, "FAIL",
                   f"unexpected {type(e).__name__}: {e}")
        _log_write(log_path, "FAIL", "trace:\n" + traceback.format_exc())
        p.error(f"예상치 못한 오류: {type(e).__name__}: {e}")
