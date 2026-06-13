"""lifelog — 통합 로그 시스템 + 모든 종료 경로 hook (v6_1_hotfix).

v6.1 변경:
  - 각 hook 설치 단계마다 로그 -> 실패 시 정확한 위치 식별
  - pythonw.exe 환경 자동 감지 -> SetConsoleCtrlHandler skip
  - signal.signal 메인 스레드 강제 검증
  - fatal traceback 을 logs/lifelog_fatal.log 에 별도 기록
  - ctypes 호출 격리 (콜백 등록 자체 segfault 위험)

핵심 책임
─────────
1. 프로젝트 루트의 logs/ 폴더에 세션 로그 기록
2. 매 줄마다 flush + os.fsync
3. 모든 종료 경로에서 호출되는 cleanup hook 등록
"""
from __future__ import annotations


# >>> LLM_SESSION_LOG_PATH_FIX_v1 (auto-inserted by FIX_SESSION_LOG_PATH.py v7.7; do not edit between markers)
def _llm_session_log_dir():
    """세션 로그를 llm_environment/logs 아래로 강제 (cwd 오염 방지)."""
    import os
    from pathlib import Path
    ov = os.environ.get("LLM_ENV_DIR")
    if ov:
        b = Path(ov)
        d = b / "logs" if b.name != "logs" else b
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d
    try:
        here = Path(__file__).resolve()
        cands = [here.parent] + list(here.parents)
    except Exception:
        cands = [Path.cwd()]
    for c in cands:
        try:
            if (c / "llm_environment").is_dir() or (c / "RUN.bat").exists() or (c / "INSTALL.bat").exists():
                d = c / "llm_environment" / "logs"
                d.mkdir(parents=True, exist_ok=True)
                return d
        except Exception:
            continue
    d = Path.cwd() / "llm_environment" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
# <<< LLM_SESSION_LOG_PATH_FIX_v1
import atexit
import datetime
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, List, Optional, TextIO


__all__ = [
    "install_global_hooks",
    "register_cleanup",
    "log",
    "log_session",
    "open_session_log",
    "shutdown_then_exit",
    "force_kill_container",
    "get_log_dir",
]


# ─────────────────────────────────────────────
#  전역 상태
# ─────────────────────────────────────────────
_lock = threading.RLock()
_installed = False
_project_root: Optional[Path] = None
_log_dir: Optional[Path] = None
_main_log_fh: Optional[TextIO] = None
_cleanup_callbacks: List[Callable[[], None]] = []
_cleanups_ran = False


# ─────────────────────────────────────────────
#  내부 유틸
# ─────────────────────────────────────────────
def _safe_fsync(fh: TextIO) -> None:
    try:
        fh.flush()
    except Exception:
        pass
    try:
        os.fsync(fh.fileno())
    except (OSError, AttributeError, ValueError):
        pass


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _ts_file() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_pythonw() -> bool:
    """현재 프로세스가 pythonw.exe (콘솔 없음) 인지 감지."""
    # pythonw.exe 는 stdout/stderr 가 None 이거나 fileno 없음
    try:
        sys.stdout.fileno()
        return False
    except (AttributeError, OSError, ValueError):
        return True


def _has_console_window() -> bool:
    """Windows 콘솔이 실제로 attached 되어 있는지 확인."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        # GetConsoleWindow 가 0 이면 콘솔 없음
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        return hwnd != 0
    except Exception:
        return False


# ─────────────────────────────────────────────
#  fatal 로그 (lifelog 자체의 예외 추적용)
# ─────────────────────────────────────────────
def _write_fatal(stage: str, exc: BaseException) -> None:
    """lifelog 자체에서 예외 발생 시 별도 파일에 기록."""
    if _log_dir is None:
        return
    try:
        with open(_log_dir / "lifelog_fatal.log", "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write("[" + _ts() + "] FATAL at stage: " + stage + "\n")
            f.write("=" * 60 + "\n")
            f.write(traceback.format_exc())
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
    except Exception:
        pass


# ─────────────────────────────────────────────
#  로그 디렉터리 / 메인 로그 파일
# ─────────────────────────────────────────────
def get_log_dir() -> Path:
    with _lock:
        if _log_dir is not None:
            return _log_dir
        fallback = Path.cwd() / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _open_main_log() -> Optional[TextIO]:
    global _main_log_fh
    if _log_dir is None:
        return None
    try:
        path = _log_dir / ("launcher_" + _ts_file() + ".log")
        _main_log_fh = open(path, "w", encoding="utf-8", buffering=1)
        _main_log_fh.write("=" * 60 + "\n")
        _main_log_fh.write("  Launcher session log\n")
        _main_log_fh.write("  Started: " + datetime.datetime.now().isoformat() + "\n")
        _main_log_fh.write("  PID: " + str(os.getpid()) + "\n")
        _main_log_fh.write("  Python: " + sys.version.split()[0] + "\n")
        _main_log_fh.write("  Platform: " + sys.platform + "\n")
        _main_log_fh.write("  Executable: " + sys.executable + "\n")
        _main_log_fh.write("  pythonw mode: " + str(_is_pythonw()) + "\n")
        _main_log_fh.write("  has console: " + str(_has_console_window()) + "\n")
        _main_log_fh.write("  main thread: " + str(
            threading.current_thread() is threading.main_thread()
        ) + "\n")
        _main_log_fh.write("=" * 60 + "\n")
        _safe_fsync(_main_log_fh)
        return _main_log_fh
    except OSError:
        _main_log_fh = None
        return None


def log(level: str, msg: str) -> None:
    """메인 launcher 로그에 한 줄 기록 + 즉시 flush+fsync."""
    line = "[" + _ts() + "] [" + level.ljust(7) + "] " + msg + "\n"
    with _lock:
        if _main_log_fh is not None:
            try:
                _main_log_fh.write(line)
                _safe_fsync(_main_log_fh)
            except (OSError, ValueError):
                pass
        # 콘솔에도 (best-effort, pythonw 에서는 무시됨)
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except (OSError, ValueError, AttributeError):
            pass


def open_session_log(name: str) -> Optional[TextIO]:
    if _log_dir is None:
        return None
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
    try:
        path = _log_dir / (safe_name + "_" + _ts_file() + ".log")
        fh = open(str(_llm_session_log_dir() / (path)), "w", encoding="utf-8", buffering=1)
        fh.write("=" * 60 + "\n")
        fh.write("  Session: " + name + "\n")
        fh.write("  Started: " + datetime.datetime.now().isoformat() + "\n")
        fh.write("=" * 60 + "\n")
        _safe_fsync(fh)
        log("INFO", "세션 로그 오픈: " + path.name)
        return fh
    except OSError as e:
        log("FAIL", "세션 로그 오픈 실패 (" + name + "): " + str(e))
        return None


def log_session(fh: Optional[TextIO], level: str, msg: str) -> None:
    if fh is None:
        return
    line = "[" + _ts() + "] [" + level.ljust(7) + "] " + msg + "\n"
    try:
        fh.write(line)
        _safe_fsync(fh)
    except (OSError, ValueError):
        pass


# ─────────────────────────────────────────────
#  정리 콜백 관리
# ─────────────────────────────────────────────
def register_cleanup(fn: Callable[[], None]) -> None:
    with _lock:
        _cleanup_callbacks.append(fn)
        log("INFO", "cleanup 콜백 등록 (총 " + str(len(_cleanup_callbacks)) + "개)")


def _run_all_cleanups(reason: str = "?") -> None:
    global _cleanups_ran
    with _lock:
        if _cleanups_ran:
            return
        _cleanups_ran = True
        callbacks = list(_cleanup_callbacks)

    log("CLEANUP", "=== 종료 정리 시작 (사유: " + reason + ") ===")
    log("CLEANUP", "콜백 " + str(len(callbacks)) + "개 실행")
    for i, fn in enumerate(callbacks):
        try:
            log("CLEANUP", "[" + str(i + 1) + "/" + str(len(callbacks)) + "] " + repr(fn))
            fn()
            log("CLEANUP", "[" + str(i + 1) + "/" + str(len(callbacks)) + "] 완료")
        except Exception as e:
            log("FAIL", "cleanup 실패: " + str(e))
            log("DEBUG", traceback.format_exc())
    log("CLEANUP", "=== 종료 정리 완료 ===")
    with _lock:
        if _main_log_fh is not None:
            try:
                _safe_fsync(_main_log_fh)
                _main_log_fh.close()
            except (OSError, ValueError):
                pass


# ─────────────────────────────────────────────
#  컨테이너 강제 격멸
# ─────────────────────────────────────────────
def force_kill_container(name: str, timeout: int = 2) -> bool:
    if not name:
        return False
    log("CLEANUP", "컨테이너 격멸 시도: " + name)
    no_window = {}
    if os.name == "nt":
        no_window["creationflags"] = 0x08000000

    try:
        r = subprocess.run(
            ["docker", "stop", "-t", str(timeout), name],
            capture_output=True, timeout=timeout + 5, **no_window
        )
        if r.returncode == 0:
            log("OK", "docker stop 성공: " + name)
            _docker_rm(name)
            return True
        log("WARN", "docker stop 실패 (" + name + "): rc=" + str(r.returncode))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log("WARN", "docker stop 예외: " + str(e))

    try:
        r = subprocess.run(
            ["docker", "kill", name],
            capture_output=True, timeout=5, **no_window
        )
        if r.returncode == 0:
            log("OK", "docker kill 성공: " + name)
            _docker_rm(name)
            return True
        log("FAIL", "docker kill 실패: rc=" + str(r.returncode))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log("FAIL", "docker kill 예외: " + str(e))

    return False


def _docker_rm(name: str) -> None:
    no_window = {}
    if os.name == "nt":
        no_window["creationflags"] = 0x08000000
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, timeout=5, **no_window
        )
        log("OK", "docker rm -f 완료: " + name)
    except Exception as e:
        log("WARN", "docker rm 예외: " + str(e))


# ─────────────────────────────────────────────
#  종료 hook 들
# ─────────────────────────────────────────────
def _atexit_hook() -> None:
    _run_all_cleanups("atexit")


def _signal_hook(signum, frame) -> None:
    log("CLEANUP", "신호 수신: signum=" + str(signum))
    _run_all_cleanups("signal_" + str(signum))
    if signum == signal.SIGINT:
        sys.exit(130)
    if hasattr(signal, "SIGTERM") and signum == signal.SIGTERM:
        sys.exit(143)
    sys.exit(1)


def _windows_console_handler(ctrl_type) -> int:
    type_names = {0: "CTRL_C", 1: "CTRL_BREAK", 2: "CTRL_CLOSE",
                  5: "CTRL_LOGOFF", 6: "CTRL_SHUTDOWN"}
    log("CLEANUP", "Windows ctrl handler: " + type_names.get(ctrl_type, str(ctrl_type)))
    _run_all_cleanups("win_ctrl_" + str(ctrl_type))
    return 1


def shutdown_then_exit() -> None:
    log("CLEANUP", "shutdown_then_exit 호출")
    _run_all_cleanups("gui_close")


# ─────────────────────────────────────────────
#  v6.1: 개별 hook 설치 함수 (각각 try/except 로 isolation)
# ─────────────────────────────────────────────
def _install_atexit() -> None:
    log("INFO", "[hook 1/4] atexit 설치 시도")
    try:
        atexit.register(_atexit_hook)
        log("OK", "[hook 1/4] atexit 설치 성공")
    except Exception as e:
        log("FAIL", "[hook 1/4] atexit 설치 실패: " + str(e))
        _write_fatal("install_atexit", e)


def _install_sigint() -> None:
    log("INFO", "[hook 2/4] SIGINT 설치 시도")
    # 메인 스레드인지 확인
    if threading.current_thread() is not threading.main_thread():
        log("WARN", "[hook 2/4] 메인 스레드 아님 — SIGINT skip")
        return
    try:
        signal.signal(signal.SIGINT, _signal_hook)
        log("OK", "[hook 2/4] SIGINT 설치 성공")
    except (ValueError, OSError) as e:
        log("FAIL", "[hook 2/4] SIGINT 설치 실패: " + str(e))
        _write_fatal("install_sigint", e)


def _install_sigterm() -> None:
    log("INFO", "[hook 3/4] SIGTERM 설치 시도")
    if not hasattr(signal, "SIGTERM"):
        log("WARN", "[hook 3/4] SIGTERM 없음 — skip")
        return
    if threading.current_thread() is not threading.main_thread():
        log("WARN", "[hook 3/4] 메인 스레드 아님 — SIGTERM skip")
        return
    try:
        signal.signal(signal.SIGTERM, _signal_hook)
        log("OK", "[hook 3/4] SIGTERM 설치 성공")
    except (ValueError, OSError) as e:
        log("FAIL", "[hook 3/4] SIGTERM 설치 실패: " + str(e))
        _write_fatal("install_sigterm", e)


def _install_win_console_handler() -> None:
    log("INFO", "[hook 4/4] Windows ConsoleCtrlHandler 설치 시도")
    if os.name != "nt":
        log("INFO", "[hook 4/4] Windows 아님 — skip")
        return
    # pythonw 환경에서는 콘솔이 없음 -> skip
    if _is_pythonw():
        log("INFO", "[hook 4/4] pythonw 환경 (stdout 없음) — skip")
        return
    if not _has_console_window():
        log("INFO", "[hook 4/4] 콘솔 윈도우 없음 (GetConsoleWindow=0) — skip")
        return
    try:
        import ctypes
        log("INFO", "[hook 4/4] ctypes import OK")
        HANDLER_TYPE = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
        log("INFO", "[hook 4/4] HANDLER_TYPE 생성 OK")
        _handler_ref = HANDLER_TYPE(_windows_console_handler)
        log("INFO", "[hook 4/4] handler 콜백 생성 OK")
        # 모듈 전역에 ref 유지 (GC 방지)
        globals()["_win_handler_ref"] = _handler_ref
        log("INFO", "[hook 4/4] SetConsoleCtrlHandler 호출 직전")
        result = ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_ref, True)
        if result:
            log("OK", "[hook 4/4] Windows ConsoleCtrlHandler 설치 성공")
        else:
            err = ctypes.windll.kernel32.GetLastError()
            log("WARN", "[hook 4/4] SetConsoleCtrlHandler 0 반환 (GetLastError=" + str(err) + ")")
    except Exception as e:
        log("FAIL", "[hook 4/4] Windows hook 설치 예외: " + str(e))
        _write_fatal("install_win_console_handler", e)


# ─────────────────────────────────────────────
#  install_global_hooks (v6.1)
# ─────────────────────────────────────────────
def install_global_hooks(project_root: Path) -> None:
    """모든 hook 을 설치. __main__ 에서 한 번만 호출.

    v6.1 변경: 각 단계마다 로그 -> 실패 시 정확한 위치 식별.
    개별 hook 은 try/except 로 isolation.
    """
    global _installed, _project_root, _log_dir

    # ── 단계 1: 기본 초기화 ──
    try:
        with _lock:
            if _installed:
                print("[WARN] install_global_hooks 중복 호출 — 무시", file=sys.stderr)
                return
            _installed = True
            _project_root = Path(project_root).resolve()
            _log_dir = _project_root / "logs"
            try:
                _log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                print("[FAIL] logs 디렉터리 생성 실패: " + str(e), file=sys.stderr)
                _log_dir = None
                return
            _open_main_log()
    except Exception as e:
        print("[FAIL] lifelog 기본 초기화 실패: " + str(e), file=sys.stderr)
        traceback.print_exc()
        return

    # 이 시점부터 log() 사용 가능
    try:
        log("INFO", "lifelog 초기화 완료 (v6.1)")
        log("INFO", "프로젝트 루트: " + str(_project_root))
        log("INFO", "로그 디렉터리: " + str(_log_dir))
        log("INFO", "Python 실행파일: " + sys.executable)
        log("INFO", "pythonw 환경: " + str(_is_pythonw()))
        log("INFO", "콘솔 윈도우 attached: " + str(_has_console_window()))
        log("INFO", "메인 스레드: " + str(threading.current_thread() is threading.main_thread()))
    except Exception as e:
        _write_fatal("post_init_logging", e)

    # ── 단계 2: 각 hook 개별 설치 (개별 try/except) ──
    _install_atexit()
    _install_sigint()
    _install_sigterm()
    _install_win_console_handler()

    log("OK", "전역 종료 hook 설치 단계 모두 통과")

# v6_3_comprehensive: Ollama 메모리 관리 함수


# ─────────────────────────────────────────────
#  v6_3_comprehensive: Ollama 메모리 관리
# ─────────────────────────────────────────────
def unload_ollama_model(model_tag: str = "", host: str = "http://127.0.0.1:11434") -> bool:
    """Ollama 에서 모델을 메모리에서 즉시 unload.

    /api/generate 를 keep_alive=0 으로 호출하면 그 모델이 즉시 unload 됨.
    model_tag 가 빈 문자열이면 /api/ps 로 적재된 모델 목록 받아 모두 unload.

    Returns True if at least one model unloaded.
    """
    import json as _json
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    log("CLEANUP", "Ollama 메모리 정리 시도")

    targets = []
    if model_tag:
        targets = [model_tag]
    else:
        # /api/ps 로 적재된 모델 목록 조회
        try:
            req = _urlreq.Request(host + "/api/ps", method="GET")
            with _urlreq.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            for entry in data.get("models", []):
                name = entry.get("name") or entry.get("model")
                if name:
                    targets.append(name)
            log("INFO", "적재된 모델 " + str(len(targets)) + "개 발견: " + ", ".join(targets))
        except (_urlerr.URLError, OSError, ValueError) as e:
            log("WARN", "Ollama /api/ps 조회 실패: " + str(e))
            return False

    if not targets:
        log("INFO", "적재된 Ollama 모델 없음 — 정리 불필요")
        return True

    success = 0
    for name in targets:
        try:
            payload = _json.dumps({
                "model": name,
                "keep_alive": 0,
                "prompt": "",
            }).encode("utf-8")
            req = _urlreq.Request(
                host + "/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _urlreq.urlopen(req, timeout=5) as resp:
                _ = resp.read()
            log("OK", "Ollama 모델 unload: " + name)
            success += 1
        except (_urlerr.URLError, OSError, ValueError) as e:
            log("WARN", "모델 " + name + " unload 실패: " + str(e))

    return success > 0


def register_ollama_cleanup(model_tag: str = "", host: str = "http://127.0.0.1:11434") -> None:
    """종료 시 Ollama 모델을 자동 unload 하도록 cleanup 등록."""
    def _do():
        try:
            unload_ollama_model(model_tag, host)
        except Exception as e:
            log("WARN", "Ollama unload cleanup 예외: " + str(e))

    register_cleanup(_do)
    log("INFO", "Ollama 메모리 정리 cleanup 등록됨")

# v6_4_orphan: 도커 컨테이너 강제 정리 함수


# ─────────────────────────────────────────────
#  v6_4_orphan: 도커 컨테이너 강제 정리
# ─────────────────────────────────────────────
def cleanup_orphan_containers(
    name_patterns: tuple = ("ai_box_", "open_webui", "searxng", "ollama"),
    image_patterns: tuple = ("ai_box_sandbox", "open_webui", "searxng", "ollama"),
) -> int:
    """v6_5_image: docker ps 로 우리 컨테이너 모두 강제 정리.

    매칭 로직: 컨테이너 이름이 name_patterns 중 하나를 포함하거나
              이미지 이름이 image_patterns 중 하나를 포함하면 정리 대상.

    종료 시 자동 호출 — docker --rm 이 동작 안 했거나 강제 종료 등으로
    살아남은 컨테이너를 강제 정리.

    또한 docker ps -a (exited 포함) 도 조회해서 진단 정보로 출력.

    Returns: 정리된 컨테이너 수.
    """
    log("CLEANUP", "v6.5 고아 컨테이너 검색 시작")
    log("CLEANUP", "  이름 패턴: " + ", ".join(name_patterns))
    log("CLEANUP", "  이미지 패턴: " + ", ".join(image_patterns))

    no_window = {}
    if os.name == "nt":
        no_window["creationflags"] = 0x08000000

    # 1) docker ps (실행 중) — 이름 + 이미지 + 상태 모두 수집
    rows = []
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True, timeout=5, text=True, **no_window
        )
        if r.returncode != 0:
            log("WARN", "docker ps 실패: rc=" + str(r.returncode)
                + ", stderr=" + (r.stderr or "").strip()[:200])
            return 0
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[0].strip()
                image = parts[1].strip()
                status = parts[2].strip() if len(parts) > 2 else ""
                if name:
                    rows.append((name, image, status))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log("WARN", "docker ps 예외: " + str(e))
        return 0

    log("INFO", "실행 중 도커 컨테이너 " + str(len(rows)) + "개")
    if not rows:
        log("INFO", "정리할 컨테이너 없음")
        # exited 컨테이너 진단도 함께
        _diagnose_exited_containers(no_window, name_patterns, image_patterns)
        return 0

    # 모든 컨테이너 정보 로그 출력 (진단)
    for name, image, status in rows:
        log("INFO", "  [발견] name=" + name + " image=" + image + " status=" + status)

    # 2) 매칭 — 이름 OR 이미지
    targets = []
    skipped = []
    for name, image, status in rows:
        matched_by = None
        for pat in name_patterns:
            if pat and pat in name:
                matched_by = "name(" + pat + ")"
                break
        if matched_by is None:
            for pat in image_patterns:
                if pat and pat in image:
                    matched_by = "image(" + pat + ")"
                    break

        if matched_by:
            targets.append((name, image, matched_by))
        else:
            skipped.append((name, image))

    if skipped:
        log("INFO", "정리 안함 (외부 컨테이너): " + str(len(skipped)) + "개")
        for name, image in skipped:
            log("INFO", "  [skip] name=" + name + " image=" + image)

    if not targets:
        log("INFO", "정리 대상 컨테이너 없음 — 우리 컨테이너 패턴에 매칭 안됨")
        log("INFO", "  사용자: 만약 위 [발견] 항목이 우리 컨테이너라면")
        log("INFO", "  patch v6.5 의 name_patterns/image_patterns 에 추가 필요")
        _diagnose_exited_containers(no_window, name_patterns, image_patterns)
        return 0

    log("CLEANUP", "정리 대상 " + str(len(targets)) + "개")
    for name, image, mb in targets:
        log("CLEANUP", "  [target] name=" + name + " (matched by " + mb + ")")

    # 3) 각각 격멸
    killed = 0
    for name, image, _mb in targets:
        try:
            r = subprocess.run(
                ["docker", "stop", "-t", "2", name],
                capture_output=True, timeout=8, **no_window
            )
            if r.returncode == 0:
                log("OK", "docker stop: " + name)
            else:
                subprocess.run(
                    ["docker", "kill", name],
                    capture_output=True, timeout=5, **no_window
                )
                log("OK", "docker kill: " + name)

            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True, timeout=5, **no_window
            )
            killed += 1
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log("FAIL", "정리 실패 (" + name + "): " + str(e))

    log("CLEANUP", "도커 컨테이너 정리 완료: " + str(killed) + "/" + str(len(targets)))
    _diagnose_exited_containers(no_window, name_patterns, image_patterns)
    return killed


def _diagnose_exited_containers(no_window, name_patterns, image_patterns) -> None:
    """진단용 — exited 우리 컨테이너 목록만 로그에 출력 (정리 안함).

    종료 후 docker ps -a 에 남은 exited 컨테이너가 있으면 사용자에게 알림.
    """
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", "status=exited",
             "--format", "{{.Names}}\t{{.Image}}"],
            capture_output=True, timeout=5, text=True, **no_window
        )
        if r.returncode != 0:
            return
        our_exited = []
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[0].strip()
            image = parts[1].strip()
            matched = False
            for pat in name_patterns:
                if pat and pat in name:
                    matched = True; break
            if not matched:
                for pat in image_patterns:
                    if pat and pat in image:
                        matched = True; break
            if matched:
                our_exited.append((name, image))
        if our_exited:
            log("INFO", "exited 우리 컨테이너 " + str(len(our_exited)) + "개 (이미 죽음, 정리 불필요)")
            for name, image in our_exited:
                log("INFO", "  [exited] name=" + name + " image=" + image)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass



def register_orphan_container_cleanup(
    name_patterns: tuple = ("ai_box_", "open_webui", "searxng", "ollama"),
    image_patterns: tuple = ("ai_box_sandbox", "open_webui", "searxng", "ollama"),
) -> None:
    """종료 시 모든 우리 도커 컨테이너 강제 정리 cleanup 등록."""
    def _do():
        try:
            cleanup_orphan_containers(name_patterns, image_patterns)
        except Exception as e:
            log("WARN", "orphan cleanup 예외: " + str(e))

    register_cleanup(_do)
    log("INFO", "고아 컨테이너 정리 cleanup 등록됨 (패턴: " + ", ".join(name_patterns) + ")")

# v6_7_final: config 자동 감지 패턴


# ─────────────────────────────────────────────
#  v6_7_final: config 기반 패턴 자동 감지
# ─────────────────────────────────────────────
def _detect_container_patterns() -> tuple:
    """config 모듈에서 실제 컨테이너 prefix/image 를 읽어 패턴 튜플 반환.

    Returns:
        (name_patterns, image_patterns) — 각각 tuple of str
    """
    name_patterns = []
    image_patterns = []

    # config 에서 직접 읽기
    try:
        from . import config as _cfg
        # SANDBOX_CONTAINER_PREFIX (예: "llm_agent_")
        prefix = getattr(_cfg, "SANDBOX_CONTAINER_PREFIX", None)
        if prefix:
            name_patterns.append(prefix.rstrip("_") + "_")
            log("INFO", "config.SANDBOX_CONTAINER_PREFIX 감지: " + prefix)
        # SANDBOX_IMAGE (예: "llm-agent-sandbox")
        image = getattr(_cfg, "SANDBOX_IMAGE", None)
        if image:
            # 태그 (:latest) 제거
            image_base = image.split(":")[0]
            image_patterns.append(image_base)
            log("INFO", "config.SANDBOX_IMAGE 감지: " + image_base)
        # 추가 컨테이너 이름들
        for key in ("OLLAMA_CONTAINER_NAME", "OPENWEBUI_CONTAINER_NAME",
                    "SEARXNG_CONTAINER_NAME", "OLLAMA_IMAGE",
                    "OPENWEBUI_IMAGE", "SEARXNG_IMAGE"):
            val = getattr(_cfg, key, None)
            if val:
                if "IMAGE" in key:
                    image_patterns.append(val.split(":")[0])
                else:
                    name_patterns.append(val)
                log("INFO", "config." + key + " 감지: " + val)
    except Exception as e:
        log("WARN", "config 자동 감지 실패: " + str(e))

    # Fallback 패턴 (항상 추가 — 안전망)
    fallback_names = ["ai_box_", "llm_agent_", "llm_ollama", "llm_openwebui",
                      "llm_searxng", "open_webui", "searxng", "ollama"]
    fallback_images = ["ai_box_sandbox", "llm-agent-sandbox", "llm_agent_sandbox",
                       "open_webui", "openwebui", "searxng", "ollama"]
    for p in fallback_names:
        if p not in name_patterns:
            name_patterns.append(p)
    for p in fallback_images:
        if p not in image_patterns:
            image_patterns.append(p)

    log("INFO", "최종 이름 패턴 " + str(len(name_patterns)) + "개")
    log("INFO", "최종 이미지 패턴 " + str(len(image_patterns)) + "개")
    return tuple(name_patterns), tuple(image_patterns)


def register_orphan_container_cleanup_auto() -> None:
    """v6_7_final: config 자동 감지로 패턴 결정 후 cleanup 등록."""
    try:
        names, images = _detect_container_patterns()
    except Exception as e:
        log("WARN", "auto-detect 실패, 정적 패턴 fallback: " + str(e))
        names = ("ai_box_", "llm_agent_", "open_webui", "searxng", "ollama")
        images = ("ai_box_sandbox", "llm-agent-sandbox",
                  "open_webui", "searxng", "ollama")

    def _do():
        try:
            cleanup_orphan_containers(names, images)
        except Exception as e:
            log("WARN", "auto orphan cleanup 예외: " + str(e))

    register_cleanup(_do)
    log("INFO", "v6.7 고아 컨테이너 정리 cleanup 등록됨 (자동 감지)")
    log("INFO", "  이름: " + ", ".join(names))
    log("INFO", "  이미지: " + ", ".join(images))

# v6_9_visibility


# ─────────────────────────────────────────────
#  v6_9_visibility: Ollama 모델 사전 warm-up
# ─────────────────────────────────────────────
def warmup_ollama_model(model_tag: str, host: str = "http://127.0.0.1:11434",
                       timeout: int = 30) -> bool:
    """Ollama 모델을 메모리에 미리 로드.

    docker 컨테이너 실행 직전 호출하면 첫 응답 지연 (~수십초) 제거.
    /api/generate 를 keep_alive 만 설정해서 1토큰 생성 -> 모델 로드 트리거.

    Returns True 면 모델이 메모리에 로드됨.
    """
    import json as _json
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    if not model_tag:
        return False

    log("INFO", "Ollama 모델 warm-up: " + model_tag)
    try:
        payload = _json.dumps({
            "model": model_tag,
            "prompt": "Hi",
            "stream": False,
            "keep_alive": "10m",
            "options": {"num_predict": 1},
        }).encode("utf-8")
        req = _urlreq.Request(
            host + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
        elapsed = time.time() - t0
        log("OK", "모델 warm-up 완료 (" + str(round(elapsed, 1)) + "초): " + model_tag)
        return True
    except (_urlerr.URLError, OSError, ValueError) as e:
        log("WARN", "모델 warm-up 실패: " + str(e))
        return False


def assert_v68_applied(agent_sandbox_path) -> bool:
    """v6.8 의 환경변수/max_tokens 가 적용됐는지 검증.

    사용자가 콘솔에서 직접 호출 가능:
        from launcher.lifelog import assert_v68_applied
        from pathlib import Path
        assert_v68_applied(Path("launcher/actions/agent_sandbox.py"))
    """
    from pathlib import Path as _P
    p = _P(agent_sandbox_path) if not isinstance(agent_sandbox_path, _P) else agent_sandbox_path
    if not p.exists():
        log("FAIL", "agent_sandbox.py 없음")
        return False
    text = p.read_text(encoding="utf-8")
    checks = [
        ("PYTHONUNBUFFERED", "PYTHONUNBUFFERED=1 환경변수"),
        ("LITELLM_LOG", "LITELLM_LOG=ERROR 환경변수"),
        ("max_tokens", "--max_tokens 인자"),
    ]
    all_ok = True
    for marker, desc in checks:
        if marker in text:
            log("OK", "v6.8 적용 확인: " + desc)
        else:
            log("FAIL", "v6.8 미적용: " + desc)
            all_ok = False
    return all_ok

# v7_1_unified: 호스트 프로세스 정리


# ─────────────────────────────────────────────
#  v7_1_unified: 호스트 interpreter 프로세스 정리
# ─────────────────────────────────────────────
def register_host_process_cleanup(get_pid_fn) -> None:
    """호스트 직접 모드의 interpreter 프로세스 종료 cleanup 등록.

    get_pid_fn: 현재 활성 PID 를 반환하는 콜러블 (없으면 None).
    종료 시 해당 PID 프로세스를 graceful -> forceful 종료.
    """
    def _do():
        try:
            pid = get_pid_fn()
        except Exception:
            pid = None
        if not pid:
            return
        log("CLEANUP", "호스트 interpreter 프로세스 종료 시도: PID=" + str(pid))
        no_window = {}
        if os.name == "nt":
            no_window["creationflags"] = 0x08000000
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=5, **no_window
                )
                log("OK", "taskkill 완료: PID=" + str(pid))
            else:
                import signal as _sig
                os.kill(pid, _sig.SIGTERM)
                log("OK", "SIGTERM 전송: PID=" + str(pid))
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError) as e:
            log("WARN", "프로세스 종료 예외: " + str(e))

    register_cleanup(_do)
    log("INFO", "호스트 프로세스 정리 cleanup 등록됨")

# v7_5_dockercheck


# ─────────────────────────────────────────────
#  v7_5_dockercheck: Docker 데몬 상태 확인
# ─────────────────────────────────────────────
def check_docker_running(timeout: int = 3) -> bool:
    """Docker 데몬이 응답하는지 확인.

    Returns True 면 docker info 성공 (데몬 살아있음).
    docker 미설치/미실행/응답없음 모두 False.
    """
    no_window = {}
    if os.name == "nt":
        no_window["creationflags"] = 0x08000000
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=timeout, **no_window
        )
        ok = (r.returncode == 0)
        if ok:
            log("INFO", "Docker 데몬 응답 정상")
        else:
            log("WARN", "Docker 데몬 미응답 (docker info rc=" + str(r.returncode) + ")")
        return ok
    except subprocess.TimeoutExpired:
        log("WARN", "Docker 데몬 응답 타임아웃")
        return False
    except (FileNotFoundError, OSError) as e:
        log("WARN", "Docker 명령 실행 불가: " + str(e))
        return False

