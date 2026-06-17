"""actions.agent_chat — [9] GUI 통합 대화 모드.

지시사항 [1~4단계] 통합:
  - 프로젝트 프로필 선택 (range_dev/Python/web/Unity/...)
  - subprocess.PIPE 로 docker 안 interpreter 실행
  - 단일 윈도우 내 대화창에서 양방향 상호작용
  - 화면 캡처 시도 자동 차단 (system_message + env + ErrorGuard)
  - [중단] 버튼으로 즉시 종료

GUI 전용 — TUI 에서 호출 시 안내 후 폴백.
"""
# v7_2_diag
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
    # 응답 행동 규칙은 SAFETY_PREAMBLE 에 이미 포함됨.
    # 세션별 동적 정보(호스트 워크스페이스 경로) 만 여기서 append.
    from .. import profiles as _profiles
    _system_msg = profile.system_message + _profiles.build_session_addendum(workspace)

    cmd = build_sandbox_pipe_cmd(
        image=config.SANDBOX_IMAGE,
        container_name=container,
        workspace=workspace,
        workspace_mount=config.SANDBOX_WORKSPACE_MOUNT,
        model_tag=config.MODEL_TAG,
        ollama_port=config.OLLAMA_PORT,
        profile_system_message=_system_msg,
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
            _v63_trace("agent.start() 호출 직전")
            agent.start(new_cmd)
            panel.enable_send()

        def on_open():
            _open_folder_in_explorer(workspace)

        panel.set_input_callback(on_user_input)
        panel.set_stop_callback(on_stop)
        panel.set_restart_callback(on_restart)
        panel.set_open_folder_callback(on_open)

        # v4_lifecycle: 패널 종료(사이드바 이동/창 닫기) 시 agent 정리
        def _on_panel_close():
            try:
                agent.stop(timeout=3.0)
            except Exception:
                pass
        if hasattr(panel, 'set_close_callback'):
            panel.set_close_callback(_on_panel_close)
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
        try:
            from .. import lifelog as _ll
            _ll.log("FAIL", "[agent_chat] panel_holder 가 비어있음 — build_panel 미완료")
            p.error("대화창을 만들지 못했습니다 (panel=None)")
            p.pause()
        except Exception:
            pass
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
        # v4_lifecycle: 패널이 destroy 됐으면 폴링 중단
        try:
            _alive = panel.frame.winfo_exists()
        except Exception:
            _alive = False
        if not _alive:
            try:
                agent.stop(timeout=1.0)
            except Exception:
                pass
            return

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


# v6_3_comprehensive: action 단계별 trace
def _v63_trace(stage: str) -> None:
    """lifelog 가 있으면 trace 기록. 없으면 무시."""
    try:
        from .. import lifelog as _ll
        _ll.log("TRACE", "[agent_chat] " + stage)
    except Exception:
        pass



# ─────────────────────────────────────────────
#  v7_1_unified: 통합 자동화 에이전트 진입점
# ─────────────────────────────────────────────
def _select_execution_mode(p):
    """실행 모드 선택 — 샌드박스(권장) vs 호스트 직접(위험).

    Returns: "sandbox" | "host" | None(취소)
    """
    from ..presenter.base import MenuItem
    items = [
        MenuItem(
            key="sandbox", title="샌드박스 (권장)",
            description="Docker 컨테이너에서 격리 실행 — 안전",
            badge="권장", badge_kind="good",
        ),
        MenuItem(
            key="host", title="호스트 직접 (위험)",
            description="호스트 PC 에 직접 접근 — 격리 없음",
            badge="위험", badge_kind="danger",
        ),
    ]
    choice = p.show_menu(
        title="실행 모드 선택",
        subtitle="에이전트를 어디서 실행할지 선택하세요",
        items=items,
    )
    if choice in ("sandbox", "host"):
        return choice
    return None


# LLM_AGENT_MODEL_ROLE_v1: 역할 기반 메모리 적응형 모델 선택
def _select_agent_model(env, p):
    """에이전트가 쓸 모델을 역할 기반으로 선택 + 메모리 적응 해석.

    Returns: {"tag","reason","label"} 또는 None(취소).
    model_roles 가 없으면 config.MODEL_TAG 로 안전 폴백.
    """
    from .. import config
    try:
        from .. import model_roles as mr
    except Exception:
        try:
            from launcher import model_roles as mr  # 절대 경로 폴백
        except Exception:
            return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    try:
        from ..presenter.base import MenuItem
    except Exception:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    # 코드 실행 에이전트에 적합한 역할만 (무검열 검색/번역은 채팅용 → 실행기에서 제외)
    exec_keys = ("2", "3", "4")  # 코딩 / 맥락 / 균형
    roles = [mr.by_key(k) for k in exec_keys if mr.by_key(k)]
    if not roles:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    items = []
    for r in roles:
        _badge = "권장" if r.key == "2" else None
        items.append(MenuItem(
            key=r.key, title=r.label, description=r.description,
            badge=_badge, badge_kind=("good" if _badge else None),
        ))
    items.append(MenuItem(key="b", title="취소", separator_above=True))

    free = mr.detect_free_memory_gb()
    free_txt = ("여유 메모리 " + format(free, ".1f") + "GB") if free is not None else "여유 메모리 탐지 실패"
    choice = p.show_menu(
        title="에이전트 모델 역할 선택",
        subtitle=free_txt + " · 코딩은 부족하면 7b 자동",
        items=items,
    )
    if choice in ("b", "q"):
        return None
    role = mr.by_key(choice) or mr.by_key("2")
    res = mr.resolve(role, free)
    return {"tag": res.model, "reason": res.reason, "label": role.label}


def _build_cmd_for_mode(mode, env, profile, workspace, container_name,
                        context_window, run_mem, run_cpus, model_tag=None):
    """모드별 PIPE 명령 조립.

    Returns: (cmd, is_host) 또는 (None, _) 실패 시
    """
    from .. import config
    if mode == "sandbox":
        from ..agent_runner import build_sandbox_pipe_cmd
        cmd = build_sandbox_pipe_cmd(
            image=config.SANDBOX_IMAGE,
            container_name=container_name,
            workspace=workspace,
            workspace_mount=config.SANDBOX_WORKSPACE_MOUNT,
            model_tag=(model_tag or config.MODEL_TAG),
            ollama_port=config.OLLAMA_PORT,
            profile_system_message=profile.system_message,
            context_window=context_window,
            memory_limit=run_mem,
            cpu_limit=run_cpus,
            block_internet=True,
            auto_run=True,   # 샌드박스 안이라 안전
        )
        return cmd, False
    else:  # host
        from ..agent_runner import build_host_pipe_cmd
        interp = env / "agent" / "venv" / "Scripts" / "interpreter.exe"
        if not interp.exists():
            return None, True
        cmd = build_host_pipe_cmd(
            interpreter_exe=str(interp),
            model_tag=(model_tag or config.MODEL_TAG),
            ollama_url=config.OLLAMA_URL,
            profile_system_message=profile.system_message,
            context_window=context_window,
            auto_run=False,  # 호스트는 매 명령 확인 (안전)
        )
        return cmd, True


def run(env, p):
    """[2] 통합 자동화 에이전트 진입점 (v7_1_unified).

    프로필 선택 -> 워크스페이스 선택 -> 실행 모드 선택
    -> GUI 내장 ChatPanel 로 양방향 대화 (샌드박스/호스트 공통).
    """
    from .. import config
    import secrets

    p.section("자동화 에이전트")
    _v63_trace("통합 run() 진입")

    # GUI 전용 가드
    try:
        from ..presenter.gui import TkPresenter
        if not isinstance(p, TkPresenter):
            p.warn("이 메뉴는 GUI (TkPresenter) 전용입니다.")
            p.info("터미널 모드에서는 별도 콘솔에서 실행하세요.")
            p.pause()
            return
    except Exception:
        pass

    # ── 1) 프로필 선택 ──
    _v63_trace("프로필 선택 직전")
    profile = _select_profile(p)
    _v63_trace("프로필 선택 완료: " + (profile.name if profile else "None"))
    if profile is None:
        return

    # LLM_AGENT_MODEL_ROLE_v1: 역할(모델) 선택 — 메모리 적응형
    _model_sel = _select_agent_model(env, p)
    if _model_sel is None:
        return
    agent_model_tag = _model_sel["tag"]
    p.info("에이전트 모델: " + agent_model_tag + "  (" + _model_sel["reason"] + ")")

    # ── 2) 워크스페이스 선택 ──
    _v63_trace("워크스페이스 선택 직전")
    workspace = _ask_workspace(p, env)
    _v63_trace("워크스페이스 선택 완료: " + str(workspace))
    if workspace is None:
        return

    # ── 3) 실행 모드 선택 ──
    _v63_trace("실행 모드 선택 직전")
    mode = _select_execution_mode(p)
    _v63_trace("실행 모드 선택 완료: " + str(mode))
    if mode is None:
        return

    # ── 4) 호스트 직접이면 확인 게이트 ──
    if mode == "host":
        from ..presenter.base import RISK_HIGH
        p.section("호스트 직접 모드 — 위험 확인")
        p.error("호스트 PC 에 직접 접근합니다. 격리가 없습니다.")
        p.warn("모델 실수가 PC 에 직접 영향을 줄 수 있습니다.")
        if not p.confirm_dangerous(
            label="호스트 직접 모드 진입",
            description=(
                "에이전트가 호스트 PC 의 모든 파일·명령에 직접 접근합니다.\n"
                "복구 불가능한 손상이 발생할 수 있습니다."
            ),
            risk=RISK_HIGH,
        ):
            p.info("취소 (권장: 샌드박스 모드 사용)")
            p.pause()
            return

    # ── 5) Ollama 확인 ──
    try:
        from ..services.ollama import OllamaService
        if not OllamaService(env, logger=p).ensure_running():
            p.error("Ollama 서비스를 시작할 수 없습니다.")
            p.pause()
            return
    except Exception:
        pass

    # ── 6) 명령 조립 ──
    run_mem, run_cpus = _resolve_resource_limits(env)
    container = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
    context_window = 4096
    try:
        from .. import runtime_guard
        rt = runtime_guard.compute_runtime_params()
        context_window = rt.context_window
    except Exception:
        pass

    cmd, is_host = _build_cmd_for_mode(
        mode, env, profile, workspace, container,
        context_window, run_mem, run_cpus,
        model_tag=agent_model_tag,
    )
    if cmd is None:
        if is_host:
            p.error("Open Interpreter (호스트) 가 설치되지 않았습니다.")
            p.info("샌드박스 모드를 사용하거나 INSTALL 을 다시 실행하세요.")
        else:
            p.error("명령 조립 실패")
        p.pause()
        return

    # ── 7) GUI 통합 대화창 실행 (v7.0 스레드 마샬링) ──
    _v63_trace("_run_gui_chat 호출 직전 (통합)")
    _run_gui_chat_unified(env, p, profile, workspace, cmd, container, is_host,
                          run_mem, run_cpus)
    _v63_trace("_run_gui_chat 반환됨 (통합)")


def _run_gui_chat_unified(env, p, profile, workspace, cmd, container, is_host,
                          run_mem, run_cpus):
    """통합 GUI 대화창 — 샌드박스/호스트 공통.

    v7_0_threadfix 스레드 마샬링 내장.
    """
    from ..agent_runner import UnifiedAgent, LEVEL_TERMINATED
    from ..presenter.gui.chat_panel import ChatPanel

    main_window = getattr(p, "_window", None)
    if main_window is None:
        p.error("GUI 환경이 아닙니다.")
        p.pause()
        return

    agent = UnifiedAgent()

    # 호스트 모드면 lifelog 에 프로세스 정리 등록
    if is_host:
        try:
            from .. import lifelog as _ll
            if hasattr(_ll, "register_host_process_cleanup"):
                def _get_pid():
                    try:
                        proc = getattr(agent, "_proc", None)
                        return proc.pid if proc else None
                    except Exception:
                        return None
                _ll.register_host_process_cleanup(_get_pid)
        except Exception:
            pass

    panel_holder = {"panel": None}
    nonlocal_container = [container]

    def build_panel(parent):
        mode_label = "호스트 직접 (위험)" if is_host else "샌드박스 (격리)"
        _plabel = getattr(profile, "label", None) or getattr(profile, "name", "에이전트")
        panel = ChatPanel(
            parent,
            title="에이전트 대화 — " + str(_plabel),
            subtitle="모드: " + mode_label + "  |  마운트: " + str(workspace),
            workspace=workspace,
        )

        def on_user_input(text):
            ok = agent.send_input(text)
            if not ok:
                panel.append_message("warn", "에이전트가 실행 중이 아닙니다")

        def on_stop():
            panel.append_message("system", "[중단 요청...]")
            agent.stop(timeout=2.0)
            panel.disable_send()

        def on_restart():
            panel.append_message("system", "[재시작 요청...]")
            agent.stop(timeout=2.0)
            agent.start(cmd)
            panel.enable_send()

        def on_open():
            _open_folder_in_explorer(workspace)

        panel.set_input_callback(on_user_input)
        panel.set_stop_callback(on_stop)
        panel.set_restart_callback(on_restart)
        panel.set_open_folder_callback(on_open)
        panel.refresh_files(workspace)
        panel.set_status(
            "프로필: " + str(_plabel) + "\n"
            "모드: " + mode_label + "\n"
            "메모리: " + str(run_mem).upper() + "\n"
            "CPU: " + str(run_cpus) + " 코어"
        )
        panel_holder["panel"] = panel
        return panel

    # v7_0_threadfix: ChatPanel 생성을 메인 스레드로 마샬링
    import threading as _thr
    _panel_ready = _thr.Event()
    _build_error = [None]

    def _build_on_main():
        try:
            from .. import lifelog as _ll
            _ll.log("TRACE", "[agent_chat] (메인) host.replace 시작")
        except Exception:
            pass
        try:
            main_window.host.replace(build_panel)
        except Exception as _e:
            _build_error[0] = _e
            try:
                import traceback as _tb
                from .. import lifelog as _ll2
                _ll2.log("FAIL", "[agent_chat] host.replace 예외: " + repr(_e))
                _ll2.log("DEBUG", _tb.format_exc())
            except Exception:
                pass
        finally:
            _panel_ready.set()
            try:
                from .. import lifelog as _ll3
                _ll3.log("TRACE", "[agent_chat] (메인) host.replace 종료")
            except Exception:
                pass

    try:
        main_window.root.after(0, _build_on_main)
    except Exception:
        _build_on_main()

    if not _panel_ready.wait(timeout=10.0):
        try:
            from .. import lifelog as _ll
            _ll.log("FAIL", "[agent_chat] 통합 패널 생성 10초 타임아웃")
        except Exception:
            pass
        return
    if _build_error[0] is not None:
        try:
            from .. import lifelog as _ll
            _ll.log("FAIL", "[agent_chat] 패널 생성 예외로 중단: "
                   + repr(_build_error[0]))
            p.error("대화창 생성 실패: " + str(_build_error[0]))
            p.pause()
        except Exception:
            pass
        return

    panel = panel_holder["panel"]
    if panel is None:
        return

    # 메인 스레드 마샬링 append
    def _safe_append(level, txt):
        try:
            main_window.root.after(0, lambda: panel.append_message(level, txt))
        except Exception:
            try:
                panel.append_message(level, txt)
            except Exception:
                pass

    try:
        _pl = getattr(profile, "label", None) or getattr(profile, "name", "에이전트")
    except Exception:
        _pl = "에이전트"
    _safe_append("system", "에이전트를 시작합니다... (프로필: " + str(_pl) + ")")
    if is_host:
        _safe_append("warn", "호스트 직접 모드 — 매 명령 확인이 필요합니다")
    try:
        from .. import lifelog as _ll
        _ll.log("TRACE", "[agent_chat] agent.start 호출 직전")
        _ll.log("INFO", "[agent_chat] 명령: " + " ".join(str(c) for c in cmd[:8]))
    except Exception:
        pass

    # v8_3_dockergate: Docker 미응답 시 Docker Desktop 자동 시작 후 대기 (수동 시작 불필요)
    if not is_host:
        try:
            from ..services.docker import DockerService as _DS
            if not _DS.daemon_alive():
                _safe_append("system", "Docker 데몬이 응답하지 않습니다 — Docker Desktop 자동 시작 시도 중...")
                _safe_append("warn", "완전히 켜질 때까지 30초~1분 걸릴 수 있습니다. 잠시만 기다려 주세요.")
                class _DLog:
                    def info(self, m): _safe_append("system", str(m))
                    def ok(self, m): _safe_append("system", str(m))
                    def warn(self, m): _safe_append("warn", str(m))
                    def error(self, m): _safe_append("error", str(m))
                if _DS.ensure_daemon(logger=_DLog(), timeout=90):
                    _safe_append("system", "Docker 준비 완료 — 에이전트를 시작합니다.")
                else:
                    _safe_append("error", "Docker 를 시작하지 못했습니다. Docker Desktop 을 직접 켠 뒤 [재시작] 을 누르세요.")
        except Exception:
            pass

    started = agent.start(cmd)
    try:
        from .. import lifelog as _ll2
        _ll2.log("TRACE", "[agent_chat] agent.start 반환: " + str(started))
    except Exception:
        pass
    if not started:
        _safe_append("error", "에이전트 시작 실패. Docker/Ollama 상태를 확인하세요.")
        try:
            from .. import lifelog as _ll3
            _ll3.log("FAIL", "[agent_chat] agent.start 실패")
        except Exception:
            pass
        return

    # 폴링 루프
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
            files_refresh_counter[0] += 1
            if files_refresh_counter[0] >= 25:
                files_refresh_counter[0] = 0
                panel.refresh_files(workspace)
        except Exception:
            pass
        try:
            main_window.root.after(poll_interval_ms, poll)
        except Exception:
            pass

    main_window.root.after(poll_interval_ms, poll)

