"""handlers — 메뉴 항목 액션 구현.

각 핸들러는 ENV(설치 폴더) 경로를 받아 해당 도구를 실행한다.
샌드박스 에이전트는 checkbox.run() 으로 옵션을 받고 docker run 명령을 조립한다.
"""
from __future__ import annotations

import datetime
import os
import secrets
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import ui, checkbox, searxng_runtime, settings_store, runtime_guard
from .i18n import t, set_language, SUPPORTED_LANGUAGES

# ─── 설정 ───
MODEL_TAG  = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M"
IMAGE_NAME = "llm-agent-sandbox"


# ═══════════════════════════════════════════════════════════════
#  공통 헬퍼
# ═══════════════════════════════════════════════════════════════

def _ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def _ensure_ollama(env: Path) -> bool:
    """Ollama가 안 켜져 있으면 백그라운드로 시작.

    개선:
      - logs 폴더가 없으면 자동 생성 (FileNotFoundError 방지)
      - 폴링 15초 -> 30초 (콜드 스타트 여유)
      - 로그 파일 핸들을 Popen 에 넘긴 직후 호스트 측은 닫아 fd 누수 방지
    """
    if _ollama_running():
        return True

    ui.info("Ollama가 응답 없음 — 백그라운드 시작 시도…")
    exe = env / "ollama_runtime" / "ollama.exe"
    if not exe.exists():
        ui.err(f"Ollama 미설치: {exe}")
        ui.err("install.py를 다시 실행하세요")
        return False

    log = env / "logs" / "ollama_run.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    new_env = os.environ.copy()
    new_env["OLLAMA_MODELS"] = str(env / "llm_models")
    new_env["OLLAMA_HOST"]   = "127.0.0.1:11434"

    CREATE_NO_WINDOW = 0x08000000

    # 자식 프로세스에 stdout/stderr 를 넘긴 뒤 호스트 핸들은 즉시 닫는다.
    # (자식은 fd 를 상속받아 그대로 쓸 수 있다.)
    f = open(log, "ab")
    try:
        subprocess.Popen(
            [str(exe), "serve"],
            stdout=f, stderr=f,
            env=new_env,
            creationflags=CREATE_NO_WINDOW,
        )
    finally:
        f.close()

    for _ in range(30):
        if _ollama_running():
            ui.ok("Ollama 가동 확인")
            return True
        time.sleep(1)

    ui.err("Ollama 시작 실패 — 로그 확인: " + str(log))
    return False


def _check_docker_image() -> bool:
    try:
        subprocess.run(
            ["docker", "image", "inspect", IMAGE_NAME],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return False


# ═══════════════════════════════════════════════════════════════
#  [1] 채팅 UI
# ═══════════════════════════════════════════════════════════════

def _chat_log_write(log_path: Path, level: str, msg: str) -> None:
    """채팅 세션 디버그 로그 한 줄 추가. 파일 I/O 실패는 본 동작을 망치지 않는다."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] [{level:5}] {msg}\n")
    except OSError:
        pass


def start_chat(env: Path):
    ui.header(t("chat.title"))

    # ─── 세션 로그 파일 준비 ───
    log_path = env / "logs" / "chat_ui.log"

    def _log(level: str, msg: str) -> None:
        _chat_log_write(log_path, level, msg)

    _log("INFO", "=" * 60)
    _log("INFO", "Chat UI session start")
    _log("INFO", f"env={env}")

    if not _ensure_ollama(env):
        _log("FAIL", "Ollama not available")
        ui.info(f"세션 로그: {log_path}")
        ui.pause()
        return
    _log("INFO", "Ollama ready")

    rt_params = runtime_guard.compute_runtime_params()
    _log("INFO", f"runtime params: {rt_params}")

    # ─── Open WebUI 진입점 결정 ───────────────────────────────────
    # `python -m open_webui` 는 패키지에 __main__.py 가 없어 동작하지 않는다.
    # 정석은 pip 가 등록한 콘솔 스크립트 (Scripts/open-webui.exe).
    # 만약 어떤 이유로 그 스크립트가 없으면 venv 의 python 으로 uvicorn 직접 호출
    # (open_webui.main:app FastAPI 인스턴스) 로 폴백한다.
    scripts_dir = env / "chat_ui" / "venv" / "Scripts"
    webui_exe = scripts_dir / "open-webui.exe"
    venv_py   = scripts_dir / "python.exe"

    if webui_exe.exists():
        argv = [str(webui_exe), "serve"]
        _log("INFO", f"primary launcher: {webui_exe}")
    elif venv_py.exists():
        argv = [
            str(venv_py), "-m", "uvicorn", "open_webui.main:app",
            "--host", "0.0.0.0", "--port", "8080",
        ]
        _log("WARN", f"open-webui.exe missing, falling back to uvicorn: {venv_py}")
        ui.warn("open-webui.exe 없음 — uvicorn 직접 호출로 폴백")
    else:
        _log("FAIL", f"no launcher: webui_exe={webui_exe}, venv_py={venv_py}")
        ui.err(t("chat.webui_missing", path=str(webui_exe)))
        ui.warn(t("chat.run_install_again"))
        ui.info(f"세션 로그: {log_path}")
        ui.pause()
        return

    # ─── SearXNG 자동 시작 ────────────────────────────────────────
    search_enabled = False
    if searxng_runtime.image_exists():
        _log("INFO", "SearXNG image present, attempting start")
        ui.info(t("chat.searxng_starting"))
        if searxng_runtime.start(env, log_path=log_path):
            search_enabled = True
            _log("INFO", "SearXNG started")
        else:
            _log("WARN", "SearXNG start failed (see entries above for details)")
            ui.warn(t("chat.searxng_failed"))
    else:
        _log("INFO", "SearXNG image not present — skipping")
        ui.warn(t("chat.searxng_not_installed"))
        ui.info(t("chat.searxng_install_hint"))

    # ─── 환경변수 구성 ────────────────────────────────────────────
    new_env = os.environ.copy()
    new_env["OLLAMA_MODELS"]   = str(env / "llm_models")
    new_env["OLLAMA_BASE_URL"] = "http://localhost:11434"
    new_env["DEFAULT_MODELS"]  = MODEL_TAG

    runtime_guard.apply_to_env(rt_params, new_env)

    if search_enabled:
        new_env["ENABLE_RAG_WEB_SEARCH"]  = "true"
        new_env["RAG_WEB_SEARCH_ENGINE"]  = "searxng"
        new_env["SEARXNG_QUERY_URL"]      = (
            f"{searxng_runtime.URL}/search?q=<query>&format=json"
        )
        new_env["RAG_WEB_SEARCH_RESULT_COUNT"]      = "5"
        new_env["RAG_WEB_SEARCH_CONCURRENT_REQUESTS"] = "5"
        ui.ok(t("chat.searxng_connected", url=searxng_runtime.URL))

    extra_keys = [
        "OLLAMA_MODELS", "OLLAMA_BASE_URL", "DEFAULT_MODELS",
        "ENABLE_RAG_WEB_SEARCH", "RAG_WEB_SEARCH_ENGINE",
        "SEARXNG_QUERY_URL", "RAG_WEB_SEARCH_RESULT_COUNT",
        "RAG_WEB_SEARCH_CONCURRENT_REQUESTS",
    ]
    set_keys = [k for k in extra_keys if k in new_env]
    _log("INFO", f"env additions: {set_keys}")

    print()
    ui.info(t("chat.browser_url"))
    if search_enabled:
        ui.info(t("chat.search_usage"))
    ui.info(t("chat.exit_hint"))
    ui.info(f"세션 로그: {log_path}")
    print()

    # ─── Open WebUI 프로세스 + 자원 워치독 ───────────────────────
    proc_holder = {"proc": None}
    kill_timer_holder = {"timer": None}

    def _on_danger(reason: str):
        _log("WARN", f"watchdog triggered: {reason}")
        p = proc_holder["proc"]
        if p and p.poll() is None:
            try:
                p.terminate()
                t = threading.Timer(
                    5.0,
                    lambda: p.kill() if p.poll() is None else None,
                )
                t.daemon = True
                t.start()
                kill_timer_holder["timer"] = t
            except Exception as e:
                _log("FAIL", f"terminate failed: {e}")

    def _watchdog_log(m: str) -> None:
        print(m, flush=True)
        _log("WARN", f"[watchdog] {m.strip()}")

    watchdog = runtime_guard.ResourceWatchdog(
        stop_callback=_on_danger,
        log_func=_watchdog_log,
    )
    watchdog.start()

    _log("INFO", f"launching: {argv}")

    # ─── 마지막 안내: 브라우저 URL 한 번 더 강조 ──────────────────
    # Open WebUI 가 시작되면 uvicorn / fastapi 로그가 콘솔에 쏟아지므로,
    # 사용자가 스크롤하지 않고도 접속 주소를 볼 수 있도록 직전에 한 번 더 표시.
    print()
    print(ui.C.BD + ui.C.G + "=" * 60 + ui.C.E)
    print(ui.C.BD + ui.C.G + "  ▶  브라우저에서 접속:  http://localhost:8080" + ui.C.E)
    print(ui.C.BD + ui.C.G + "=" * 60 + ui.C.E)
    print()

    try:
        proc = subprocess.Popen(argv, env=new_env)
        proc_holder["proc"] = proc
        _log("INFO", f"open-webui started (pid={proc.pid})")
        rc = proc.wait()
        _log("INFO", f"open-webui exited (rc={rc})")
        if rc != 0:
            ui.warn(f"Open WebUI 비정상 종료: 코드={rc}")
            ui.info(f"자세한 로그: {log_path}")
    except KeyboardInterrupt:
        _log("INFO", "KeyboardInterrupt — terminating")
        if proc_holder["proc"]:
            proc_holder["proc"].terminate()
    except FileNotFoundError as e:
        _log("FAIL", f"FileNotFoundError: {e}")
        ui.err(f"실행 파일을 찾을 수 없습니다: {e}")
        ui.info(f"자세한 로그: {log_path}")
    except OSError as e:
        _log("FAIL", f"OSError: {e}")
        ui.err(f"OS 오류: {e}")
        ui.info(f"자세한 로그: {log_path}")
    except Exception as e:
        _log("FAIL", f"unexpected {type(e).__name__}: {e}")
        _log("FAIL", "traceback:\n" + traceback.format_exc())
        ui.err(f"예상치 못한 오류: {type(e).__name__}: {e}")
        ui.info(f"자세한 로그: {log_path}")
    finally:
        # kill timer 정리 — 좀비 타이머 방지
        kt = kill_timer_holder["timer"]
        if kt is not None:
            kt.cancel()
        watchdog.stop()
        _log("INFO", "session end")

    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [2] 샌드박스 에이전트 (체크박스 옵션 메뉴)
# ═══════════════════════════════════════════════════════════════

def _ask_workspace(default: Path, last_used: Optional[str] = None) -> Path | None:
    """마운트할 폴더 입력 받기. None이면 취소."""
    suggested = default
    if last_used:
        last_path = Path(last_used)
        if last_path.exists():
            suggested = last_path

    ui.header(t("agent.workspace_title"))

    print(f"  {ui.C.DIM}{t('agent.workspace_desc1')}{ui.C.E}")
    print(f"  {ui.C.DIM}{t('agent.workspace_desc2')}{ui.C.E}")
    print()

    if last_used and Path(last_used).exists() and suggested != default:
        print(f"  {ui.C.G}{t('agent.workspace_last', path=str(suggested))}{ui.C.E}")
        print(f"  {ui.C.DIM}{t('agent.workspace_default', path=str(default))}{ui.C.E}")
    else:
        print(f"  {ui.C.B}{t('agent.workspace_default', path=str(suggested))}{ui.C.E}")

    print()
    print(f"  {ui.C.DIM}{t('agent.workspace_enter')}{ui.C.E}")
    print(f"  {ui.C.DIM}{t('agent.workspace_input')}{ui.C.E}")
    print(f"  {ui.C.DIM}{t('agent.workspace_back')}{ui.C.E}")
    print()

    response = ui.prompt("> ").strip()
    if response.lower() in ("b", "back", "q"):
        return None
    if not response:
        suggested.mkdir(parents=True, exist_ok=True)
        return suggested

    custom = Path(response).expanduser().resolve()
    if not custom.exists():
        ui.err(t("agent.workspace_not_exist", path=str(custom)))
        ui.pause()
        return _ask_workspace(default, last_used)
    return custom


def _build_sandbox_options() -> list:
    """샌드박스 옵션 정의. CPU/메모리 한도는 시스템 사양에 따라 자동 조정."""
    try:
        from installer.resources import detect, compute_safety_profile
        from pathlib import Path as _P
        spec = detect(_P("."))
        profile = compute_safety_profile(spec)
        cpu_label = t("opt.cpu_limit", cpus=profile.container_cpus)
        mem_label = t("opt.memory_limit", mem=profile.container_memory.upper())
    except Exception:
        cpu_label = t("opt.cpu_limit", cpus="2")
        mem_label = t("opt.memory_limit", mem="4G")

    return [
        checkbox.Option(
            id="isolation",
            label=t("opt.isolation"),
            default=True, locked=True, risk=checkbox.SAFE,
            description=t("opt.isolation_desc"),
        ),
        checkbox.Option(
            id="block_internet",
            label=t("opt.block_internet"),
            default=True, risk=checkbox.SAFE,
            description=t("opt.block_internet_desc"),
            excludes=["allow_internet"],
        ),
        checkbox.Option(
            id="cpu_limit",
            label=cpu_label,
            default=True, risk=checkbox.SAFE,
            description=t("opt.cpu_limit_desc"),
            excludes=["no_resource_limit"],
        ),
        checkbox.Option(
            id="memory_limit",
            label=mem_label,
            default=True, risk=checkbox.SAFE,
            description=t("opt.memory_limit_desc"),
            excludes=["no_resource_limit"],
        ),
        checkbox.Option(
            id="auto_run",
            label=t("opt.auto_run"),
            default=True, risk=checkbox.SAFE,
            description=f"{t('opt.auto_run_desc1')}\n{t('opt.auto_run_desc2')}",
        ),
        checkbox.Option(
            id="allow_internet",
            label=t("opt.allow_internet"),
            default=False, risk=checkbox.MEDIUM,
            description=(f"{t('opt.allow_internet_desc1')}\n"
                         f"{t('opt.allow_internet_desc2')}\n"
                         f"{t('opt.allow_internet_desc3')}"),
            excludes=["block_internet"],
        ),
        checkbox.Option(
            id="no_resource_limit",
            label=t("opt.no_resource_limit"),
            default=False, risk=checkbox.MEDIUM,
            description=(f"{t('opt.no_resource_limit_desc1')}\n"
                         f"{t('opt.no_resource_limit_desc2')}"),
            excludes=["cpu_limit", "memory_limit"],
        ),
        checkbox.Option(
            id="privileged",
            label=t("opt.privileged"),
            default=False, risk=checkbox.HIGH,
            description=(f"{t('opt.privileged_desc1')}\n"
                         f"{t('opt.privileged_desc2')}\n"
                         f"{t('opt.privileged_desc3')}"),
        ),
    ]


def start_agent_sandbox(env: Path):
    cfg = settings_store.load()

    if not _check_docker_image():
        ui.header(t("sandbox.image_missing_title"))
        ui.err(t("sandbox.image_missing", name=IMAGE_NAME))
        ui.warn(t("sandbox.build_hint"))
        ui.pause()
        return

    default_ws = env / "agent" / "workspace"
    workspace = _ask_workspace(default_ws, last_used=cfg.last_workspace)
    if workspace is None:
        return

    settings_store.update_last_workspace(cfg, workspace)

    if not _ensure_ollama(env):
        ui.pause()
        return

    rt_params = runtime_guard.compute_runtime_params()

    options = _build_sandbox_options()
    safe_ids = {o.id for o in options if o.risk == checkbox.SAFE}
    saved_defaults = settings_store.get_sandbox_defaults(cfg, safe_ids)

    extra = [
        t("sandbox.mount_label", path=str(workspace)),
        t("sandbox.mount_target"),
        "",
        f"{ui.C.DIM}{t('sandbox.options_help_safe')}{ui.C.E}",
        f"{ui.C.DIM}{t('sandbox.options_help_dangerous')}{ui.C.E}",
    ]

    selected = checkbox.run(
        title=t("sandbox.options_title"),
        subtitle=t("sandbox.options_subtitle"),
        options=options,
        extra_lines=extra,
        override_defaults=saved_defaults,
    )
    if selected is None:
        return

    settings_store.update_sandbox_options(cfg, selected)
    settings_store.update_last_model_tag(cfg, MODEL_TAG)
    settings_store.save(cfg)

    # 시스템 사양 기반 자원 한도 산출
    try:
        from installer.resources import detect, compute_safety_profile
        spec = detect(env)
        profile = compute_safety_profile(spec)
        run_mem = profile.container_memory
        run_cpus = profile.container_cpus
    except Exception:
        run_mem = "4g"
        run_cpus = "2"

    container_name = f"llm_agent_{secrets.token_hex(4)}"

    cmd = [
        "docker", "run", "--rm", "-it",
        "--name", container_name,
        "-v", f"{workspace}:/home/agent/workspace",
        "--add-host=host.docker.internal:host-gateway",
    ]

    if "block_internet" in selected:
        cmd += ["--dns=0.0.0.0"]
    if "cpu_limit" in selected:
        cmd += [f"--cpus={run_cpus}"]
    if "memory_limit" in selected:
        cmd += [f"--memory={run_mem}"]
    if "privileged" in selected:
        cmd += ["--privileged"]

    cmd += [
        IMAGE_NAME, "interpreter",
        "--model",     f"ollama/{MODEL_TAG}",
        "--api_base",  "http://host.docker.internal:11434",
        "--context_window", str(rt_params.context_window),
    ]
    if "auto_run" in selected:
        cmd += ["--auto_run"]

    ui.header(t("sandbox.start_title"))
    print(f"  {ui.C.DIM}{t('sandbox.final_command')}{ui.C.E}")
    parts = " ".join(cmd).replace(" --", " \\\n      --")
    print(f"\n  {parts}\n")
    ui.info(t("sandbox.exit_hint"))
    print()

    def _on_danger(reason: str):
        try:
            subprocess.run(
                ["docker", "stop", "-t", "5", container_name],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    watchdog = runtime_guard.ResourceWatchdog(
        stop_callback=_on_danger,
        log_func=lambda m: print(m, flush=True),
    )
    watchdog.start()

    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass
    finally:
        watchdog.stop()

    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [3] 호스트 직접 모드
# ═══════════════════════════════════════════════════════════════

def start_agent_direct(env: Path):
    ui.clear()

    print(ui.C.R + ui.C.BD + "=" * 60 + ui.C.E)
    print(ui.C.R + ui.C.BD + "  !! " + t("agent.direct_title_warn") + " !!" + ui.C.E)
    print(ui.C.R + ui.C.BD + "=" * 60 + ui.C.E)
    print()
    print(t("agent.direct_intro"))
    print()
    print(f"  {ui.C.R}{t('agent.direct_risks')}{ui.C.E}")
    print(f"    {t('agent.direct_risk1')}")
    print(f"    {t('agent.direct_risk2')}")
    print(f"    {t('agent.direct_risk3')}")
    print(f"    {t('agent.direct_risk4')}")
    print()
    print(f"  {ui.C.G}{t('agent.direct_alternative')}{ui.C.E}")
    print()
    print(t("agent.direct_confirm_prompt", kw="I-UNDERSTAND-THE-RISK"))
    print(f"({ui.C.DIM}{t('agent.direct_confirm_strict')}{ui.C.E})")
    print()

    response = ui.prompt("> ")
    if response != "I-UNDERSTAND-THE-RISK":
        ui.info(t("agent.direct_cancelled"))
        ui.pause()
        return

    if not _ensure_ollama(env):
        ui.pause()
        return

    rt_params = runtime_guard.compute_runtime_params()

    venv_py = env / "agent" / "venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        ui.err(t("agent.direct_interpreter_missing", path=str(venv_py)))
        ui.pause()
        return

    cmd = [
        str(venv_py), "-m", "interpreter",
        "--model",     f"ollama/{MODEL_TAG}",
        "--api_base",  "http://localhost:11434",
        "--context_window", str(rt_params.context_window),
    ]

    ui.warn(t("agent.direct_starting"))
    print()

    proc_holder = {"proc": None}

    def _on_danger(reason: str):
        p = proc_holder["proc"]
        if p and p.poll() is None:
            try:
                p.terminate()
                threading.Timer(3.0, lambda: p.kill() if p.poll() is None else None).start()
            except Exception:
                pass

    watchdog = runtime_guard.ResourceWatchdog(
        stop_callback=_on_danger,
        log_func=lambda m: print(m, flush=True),
    )
    watchdog.start()

    try:
        proc = subprocess.Popen(cmd)
        proc_holder["proc"] = proc
        proc.wait()
    except KeyboardInterrupt:
        if proc_holder["proc"]:
            proc_holder["proc"].terminate()
    finally:
        watchdog.stop()

    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [4] Ollama
# ═══════════════════════════════════════════════════════════════

def start_ollama(env: Path):
    ui.header(t("ollama.title"))
    if _ollama_running():
        ui.ok(t("ollama.running"))
    else:
        ui.info(t("ollama.starting"))
        if _ensure_ollama(env):
            ui.ok(t("ollama.start_ok"))
        else:
            ui.err(t("ollama.start_fail"))
    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [5] 모델 정보
# ═══════════════════════════════════════════════════════════════

def show_model_info(env: Path):
    ui.header(t("model_info.title"))

    if not _ensure_ollama(env):
        ui.pause()
        return

    exe = env / "ollama_runtime" / "ollama.exe"
    new_env = os.environ.copy()
    new_env["OLLAMA_MODELS"] = str(env / "llm_models")

    try:
        subprocess.run([str(exe), "list"], env=new_env, check=False)
    except Exception as e:
        ui.err(str(e))

    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [6] Docker 이미지 빌드
# ═══════════════════════════════════════════════════════════════

def rebuild_sandbox_image(env: Path):
    ui.header(t("build.title"))

    sandbox_dir = env / "agent" / "sandbox"
    if not (sandbox_dir / "Dockerfile").exists():
        ui.err(t("build.dockerfile_missing", path=str(sandbox_dir / 'Dockerfile')))
        ui.warn(t("build.run_install_again"))
        ui.pause()
        return

    try:
        subprocess.run(["docker", "info"], capture_output=True,
                       check=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        ui.err(t("build.daemon_not_running"))
        ui.warn(t("build.start_docker_first"))
        ui.pause()
        return

    ui.warn(t("build.starting"))
    print()

    try:
        subprocess.run(
            ["docker", "build", "-t", IMAGE_NAME, str(sandbox_dir)],
            check=True,
        )
        ui.ok(t("build.complete", name=IMAGE_NAME))
    except subprocess.CalledProcessError:
        ui.err(t("build.failed"))

    ui.pause()


# ═══════════════════════════════════════════════════════════════
#  [7] SearXNG
# ═══════════════════════════════════════════════════════════════

def manage_searxng(env: Path):
    while True:
        ui.header(t("searxng.title"))

        if not searxng_runtime.image_exists():
            print(f"  {ui.C.R}{t('searxng.image_missing')}{ui.C.E}")
            print(f"  {ui.C.DIM}{t('searxng.image_missing_hint')}{ui.C.E}")
            ui.pause()
            return

        running = searxng_runtime.is_running()
        if running:
            print(f"  {ui.C.G}{t('searxng.status_running', url=searxng_runtime.URL)}{ui.C.E}")
        else:
            print(f"  {ui.C.Y}{t('searxng.status_stopped')}{ui.C.E}")

        cfg_path = env / "searxng" / "config" / "settings.yml"
        print(f"  {t('searxng.config_label', path=str(cfg_path))}")
        print(f"  {t('searxng.port_label', port=searxng_runtime.HOST_PORT)}")
        print()
        ui.hr(color=ui.C.DIM)
        print()

        if running:
            print(f"  {ui.C.BD}[1]{ui.C.E} {t('searxng.opt_stop')}")
            print(f"  {ui.C.BD}[2]{ui.C.E} {t('searxng.opt_open_browser')}")
        else:
            print(f"  {ui.C.BD}[1]{ui.C.E} {t('searxng.opt_start')}")
        print(f"  {ui.C.BD}[3]{ui.C.E} {t('searxng.opt_recreate')}")
        print(f"  {ui.C.BD}[4]{ui.C.E} {t('searxng.opt_show_settings')}")
        print(f"  {ui.C.BD}[5]{ui.C.E} 컨테이너 로그 보기 (마지막 50줄)")
        print()
        print(f"  {ui.C.BD}[B]{ui.C.E} {t('common.back')}")
        print()

        choice = ui.prompt("> ").lower()

        if choice == "1":
            if running:
                searxng_runtime.stop()
            else:
                searxng_runtime.start(env)
            ui.pause()
        elif choice == "2" and running:
            import webbrowser
            webbrowser.open(searxng_runtime.URL)
        elif choice == "3":
            searxng_runtime.remove()
            ui.info(t("searxng.recreating"))
            searxng_runtime.start(env)
            ui.pause()
        elif choice == "4":
            print()
            ui.info(t("searxng.settings_file", path=str(cfg_path)))
            ui.info(t("searxng.settings_main_keys"))
            print(t("searxng.settings_safesearch"))
            print(t("searxng.settings_engines"))
            ui.warn(t("searxng.settings_recreate_hint"))
            ui.pause()
        elif choice == "5":
            if not searxng_runtime.container_exists():
                ui.warn("SearXNG 컨테이너가 아직 생성되지 않았습니다.")
            else:
                logs = searxng_runtime.fetch_container_logs(tail=50)
                print()
                ui.info("--- 컨테이너 로그 (마지막 50줄) ---")
                if logs.strip():
                    for line in logs.splitlines():
                        print(f"  {line}")
                else:
                    ui.warn("(로그 비어있음)")
                print()
            ui.pause()
        elif choice in ("b", "back", "q"):
            return


# ═══════════════════════════════════════════════════════════════
#  [8] 설정 관리
# ═══════════════════════════════════════════════════════════════

def manage_settings(env: Path):
    while True:
        cfg = settings_store.load()
        cfg_path = settings_store.file_location()

        ui.header(t("settings.title"))

        print(f"  {t('settings.file_label', path=str(cfg_path))}")
        if cfg_path.exists():
            size = cfg_path.stat().st_size
            print(f"  {ui.C.G}{t('settings.status_exists', size=size)}{ui.C.E}")
        else:
            print(f"  {ui.C.Y}{t('settings.status_missing')}{ui.C.E}")
        print()
        ui.hr(color=ui.C.DIM)
        print()

        none_str = t("settings.none")
        print(f"  {ui.C.BD}{t('settings.current_values')}{ui.C.E}")
        print(t("settings.last_workspace", value=cfg.last_workspace or none_str))
        print(t("settings.last_choice", value=cfg.last_menu_choice or none_str))
        print(t("settings.last_model", value=cfg.last_model_tag or none_str))
        print(t("settings.lang_current", lang=cfg.language or "auto"))
        print(t("settings.saved_safe_options"))
        if cfg.sandbox_safe_options:
            for oid in cfg.sandbox_safe_options:
                print(f"      - {oid}")
        else:
            print(f"      {none_str}")
        print()
        print(f"  {ui.C.DIM}{t('settings.dangerous_note')}{ui.C.E}")
        print()
        ui.hr(color=ui.C.DIM)
        print()
        print(f"  {ui.C.BD}[1]{ui.C.E} {t('settings.opt_show_raw')}")
        print(f"  {ui.C.BD}[2]{ui.C.E} {t('settings.opt_reset_workspace')}")
        print(f"  {ui.C.BD}[3]{ui.C.E} {t('settings.opt_change_lang')}")
        print(f"  {ui.C.BD}[4]{ui.C.E} {t('settings.opt_reset_all')} {ui.C.Y}!{ui.C.E}")
        print()
        print(f"  {ui.C.BD}[B]{ui.C.E} {t('common.back')}")
        print()

        choice = ui.prompt("> ").lower()

        if choice == "1":
            if cfg_path.exists():
                print()
                print(cfg_path.read_text(encoding="utf-8"))
                ui.pause()
            else:
                ui.warn(t("settings.no_file_yet"))
                ui.pause()

        elif choice == "2":
            cfg.last_workspace = None
            settings_store.save(cfg)
            ui.ok(t("settings.workspace_reset_ok"))
            ui.pause()

        elif choice == "3":
            _change_language_menu(cfg)

        elif choice == "4":
            print()
            print(f"  {ui.C.Y}{t('settings.reset_warn')}{ui.C.E}")
            print(f"  {t('settings.reset_confirm')}")
            response = ui.prompt("  > ")
            if response == "RESET":
                settings_store.reset()
                ui.ok(t("settings.reset_done"))
            else:
                ui.info(t("settings.reset_cancelled"))
            ui.pause()

        elif choice in ("b", "back", "q"):
            return


def _change_language_menu(cfg):
    """언어 변경 서브메뉴."""
    ui.header(t("settings.opt_change_lang"))
    print()
    print(f"  [1] English")
    print(f"  [2] 한국어 (Korean)")
    print()
    print(f"  [B] {t('common.back')}")
    print()
    choice = ui.prompt("> ").lower()
    new_lang = None
    if choice == "1":
        new_lang = "en"
    elif choice == "2":
        new_lang = "ko"
    else:
        return

    set_language(new_lang)
    settings_store.update_language(cfg, new_lang)
    settings_store.save(cfg)
    ui.ok(t("lang.saved", lang={"en": "English", "ko": "한국어"}[new_lang]))
    ui.pause()
