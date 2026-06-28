"""actions.agent_sandbox — [2] 자동화 에이전트 (Docker 샌드박스).

Presenter.show_checkbox 호출 한 번으로 옵션을 받고 docker run 조립.
"""
# v6_7_final: 사용자 가시성 강화 적용됨
from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path
from typing import List

from .. import config
from ..presenter.base import Presenter
from ..services.docker import DockerService
from ..services.ollama import OllamaService
from ._sandbox_options import build_sandbox_options


def _resolve_resource_limits(env: Path) -> tuple[str, str]:
    """시스템 사양 기반 (memory, cpus) 라벨 결정.

    실패 시 안전한 기본값 사용.
    """
    try:
        from installer.resources import detect, compute_safety_profile
        spec = detect(env)
        profile = compute_safety_profile(spec)
        return profile.container_memory, profile.container_cpus
    except Exception:
        return config.DEFAULT_CONTAINER_MEM, config.DEFAULT_CONTAINER_CPUS


def _ask_workspace(p: Presenter, env: Path) -> Path | None:
    """마운트할 폴더 선택."""
    default = env / "agent" / "workspace"

    # settings_store 에서 마지막 사용 경로 조회 (선택)
    last_used = None
    try:
        from .. import settings_store
        cfg = settings_store.load()
        if cfg.last_workspace:
            lp = Path(cfg.last_workspace)
            if lp.exists():
                last_used = lp
    except Exception:
        pass

    return p.prompt_path(
        title="샌드박스 에이전트 — 작업 폴더 선택",
        default=default,
        last_used=last_used,
        must_exist=False,
    )


def _build_command(
    selected: set, container_name: str,
    workspace: Path, run_mem: str, run_cpus: str,
    context_window: int = 4096,
) -> List[str]:
    """docker run 명령 조립."""
    cmd = [
        "docker", "run", "--rm", "-it",
        "--name", container_name,
        "-v", f"{workspace}:{config.SANDBOX_WORKSPACE_MOUNT}",
        "--add-host=host.docker.internal:host-gateway",
        # ErrorGuard: 화면캡처/GUI 자동화 비활성 (no_vision 안전장치)
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",
        # v6_8_runtime: Python stdout 즉시 flush (콘솔 응답 가시성)
        "-e", "PYTHONUNBUFFERED=1",
        # v6_8_runtime: LiteLLM 광고 메시지 억제
        "-e", "LITELLM_LOG=ERROR",
        # v6_9_visibility: 추가 ANSI/색상 제거
        "-e", "FORCE_COLOR=0",
        "-e", "NO_COLOR=1",
        "-e", "TERM=dumb",
    ]

    # FOLDER_POLICY_v1: 상시 허용 폴더 마운트 (샌드박스는 그 외 경로 물리 차단)
    try:
        from .. import folder_policy as _fp
        for _h, _c in _fp.mounts_for():
            cmd += ["-v", _h + ":" + _c]
    except Exception:
        pass

    if "block_internet" in selected:
        cmd += ["--dns=0.0.0.0"]
    if "cpu_limit" in selected:
        cmd += [f"--cpus={run_cpus}"]
    if "memory_limit" in selected:
        cmd += [f"--memory={run_mem}"]
    if "privileged" in selected:
        cmd += ["--privileged"]

    # ErrorGuard: vision/GUI 자동화 시도 차단 + 한국어 응답 강제
    _safety_msg = (
        "당신은 격리된 Docker 컨테이너 안의 자율 코딩 에이전트입니다. "
        "사용자에게는 반드시 한국어로 응답하세요 (코드는 영어 그대로 OK).\n"
        "절대 규칙:\n"
        "1) 디스플레이가 없습니다. computer.display/mouse/keyboard/screen, "
        "pyautogui, pynput, PIL.ImageGrab, mss, screenshot 등은 모두 실패합니다. "
        "사용 시도 자체를 하지 마세요. computer 모듈을 쓸 필요 없습니다 — "
        "표준 Python 과 쉘 명령으로 모든 작업이 가능합니다.\n"
        "2) 같은 코드가 같은 에러로 두 번 실패하면 즉시 중단하고 사용자에게 한국어로 보고하세요. "
        "NameError, ImportError 가 나면 그 함수/모듈이 없는 것이니 재시도 금지.\n"
        "3) 작업 디렉터리는 /home/agent/workspace 입니다.\n"
        "4) 사용자가 화면/GUI 작업을 요청하면 한국어로 거절하고 대안을 제시하세요."
    )

    # 응답 행동 규칙 + 세션 정보 합성 (profiles 와 동일 패턴)
    from .. import profiles as _profiles
    _safety_msg = (
        _safety_msg
        + _profiles.RESPONSE_DISCIPLINE
        + _profiles.build_session_addendum(workspace)
    )

    # v5_runaway: stdout 즉시 flush + LiteLLM 광고 메시지 억제
    cmd += ["-e", "PYTHONUNBUFFERED=1", "-e", "LITELLM_LOG=ERROR"]

    cmd += [
        config.SANDBOX_IMAGE, "interpreter",
        "--model", f"ollama/{config.MODEL_TAG}",
        "--api_base",
        f"http://host.docker.internal:{config.OLLAMA_PORT}",
        "--context_window", str(context_window),
        # v6_8_runtime: 응답 길이 제한 (무한 생성 방지)
        "--max_tokens", "512",
        # v6_9_visibility: 응답 가시성 강화
        "--verbose",  # 응답 진행 상황 표시

        "--system_message", _safety_msg,
    ]
    if "auto_run" in selected:
        cmd += ["--auto_run"]
    return cmd


# v6_6_sandbox: 샌드박스 액션 단계별 trace
def _v66_trace(stage: str) -> None:
    try:
        from .. import lifelog as _ll
        _ll.log("TRACE", "[agent_sandbox] " + stage)
    except Exception:
        pass


def run(env: Path, p: Presenter) -> None:
    """샌드박스 에이전트 시작."""
    _v66_trace("run() 진입")
    p.section("자동화 에이전트 — 샌드박스")

    # ── 사전 검사: Docker 자동 시작 ──
    cancel_check = getattr(p, "is_cancelled", lambda: False)
    if not DockerService.ensure_daemon(
        logger=p, timeout=60, cancel_check=cancel_check,
    ):
        _v66_trace("p.pause() 직전 (★사용자 클릭 대기 — 여기서 멈추면 정상)")
        p.pause()
        return

    if not DockerService.image_exists(config.SANDBOX_IMAGE):
        p.error(f"이미지가 없습니다: {config.SANDBOX_IMAGE}")
        p.warn("[6] Docker 이미지 빌드 메뉴를 먼저 실행하세요")
        _v66_trace("p.pause() 직전 (★사용자 클릭 대기 — 여기서 멈추면 정상)")
        p.pause()
        return

    if not OllamaService(env, logger=p).ensure_running():
        _v66_trace("p.pause() 직전 (★사용자 클릭 대기 — 여기서 멈추면 정상)")
        p.pause()
        return

    # ── 워크스페이스 ──
    _v66_trace("폴더 선택 다이얼로그 직전")
    workspace = _ask_workspace(p, env)
    _v66_trace("폴더 선택 완료: " + str(workspace))
    if workspace is None:
        return
    workspace.mkdir(parents=True, exist_ok=True)

    # ── 옵션 선택 ──
    run_mem, run_cpus = _resolve_resource_limits(env)
    cpu_label = f"CPU 제한 ({run_cpus}코어)"
    mem_label = f"메모리 제한 ({run_mem.upper()})"
    options = build_sandbox_options(cpu_label, mem_label)

    # 저장된 안전 옵션 기본값 복원
    safe_ids = {o.id for o in options if o.risk == 0}
    saved = None
    try:
        from .. import settings_store
        cfg = settings_store.load()
        saved = settings_store.get_sandbox_defaults(cfg, safe_ids)
    except Exception:
        saved = safe_ids

    extra = [
        f"마운트: {workspace}",
        f"        → {config.SANDBOX_WORKSPACE_MOUNT}",
        "",
        "안전 옵션은 저장된 값으로 복원됩니다 (✓).",
        "위험 옵션(⚠/⚠⚠)은 항상 해제 상태로 시작 — 매번 명시적 활성화 필요.",
    ]

    _v66_trace("옵션 체크박스 다이얼로그 직전")

    selected = p.show_checkbox(
        title="샌드박스 에이전트 — 옵션 설정",
        subtitle="체크박스 토글 후 [실행] 으로 진행",
        options=options,
        extra_lines=extra,
        override_defaults=saved,
    )
    if selected is None:
        return

    # ── 저장 ──
    try:
        from .. import settings_store
        cfg = settings_store.load()
        settings_store.update_sandbox_options(cfg, selected)
        settings_store.update_last_model_tag(cfg, config.MODEL_TAG)
        if workspace != env / "agent" / "workspace":
            cfg.last_workspace = str(workspace)
        settings_store.save(cfg)
    except Exception:
        pass

    # ── 실행 ──
    container_name = f"{config.SANDBOX_CONTAINER_PREFIX}{secrets.token_hex(4)}"

    # 런타임 가드 (선택)
    context_window = 4096
    try:
        from .. import runtime_guard
        rt = runtime_guard.compute_runtime_params()
        context_window = rt.context_window
    except Exception:
        pass

    cmd = _build_command(
        selected, container_name, workspace,
        run_mem, run_cpus, context_window,
    )

    p.section("샌드박스 에이전트 시작")
    p.info("실행할 명령:")
    parts = " ".join(cmd).replace(" --", " \\\n      --")
    for line in parts.splitlines():
        p.info("  " + line)
    p.info("종료: 컨테이너 콘솔에서 Ctrl+C 또는 exit")

    # GUI (pythonw) 환경 감지 — 콘솔 없으면 새 콘솔 띄움
    import sys as _sys
    is_gui_env = (_sys.stdout is None or
                  not getattr(_sys.stdout, 'isatty', lambda: False)())
    popen_kw = {}
    if os.name == "nt" and is_gui_env:
        popen_kw["creationflags"] = config.WIN_CREATE_NEW_CONSOLE

    try:
        # v6_9_visibility: Ollama 모델 사전 warm-up (첫 응답 지연 제거)
        try:
            from .. import lifelog as _ll
            if hasattr(_ll, "warmup_ollama_model"):
                p.info("Ollama 모델을 사전 로드합니다... (수십초 걸릴 수 있음)")
                _ll.warmup_ollama_model(config.MODEL_TAG, timeout=60)
                p.ok("모델 사전 로드 완료 — 첫 응답이 빨라집니다")
        except Exception as _we:
            pass
        _v66_trace("docker subprocess.Popen 직전")
        proc = subprocess.Popen(cmd, **popen_kw)
        if is_gui_env:
            _v66_trace("docker 실행됨 (새 콘솔, PID=" + str(proc.pid) + ") — 즉시 반환 예정")
            p.section("=" * 50)
            p.ok("✓ 에이전트가 별도 콘솔창에서 실행 중입니다")
            p.ok(f"  PID: {proc.pid}")
            p.warn("★ 작업표시줄에서 새로 열린 검정색 콘솔창을 찾으세요!")
            p.warn("   거기서 에이전트와 한국어로 대화하시면 됩니다")
            p.warn("   대화 종료: 콘솔창에서 exit 입력 또는 X 클릭")
            p.section("=" * 50)
            
        else:
            _v66_trace("proc.wait() 직전 (콘솔 모드 — 여기서 블록될 수 있음)")
            proc.wait()
    except FileNotFoundError as e:
        p.error(f"docker 명령을 찾을 수 없습니다: {e}")
    except KeyboardInterrupt:
        pass

    _v66_trace("p.pause() 직전 (★사용자 클릭 대기 — 여기서 멈추면 정상)")

    p.pause()
