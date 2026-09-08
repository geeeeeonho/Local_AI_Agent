"""GUI entrypoint for the Open Interpreter automation agent.

The action owns top-level setup and ChatPanel construction. Selection helpers,
runtime construction and live session control are intentionally delegated to
``launcher.agent.setup_flow``, ``launcher.agent.runtime_config`` and
``launcher.agent.chat_session_controller``.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

import launcher.agent.runtime_config as runtime_config
import launcher.agent.setup_flow as setup_flow
from launcher import config, network_policy
from launcher.agent.backend import AgentConfig, ProcessRuntimeSpec
from launcher.agent.backend_factory import create_backend
from launcher.agent.chat_session_controller import ChatSessionController
from launcher.agent.service import AgentService
from launcher.presenter.base import Presenter, RISK_HIGH


def _trace(stage: str) -> None:
    try:
        from launcher.core import lifelog
        lifelog.log("TRACE", "[agent_chat] " + stage)
    except Exception:
        pass


def _open_folder(folder: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


def _ensure_gui(p: Presenter) -> bool:
    try:
        from launcher.presenter.gui import TkPresenter
        if isinstance(p, TkPresenter):
            return True
    except Exception:
        pass
    p.warn("이 메뉴는 GUI (TkPresenter) 전용입니다.")
    p.info("터미널 모드에서는 별도 콘솔에서 실행하세요.")
    p.pause()
    return False


def _confirm_host_mode(p: Presenter) -> bool:
    p.section("호스트 직접 모드 — 위험 확인")
    p.error("호스트 PC 에 직접 접근합니다. 격리가 없습니다.")
    p.warn("모델 실수가 PC 에 직접 영향을 줄 수 있습니다.")
    return bool(
        p.confirm_dangerous(
            label="호스트 직접 모드 진입",
            description=(
                "에이전트가 호스트 PC 의 파일·명령에 직접 접근합니다.\n"
                "Open Interpreter workspace-write 정책과 사용자 승인이 적용되지만 "
                "컨테이너 격리는 없습니다."
            ),
            risk=RISK_HIGH,
        )
    )


def _select_setup(env: Path, p: Presenter):
    profile = setup_flow.select_profile(p)
    if profile is None:
        return None

    unified = False
    try:
        from launcher.agent import entry_dialog
        unified = entry_dialog.agent_setup(env, p)
    except Exception:
        unified = False

    if unified is None:
        p.info("취소")
        return None
    if isinstance(unified, dict):
        model_selection = unified
        mode = str(unified.get("mode") or "sandbox")
    else:
        model_selection = setup_flow.select_agent_model(env, p)
        if model_selection is None:
            return None
        mode = setup_flow.select_execution_mode(p)
        if mode is None:
            return None
        setup_flow.select_internet_mode(p)

    try:
        from launcher.agent import folder_policy
        folder_policy.maybe_manage(p, env)
    except Exception:
        pass

    workspace = setup_flow.ask_workspace(p, env)
    if workspace is None:
        return None

    selected_network = network_policy.current_mode()
    if mode == "host" and selected_network is network_policy.NetworkMode.BLOCK:
        p.error("Host 차단 모드는 OS 수준 hard-egress 경계가 없어 사용할 수 없습니다.")
        p.info("샌드박스 차단 또는 WARP/Tor/직접 연결을 선택하세요.")
        p.pause()
        return None
    if mode == "host" and not _confirm_host_mode(p):
        p.info("취소 (권장: 샌드박스 모드 사용)")
        p.pause()
        return None

    return profile, Path(workspace), mode, model_selection, selected_network


def _ensure_ollama(env: Path, p: Presenter) -> bool:
    try:
        from launcher.services.ollama import OllamaService
        if OllamaService(env, logger=p).ensure_running():
            return True
    except Exception as exc:
        p.error("Ollama 확인 실패: " + str(exc))
        return False
    p.error("Ollama 서비스를 시작할 수 없습니다.")
    return False


def _match_installed_model(tag: str, p: Presenter) -> str | None:
    """Keep the existing model ladder, but ensure the selected tag is installed."""
    try:
        from launcher.models import model_roles
        if not hasattr(model_roles, "auto_match_installed"):
            return tag
        role_name = None
        for name, ladder in getattr(model_roles, "LADDERS", {}).items():
            if any(model == tag for model, _need in ladder):
                role_name = name
                break
        try:
            free = model_roles.detect_free_memory_gb()
        except Exception:
            free = None
        host = "127.0.0.1:" + str(getattr(config, "OLLAMA_PORT", 11434))
        matched, note = model_roles.auto_match_installed(tag, role_name, free, host=host)
        if matched is None:
            p.error(note or "설치된 에이전트 모델이 없습니다 — SETUP.bat에서 모델을 설치하세요.")
            return None
        if matched != tag:
            p.warn(note or ("설치된 " + matched + " 로 자동 전환"))
        return matched
    except Exception:
        return tag


def _docker_required(mode: str, selected: network_policy.NetworkMode) -> bool:
    return mode == "sandbox" or selected in (
        network_policy.NetworkMode.WARP,
        network_policy.NetworkMode.TOR,
    )


def _prepare_runtime(env: Path, p: Presenter, mode: str, selected: network_policy.NetworkMode) -> bool:
    if not _ensure_ollama(env, p):
        return False

    docker_ready = False
    if _docker_required(mode, selected):
        try:
            from launcher.services.docker import DockerService
            docker_ready = DockerService.ensure_daemon(logger=p, timeout=90)
        except Exception:
            docker_ready = False
        if not docker_ready:
            p.error("Docker Desktop을 준비할 수 없어 에이전트 시작을 중단합니다.")
            return False
    else:
        try:
            from launcher.services.docker import DockerService
            docker_ready = DockerService.daemon_alive()
        except Exception:
            docker_ready = False

    if selected is network_policy.NetworkMode.BLOCK:
        if mode != "sandbox":
            return False
        if not network_policy.ensure_block_network(log=p.info):
            p.error("Block internal network를 안전하게 준비하지 못했습니다.")
            return False
    elif selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR):
        if not network_policy.prepare_runtime(selected, env_path=env, log=p.info):
            p.error(network_policy.display_label(selected) + " 준비 실패 — 직접 연결로 우회하지 않습니다.")
            return False

    if selected is not network_policy.NetworkMode.BLOCK and docker_ready:
        try:
            from launcher import searxng_runtime
            if not searxng_runtime.is_running():
                p.info("로컬 검색엔진(SearXNG) 준비 중...")
                if not searxng_runtime.start(env):
                    p.warn("SearXNG를 시작하지 못했습니다. 검색 기능은 사용할 수 없을 수 있습니다.")
        except Exception as exc:
            p.warn("SearXNG 준비 생략: " + str(exc))
    elif selected is not network_policy.NetworkMode.BLOCK:
        p.warn("Docker가 실행 중이 아니어서 SearXNG 검색은 비활성 상태입니다.")

    return True


def _approval_description(event, workspace: Path) -> str:
    data = dict(event.data or {})
    reason = data.get("reason") or event.content or "승인이 필요합니다."
    if data.get("kind") == "command":
        command = data.get("command") or "(명령 정보 없음)"
        cwd = data.get("cwd") or str(workspace)
        return "명령 실행 승인 요청\n\n명령: %s\n작업 폴더: %s\n사유: %s" % (command, cwd, reason)
    changes = data.get("changes") or data.get("item") or "파일 변경"
    return "파일 변경 승인 요청\n\n변경: %s\n사유: %s" % (str(changes)[:1200], reason)


def _mount_signature():
    try:
        from launcher.agent import folder_policy
        return (
            tuple(folder_policy.mounts_for()),
            tuple(folder_policy.tmpfs_masks_for()),
            tuple(folder_policy.list_denied()),
        )
    except Exception:
        return ()


def _launch_panel(
    env: Path,
    p: Presenter,
    *,
    profile,
    workspace: Path,
    mode: str,
    selected_network: network_policy.NetworkMode,
    model_tag: str,
    run_mem: str,
    run_cpus: str,
    command: list[str],
) -> None:
    from launcher.presenter.gui.chat_panel import ChatPanel

    main_window = getattr(p, "_window", None)
    if main_window is None:
        p.error("GUI 환경이 아닙니다.")
        return

    service = AgentService(create_backend(mode, env))
    model_holder = [str(model_tag)]
    command_holder = [list(command)]
    signature_holder = [_mount_signature()]
    panel_holder = {"panel": None}
    service_lock = threading.Lock()

    def ui(fn) -> None:
        try:
            main_window.root.after(0, fn)
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def post(level: str, text: str) -> None:
        panel = panel_holder.get("panel")
        if panel is None:
            return
        ui(lambda: panel.append_message(level, str(text)))

    def dispatch(name: str, fn) -> None:
        def worker():
            try:
                with service_lock:
                    fn()
            except Exception as exc:
                post("error", "%s 실패: %s" % (name, exc))
        threading.Thread(target=worker, daemon=True, name="agent-" + name).start()

    def config_for_current() -> AgentConfig:
        runtime_env = None
        if mode == "host":
            runtime_env = network_policy.host_proxy_env(selected_network)
        return AgentConfig(
            workspace=workspace,
            mode=mode,
            model=model_holder[0],
            network_mode=selected_network.value,
            profile_name=str(getattr(profile, "name", "agent")),
            runtime_spec=ProcessRuntimeSpec(
                command=tuple(str(part) for part in command_holder[0]),
                env=runtime_env,
                cwd=workspace if mode == "host" else None,
            ),
            instructions=str(getattr(profile, "system_message", "")),
        )

    def rebuild_sandbox_command() -> bool:
        if mode != "sandbox":
            return True
        new_container = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
        rebuilt, is_host = runtime_config.build_cmd_for_mode(
            "sandbox",
            env,
            profile,
            workspace,
            new_container,
            run_mem,
            run_cpus,
            model_tag=model_holder[0],
        )
        if rebuilt is None or is_host:
            return False
        command_holder[0] = list(rebuilt)
        return True

    def start_current() -> bool:
        return bool(service.start(config_for_current()))

    def restart_model(tag: str) -> bool:
        previous = model_holder[0]
        service.stop(timeout=2.0)
        model_holder[0] = str(tag)
        if rebuild_sandbox_command() and start_current():
            panel = panel_holder.get("panel")
            if panel is not None and hasattr(panel, "set_current_model"):
                ui(lambda: panel.set_current_model(model_holder[0]))
            return True
        model_holder[0] = previous
        rebuild_sandbox_command()
        start_current()
        return False

    def reload_policy():
        current = _mount_signature()
        if current == signature_holder[0]:
            return False
        service.stop(timeout=2.0)
        if not rebuild_sandbox_command() or not start_current():
            return None
        signature_holder[0] = current
        panel = panel_holder.get("panel")
        if panel is not None:
            ui(lambda: panel.refresh_files(workspace))
        return True

    def restart_service() -> bool:
        service.stop(timeout=2.0)
        return bool(rebuild_sandbox_command() and start_current())

    def new_session() -> bool:
        service.stop(timeout=2.0)
        return bool(rebuild_sandbox_command() and start_current())

    def stop_service() -> None:
        if mode == "host" and service.cancel():
            post("system", "현재 Host turn 중단 요청 완료")
            panel = panel_holder.get("panel")
            if panel is not None:
                ui(panel.enable_send)
            return
        service.stop(timeout=2.0)
        panel = panel_holder.get("panel")
        if panel is not None:
            ui(panel.disable_send)

    def approve(event) -> bool:
        try:
            return bool(
                p.confirm_dangerous(
                    label="Open Interpreter 작업 승인",
                    description=_approval_description(event, workspace),
                    risk=RISK_HIGH,
                )
            )
        except Exception:
            return False

    def on_terminated() -> None:
        panel = panel_holder.get("panel")
        if panel is not None:
            ui(panel.disable_send)

    controller = ChatSessionController(
        service,
        post=post,
        dispatch=dispatch,
        restart_model=restart_model,
        reload_policy=reload_policy,
        restart_service=restart_service,
        new_session=new_session,
        stop_service=stop_service,
        approval_decider=approve,
        on_terminated=on_terminated,
    )

    profile_label = getattr(profile, "label", None) or getattr(profile, "name", "에이전트")
    mode_label = "호스트 직접 (위험)" if mode == "host" else "샌드박스 (격리)"
    net_label = runtime_config.network_label(selected_network)

    def build_panel(parent):
        panel = ChatPanel(
            parent,
            title="에이전트 대화 — " + str(profile_label),
            subtitle=(
                "모드: " + mode_label + "  |  네트워크: " + net_label
                + "  |  마운트: " + str(workspace)
            ),
            workspace=workspace,
        )
        panel_holder["panel"] = panel
        panel.set_input_callback(controller.handle_input)
        panel.set_stop_callback(controller.stop)
        panel.set_restart_callback(controller.restart)
        panel.set_open_folder_callback(lambda: _open_folder(workspace))
        panel.set_status(
            "프로필: " + str(profile_label) + "\n"
            "모드: " + mode_label + "\n"
            "네트워크: " + net_label + "\n"
            "메모리: " + str(run_mem).upper() + "\n"
            "CPU: " + str(run_cpus) + " 코어"
        )
        panel.refresh_files(workspace)
        if hasattr(panel, "set_current_model"):
            panel.set_current_model(model_holder[0])
        panel.disable_send()

        def close_service() -> None:
            threading.Thread(
                target=lambda: service.stop(timeout=2.0),
                daemon=True,
                name="agent-close",
            ).start()
        panel.set_close_callback(close_service)
        return panel

    main_window.host.replace(build_panel)
    panel = panel_holder.get("panel")
    if panel is None:
        return

    post("system", "에이전트를 시작합니다... (프로필: " + str(profile_label) + ")")
    post("system", "[인터넷] " + net_label)
    post("system", "명령: /session · /resume <thread-id> · /new · /model <태그> · /folders · /reload")
    if mode == "host":
        post("warn", "호스트 직접 모드 — Open Interpreter workspace-write + 사용자 승인 정책")

    def initial_start() -> None:
        if start_current():
            post("system", "Open Interpreter 세션 준비 완료")
            ui(panel.enable_send)
        else:
            post("error", "에이전트 시작 실패. Docker/Ollama/Open Interpreter 상태를 확인하세요.")
            ui(panel.disable_send)

    dispatch("start", initial_start)

    poll_counter = [0]

    def poll() -> None:
        controller.poll_once(max_n=100)
        poll_counter[0] += 1
        if poll_counter[0] >= 25:
            poll_counter[0] = 0
            try:
                panel.refresh_files(workspace)
            except Exception:
                pass
        try:
            main_window.root.after(80, poll)
        except Exception:
            pass

    main_window.root.after(80, poll)


def run(env, p):
    """Open the integrated Open Interpreter automation-agent panel."""
    env = Path(env)
    p.section("자동화 에이전트")
    _trace("run 진입")

    if not _ensure_gui(p):
        return

    selected = _select_setup(env, p)
    if selected is None:
        return
    profile, workspace, mode, model_selection, selected_network = selected

    model_tag = str(model_selection.get("tag") or config.MODEL_TAG)
    p.info("에이전트 모델: " + model_tag + "  (" + str(model_selection.get("reason") or "선택") + ")")

    if not _prepare_runtime(env, p, mode, selected_network):
        p.pause()
        return

    model_tag = _match_installed_model(model_tag, p)
    if not model_tag:
        p.pause()
        return

    run_mem, run_cpus = runtime_config.resolve_resource_limits(env)
    container = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
    command, is_host = runtime_config.build_cmd_for_mode(
        mode,
        env,
        profile,
        workspace,
        container,
        run_mem,
        run_cpus,
        model_tag=model_tag,
    )
    if command is None:
        if is_host:
            p.error("Open Interpreter (호스트) 가 설치되지 않았습니다.")
            p.info("샌드박스 모드를 사용하거나 SETUP.bat을 다시 실행하세요.")
        else:
            p.error("에이전트 런타임 명령 조립 실패")
        p.pause()
        return

    _launch_panel(
        env,
        p,
        profile=profile,
        workspace=workspace,
        mode=mode,
        selected_network=selected_network,
        model_tag=model_tag,
        run_mem=run_mem,
        run_cpus=run_cpus,
        command=list(command),
    )
    _trace("패널 시작 완료")


__all__ = ["run"]
