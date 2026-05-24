"""actions.agent_chat — [9] GUI 통합 대화 모드.

지시사항 [1~4단계] 통합:
  - 프로젝트 프로필 선택 (range_dev/Python/web/Unity/...)
  - subprocess.PIPE 로 docker 안 interpreter 실행
  - 단일 윈도우 내 대화창에서 양방향 상호작용
  - 화면 캡처 시도 자동 차단 (system_message + env + ErrorGuard)
  - [중단] 버튼으로 즉시 종료

GUI 전용 — TUI 에서 호출 시 안내 후 폴백.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .. import config
from ..presenter.base import MenuItem, Presenter
from ..services.docker import DockerService
from ..services.ollama import OllamaService


def _resolve_resource_limits(env: Path) -> tuple[str, str]:
    """시스템 사양 기반 (memory, cpus) 결정."""
    try:
        from installer.resources import detect, compute_safety_profile
        spec = detect(env)
        profile = compute_safety_profile(spec)
        return profile.container_memory, profile.container_cpus
    except Exception:
        return config.DEFAULT_CONTAINER_MEM, config.DEFAULT_CONTAINER_CPUS


def _select_profile(p: Presenter):
    """프로필 선택 — 메뉴 표시."""
    from .. import profiles

    items = [
        MenuItem(
            key=prof.key,
            title=prof.label,
            description=prof.description,
        )
        for prof in profiles.PROFILES
    ]
    items.append(MenuItem(key="b", title="취소", separator_above=True))

    choice = p.show_menu(
        title="프로젝트 프로필 선택",
        subtitle="에이전트의 '전문가 자아' 를 결정합니다",
        items=items,
    )
    if choice in ("b", "q"):
        return None

    return profiles.by_key(choice) or profiles.default()


def _ask_workspace(p: Presenter, env: Path) -> Optional[Path]:
    """마운트할 폴더 선택."""
    default = env / "agent" / "workspace"

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
        title="GUI 통합 대화 — 작업 폴더",
        default=default,
        last_used=last_used,
        must_exist=False,
    )


def _open_folder_in_explorer(folder: Path) -> None:
    """탐색기로 폴더 열기 (Windows/맥/리눅스 호환)."""
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


def _run_gui_chat(env: Path, p: Presenter, profile, workspace: Path) -> None:
    """GUI 통합 대화창 실행. TkPresenter 전용."""
    from ..agent_runner import (
        UnifiedAgent,
        AgentMessage,
        build_sandbox_pipe_cmd,
        LEVEL_TERMINATED,
    )
    from ..presenter.gui.chat_panel import ChatPanel

    # ── 자원 한도 ──
    run_mem, run_cpus = _resolve_resource_limits(env)

    # ── 컨테이너 이름 ──
    container = f"{config.SANDBOX_CONTAINER_PREFIX}chat_{secrets.token_hex(4)}"

    # ── 컨텍스트 윈도 ──
    context_window = 4096
    try:
        from .. import runtime_guard
        rt = runtime_guard.compute_runtime_params()
        context_window = rt.context_window
    except Exception:
        pass

    # ── 명령 조립 ──
    cmd = build_sandbox_pipe_cmd(
        image=config.SANDBOX_IMAGE,
        container_name=container,
        workspace=workspace,
        workspace_mount=config.SANDBOX_WORKSPACE_MOUNT,
        model_tag=config.MODEL_TAG,
        ollama_port=config.OLLAMA_PORT,
        profile_system_message=profile.system_message,
        context_window=context_window,
        memory_limit=run_mem,
        cpu_limit=run_cpus,
        block_internet=True,    # 기본 안전
        auto_run=True,           # 샌드박스 안이라 안전
    )

    # ── ChatPanel 생성 (TkPresenter 의 PanelHost 위에) ──
    # GUI presenter 라는 가정 — 호출자가 보장
    gui = p
    main_window = getattr(gui, "_window", None)
    if main_window is None:
        p.error("GUI 환경이 아닙니다 — 이 메뉴는 GUI 전용입니다")
        p.pause()
        return

    agent = UnifiedAgent()
    panel_holder = {"panel": None}

    def build_panel(parent):
        panel = ChatPanel(
            parent,
            title=f"에이전트 대화 — {profile.label}",
            subtitle=f"마운트: {workspace}  |  컨테이너: {container}",
            workspace=workspace,
        )

        # 콜백 연결
        def on_user_input(text: str):
            ok = agent.send_input(text)
            if not ok:
                panel.append_message("warn", "에이전트가 실행 중이 아닙니다")

        def on_stop():
            panel.append_message("system", "[중단 요청…]")
            agent.stop(timeout=2.0)
            panel.disable_send()

        def on_restart():
            panel.append_message("system", "[재시작 요청…]")
            agent.stop(timeout=2.0)
            # 새 컨테이너 이름으로 재시작
            nonlocal_container[0] = f"{config.SANDBOX_CONTAINER_PREFIX}chat_{secrets.token_hex(4)}"
            new_cmd = list(cmd)
            # --name 다음 항목을 교체
            try:
                idx = new_cmd.index("--name")
                new_cmd[idx + 1] = nonlocal_container[0]
            except (ValueError, IndexError):
                pass
            agent.start(new_cmd)
            panel.enable_send()

        def on_open():
            _open_folder_in_explorer(workspace)

        panel.set_input_callback(on_user_input)
        panel.set_stop_callback(on_stop)
        panel.set_restart_callback(on_restart)
        panel.set_open_folder_callback(on_open)
        panel.refresh_files(workspace)
        panel.set_status(
            f"프로필: {profile.label}\n"
            f"메모리: {run_mem.upper()}\n"
            f"CPU: {run_cpus} 코어\n"
            f"인터넷: 차단\n"
            f"화면 캡처: 비활성"
        )
        panel_holder["panel"] = panel
        return panel

    nonlocal_container = [container]
    main_window.host.replace(build_panel)
    panel = panel_holder["panel"]
    if panel is None:
        return

    # ── 에이전트 시작 ──
    panel.append_message("system", f"에이전트를 시작합니다… (프로필: {profile.label})")
    panel.append_message("system", "명령: " + " ".join(cmd[:6]) + " ...")
    started = agent.start(cmd)
    if not started:
        panel.append_message("error", "에이전트 시작 실패. Docker 데몬과 이미지 상태를 확인하세요.")
        return

    # ── 폴링 루프 (Tk after 기반) ──
    poll_interval_ms = 80
    files_refresh_counter = [0]

    def poll():
        try:
            msgs = agent.drain_messages(max_n=100)
            for m in msgs:
                if m.level == LEVEL_TERMINATED:
                    panel.append_message("terminated", m.text)
                    panel.disable_send()
                else:
                    panel.append_message(m.level, m.text)

            # 약 2초마다 파일 리스트 갱신
            files_refresh_counter[0] += 1
            if files_refresh_counter[0] >= 25:  # 80ms * 25 = 2000ms
                files_refresh_counter[0] = 0
                panel.refresh_files(workspace)
        except Exception:
            pass

        # 패널이 살아있으면 계속 폴링
        try:
            main_window.root.after(poll_interval_ms, poll)
        except Exception:
            pass

    main_window.root.after(poll_interval_ms, poll)


def run(env: Path, p: Presenter) -> None:
    """메뉴 [9] 진입점."""
    p.section("GUI 통합 대화 모드")

    # GUI 전용 가드
    try:
        from ..presenter.gui import TkPresenter
        if not isinstance(p, TkPresenter):
            p.warn("이 메뉴는 GUI (TkPresenter) 전용입니다.")
            p.info("터미널 모드에서는 [2] 샌드박스 에이전트를 사용하세요.")
            p.pause()
            return
    except ImportError:
        p.error("GUI 모듈 로드 실패")
        p.pause()
        return

    # 사전 검사: Docker
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

    # 프로필 선택
    profile = _select_profile(p)
    if profile is None:
        p.info("취소됨")
        p.pause()
        return

    # 워크스페이스
    workspace = _ask_workspace(p, env)
    if workspace is None:
        return
    workspace.mkdir(parents=True, exist_ok=True)

    # last_workspace 저장
    try:
        from .. import settings_store
        cfg = settings_store.load()
        if workspace != env / "agent" / "workspace":
            cfg.last_workspace = str(workspace)
        settings_store.save(cfg)
    except Exception:
        pass

    # 실행
    _run_gui_chat(env, p, profile, workspace)
