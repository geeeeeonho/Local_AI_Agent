"""lifelog — 통합 로그 시스템과 프로세스 종료 hook.

핵심 책임
─────────
1. 현재 계정의 users/<account>/logs 폴더에 세션 로그 기록
2. 매 줄마다 flush + os.fsync
3. 모든 종료 경로에서 호출되는 cleanup hook 등록
"""
from __future__ import annotations


def _llm_session_log_dir():
    """Return the current Windows account's private log directory."""
    from pathlib import Path
    try:
        import project_paths
        d = project_paths.logs_dir()
    except Exception:
        d = Path.cwd() / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d

import atexit
import datetime
import os
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, List, Optional, TextIO


__all__ = [
    "install_global_hooks",
    "register_cleanup",
    "CLEANUP_STAGES",
    "log",
    "log_session",
    "open_session_log",
    "shutdown_then_exit",
    "suppress_exit_cleanups",
    "rearm_exit_cleanups",
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
# 종료 정리는 순서가 의미를 가진다. 등록 시각이 아니라 의도로 순서를 정한다:
#   runtime — 우리가 띄운 컨테이너/서버를 멈춘다
#   sweep   — 그렇게 남은 찌꺼기를 치운다 (멈춘 뒤라야 치울 게 보인다)
#   daemon  — Docker 데몬 자체를 내린다 (앞의 둘이 전부 데몬을 필요로 한다)
CLEANUP_STAGES = ("runtime", "sweep", "daemon")
_cleanup_callbacks: List[Callable[[], None]] = []
_sweep_cleanup_callbacks: List[Callable[[], None]] = []
_final_cleanup_callbacks: List[Callable[[], None]] = []
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


# 실행마다 새 파일을 만들고 지우는 곳이 없었다. 터미널 런처만 이 코드를
# 부르던 동안에는 눈에 띄지 않았지만, 데스크톱 창도 같은 종료 hook 을 쓰게
# 되면서 창을 열 때마다 한 개씩 쌓인다. agent_trace 와 같은 방식으로 최근
# 것만 남긴다 — 진단에 필요한 것은 마지막 몇 번의 실행이다.
_KEEP_LAUNCHER_LOGS = 20


def _prune_old_logs(keep: Optional[int] = None) -> None:
    """이번 세션 파일보다 오래된 실행 로그를 정리. 실패는 무시한다."""
    if _log_dir is None:
        return
    keep = _KEEP_LAUNCHER_LOGS if keep is None else keep
    current = getattr(_main_log_fh, "name", None)
    try:
        # 이름이 launcher_<YYYYmmdd>_<HHMMSS>.log 인 것만. launcher_fatal.log
        # 는 크래시 기록이고 하나뿐이므로 건드리지 않는다.
        existing = sorted(
            (path for path in _log_dir.glob("launcher_2*.log")
             if str(path) != str(current)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    # keep 은 이번 실행 파일을 포함한 총 개수다.
    room = keep - (1 if current else 0)
    for stale in existing[max(0, room):]:
        try:
            stale.unlink()
        except OSError:
            pass


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
        path = _llm_session_log_dir() / (safe_name + "_" + _ts_file() + ".log")  # SESSION_LOG_PATH_FIX_v2
        fh = open(str(path), "w", encoding="utf-8", buffering=1)  # PATH_UNIFY_v1: 이중 join 제거
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
def register_cleanup(fn: Callable[[], None], *, stage: str = "runtime") -> None:
    """종료 정리 콜백을 단계와 함께 등록한다 (:data:`CLEANUP_STAGES` 참고).

    순서를 등록 시각에 맡기면, 정리를 하나 추가하는 것만으로 조용히 깨진다.
    찌꺼기 청소는 컨테이너가 멈춘 뒤에, 데몬 종료는 그 둘 다 끝난 뒤에 돌아야
    한다.
    """
    if stage not in CLEANUP_STAGES:
        raise ValueError("unknown cleanup stage: " + str(stage))
    buckets = {"runtime": _cleanup_callbacks, "sweep": _sweep_cleanup_callbacks,
               "daemon": _final_cleanup_callbacks}
    with _lock:
        buckets[stage].append(fn)
        total = sum(len(bucket) for bucket in buckets.values())
        log("INFO", "cleanup 콜백 등록 (총 " + str(total) + "개, 단계=" + stage + ")")


def _run_all_cleanups(reason: str = "?") -> None:
    global _cleanups_ran
    with _lock:
        if _cleanups_ran:
            return
        _cleanups_ran = True
        callbacks = (list(_cleanup_callbacks) + list(_sweep_cleanup_callbacks)
                     + list(_final_cleanup_callbacks))

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


def suppress_exit_cleanups() -> None:
    """Mark callbacks consumed without running them.

    Used only when another Windows account already owns the machine-wide
    runtime lock. Running this process's stale shared-container callbacks then
    would tear down the other account's active runtime.
    """
    global _cleanups_ran
    with _lock:
        _cleanups_ran = True


def rearm_exit_cleanups() -> None:
    """Allow registered callbacks to run for a newly acquired runtime lease."""
    global _cleanups_ran
    with _lock:
        _cleanups_ran = False


# ─────────────────────────────────────────────
#  current: 개별 hook 설치 함수 (각각 try/except 로 isolation)
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
#  install_global_hooks (current)
# ─────────────────────────────────────────────
def install_global_hooks(project_root: Path) -> None:
    """모든 hook 을 설치. __main__ 에서 한 번만 호출.

    ``project_root`` is retained for diagnostics only. Logs always go to the
    current account's canonical ``project_paths.logs_dir()`` so one Windows
    account never writes another account's runtime records.
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
            # Runtime binaries are shared, but logs are personal usage data.
            _log_dir = _llm_session_log_dir().resolve()
            try:
                _log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                print("[FAIL] logs 디렉터리 생성 실패: " + str(e), file=sys.stderr)
                _log_dir = None
                return
            _open_main_log()
            _prune_old_logs()
    except Exception as e:
        print("[FAIL] lifelog 기본 초기화 실패: " + str(e), file=sys.stderr)
        traceback.print_exc()
        return

    # 이 시점부터 log() 사용 가능
    try:
        log("INFO", "lifelog 초기화 완료 (current)")
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

# >>> CACHE_CLEANUP_v1 - 종료 시 캐시 자동 정리
def register_cache_cleanup(data_root) -> None:
    """종료 시 chat/cache 와 잔여 .tmp 를 자동 정리하도록 등록.

    ``data_root`` 는 정리 대상인 user_data 폴더 자체다. 예전에는 프로젝트
    루트를 받아 여기서 ``/user_data`` 를 다시 붙였는데, 런타임 루트가 생긴
    뒤로는 그 조합이 존재하지 않는 폴더를 가리킨다.

    임베딩/모델 다운로드(오프라인에서 재다운로드 비쌈)는 보존한다.
    """
    from pathlib import Path as _P

    _PRESERVE = ("embedding", "embeddings", "model", "models",
                 "whisper", "sentence-transformers", "hub", "tiktoken")

    def _do():
        import shutil as _sh
        try:
            ud = _P(data_root)
            cache = ud / "chat" / "cache"
            removed = 0
            freed = 0
            if cache.is_dir():
                for item in list(cache.iterdir()):
                    nm = item.name.lower()
                    if item.is_dir() and any(k in nm for k in _PRESERVE):
                        continue  # 모델/임베딩 보존
                    try:
                        if item.is_dir():
                            for f in item.rglob("*"):
                                try:
                                    if f.is_file():
                                        freed += f.stat().st_size
                                except OSError:
                                    pass
                            _sh.rmtree(item, ignore_errors=True)
                        else:
                            freed += item.stat().st_size
                            item.unlink()
                        removed += 1
                    except OSError:
                        pass
            if ud.is_dir():
                for t in ud.rglob("*.tmp"):
                    try:
                        if t.is_file():
                            freed += t.stat().st_size
                            t.unlink()
                            removed += 1
                    except OSError:
                        pass
            log("CLEANUP", "캐시 정리: " + str(removed) + "개 항목, 약 "
                + str(freed // 1024) + " KB 회수")
        except Exception as e:
            log("WARN", "캐시 정리 예외: " + str(e))

    register_cleanup(_do)
    log("INFO", "캐시 정리 cleanup 등록됨")
# <<< CACHE_CLEANUP_v1
