"""actions.agent_sandbox — [2] 자동화 에이전트 (Docker 샌드박스).

Presenter.show_checkbox 호출 한 번으로 옵션을 받고 docker run 조립.
"""
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
        config.SANDBOX_IMAGE, "interpreter",
        "--model", f"ollama/{config.MODEL_TAG}",
        "--api_base",
        f"http://host.docker.internal:{config.OLLAMA_PORT}",
        "--context_window", str(context_window),
    ]
    if "auto_run" in selected:
        cmd += ["--auto_run"]
    return cmd


def run(env: Path, p: Presenter) -> None:
    """샌드박스 에이전트 시작."""
    p.section("자동화 에이전트 — 샌드박스")

    # ── 사전 검사: Docker 자동 시작 ──
    cancel_check = getattr(p, "is_cancelled", lambda: False)
    if not DockerService.ensure_daemon(
        logger=p, timeout=60, cancel_check=cancel_check,
    ):
        p.pause()
        return

    if not DockerService.image_exists(config.SANDBOX_IMAGE):
        p.error(f"이미지가 없습니다: {config.SANDBOX_IMAGE}")
        p.warn("[6] Docker 이미지 빌드 메뉴를 먼저 실행하세요")
        p.pause()
        return

    if not OllamaService(env, logger=p).ensure_running():
        p.pause()
        return

    # ── 워크스페이스 ──
    workspace = _ask_workspace(p, env)
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
        proc = subprocess.Popen(cmd, **popen_kw)
        if is_gui_env:
            p.ok(f"새 콘솔창에서 에이전트가 실행 중입니다 (PID={proc.pid})")
            p.info("그 창을 닫거나 exit 명령으로 종료하세요.")
        else:
            proc.wait()
    except FileNotFoundError as e:
        p.error(f"docker 명령을 찾을 수 없습니다: {e}")
    except KeyboardInterrupt:
        pass

    p.pause()
