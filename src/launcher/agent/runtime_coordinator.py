"""Runtime/service lifecycle coordination for the automation-agent GUI.

Selection stays in :mod:`setup_flow`, deterministic command construction stays
in :mod:`runtime_config`, and live slash/event routing stays in
:mod:`chat_session_controller`.  This module owns the stateful boundary between
those pieces: service preparation, network prerequisites, AgentConfig creation,
and controlled restart/reload operations.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from launcher import config, network_policy
from launcher.services.docker import DockerService

from . import runtime_config
from .backend import AgentConfig, ProcessRuntimeSpec
from .backend_factory import create_backend
from .service import AgentService


def _ensure_ollama(env: Path, presenter) -> bool:
    try:
        from launcher.services.ollama import OllamaService

        if OllamaService(env, logger=presenter).ensure_running():
            return True
    except Exception as exc:
        presenter.error("Ollama 확인 실패: " + str(exc))
        return False
    presenter.error("Ollama 서비스를 시작할 수 없습니다.")
    return False


def _cancelled(cancel) -> bool:
    if cancel is None:
        return False
    try:
        return bool(cancel())
    except Exception:
        return False


def _docker_required(mode: str, selected: network_policy.NetworkMode) -> bool:
    return mode == "sandbox" or selected in (
        network_policy.NetworkMode.WARP,
        network_policy.NetworkMode.TOR,
    )


def prepare_runtime(
    env: Path,
    presenter,
    mode: str,
    selected: network_policy.NetworkMode,
    cancel=None,
) -> bool:
    """Prepare required services for one canonical execution/network mode.

    Security-sensitive failures are fail-closed.  WARP/Tor never fall back to
    Direct, Host+Block is rejected, and Sandbox Block must have the managed
    internal network before the agent can start.
    """
    env = Path(env)
    selected = network_policy.normalize_mode(selected)

    if selected is network_policy.NetworkMode.BLOCK and mode != "sandbox":
        presenter.error("Host 차단 모드는 OS 수준 hard-egress 경계가 없어 사용할 수 없습니다.")
        return False

    if _cancelled(cancel):
        return False

    if not _ensure_ollama(env, presenter):
        return False

    docker_ready = False
    if _docker_required(mode, selected):
        try:
            # Ninety seconds of Docker Desktop boot used to be uninterruptible,
            # so closing the window during Agent start had to sit through it.
            docker_ready = DockerService.ensure_daemon(
                logger=presenter, timeout=90, cancel_check=cancel)
        except Exception:
            docker_ready = False
        if not docker_ready:
            presenter.error("Docker Desktop을 준비할 수 없어 에이전트 시작을 중단합니다.")
            return False
    else:
        try:
            docker_ready = DockerService.daemon_alive()
        except Exception:
            docker_ready = False

    if _cancelled(cancel):
        return False

    if selected is network_policy.NetworkMode.BLOCK:
        if not network_policy.ensure_block_network(log=presenter.info):
            presenter.error("Block internal network를 안전하게 준비하지 못했습니다.")
            return False
    elif selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR):
        if not network_policy.prepare_runtime(selected, env_path=env,
                                              log=presenter.info, cancel=cancel):
            presenter.error(
                network_policy.display_label(selected)
                + " 준비 실패 — 직접 연결로 우회하지 않습니다."
            )
            return False

    if selected is not network_policy.NetworkMode.BLOCK and docker_ready:
        try:
            from launcher import searxng_runtime

            if not searxng_runtime.is_running():
                presenter.info("로컬 검색엔진(SearXNG) 준비 중...")
                # Without log/cancel this was a silent sixty-second wait whose
                # failure reason (missing image, missing settings.yml, docker
                # error) was written to a file nobody passed and then dropped.
                if not searxng_runtime.start(env, log=presenter.info,
                                             cancel_check=cancel):
                    presenter.warn(
                        "SearXNG를 시작하지 못했습니다. 검색 기능은 사용할 수 없을 수 있습니다."
                    )
        except Exception as exc:
            presenter.warn("SearXNG 준비 생략: " + str(exc))
    elif selected is not network_policy.NetworkMode.BLOCK:
        presenter.warn("Docker가 실행 중이 아니어서 SearXNG 검색은 비활성 상태입니다.")

    return True


def mount_signature():
    """Return the product folder-policy identity relevant to Sandbox remounts."""
    try:
        from launcher.agent import folder_policy

        return (
            tuple(folder_policy.mounts_for()),
            tuple(folder_policy.tmpfs_masks_for()),
            tuple(folder_policy.list_denied()),
        )
    except Exception:
        return ()


class RuntimeCoordinator:
    """Own mutable AgentService/runtime state for one open agent panel."""

    def __init__(
        self,
        *,
        env: Path,
        profile,
        workspace: Path,
        mode: str,
        selected_network: network_policy.NetworkMode,
        model_tag: str,
        run_mem: str,
        run_cpus: str,
        command: list[str],
        service=None,
    ) -> None:
        self.env = Path(env)
        self.profile = profile
        self.workspace = Path(workspace)
        self.mode = str(mode)
        self.selected_network = network_policy.normalize_mode(selected_network)
        self.model_tag = str(model_tag)
        self.run_mem = str(run_mem)
        self.run_cpus = str(run_cpus)
        self.command = list(command)
        self._signature = mount_signature()
        self.service = service or AgentService(create_backend(self.mode, self.env))

    def config_for_current(self) -> AgentConfig:
        runtime_env = None
        if self.mode == "host":
            runtime_env = network_policy.host_proxy_env(self.selected_network)
        return AgentConfig(
            workspace=self.workspace,
            mode=self.mode,
            model=self.model_tag,
            network_mode=self.selected_network.value,
            profile_name=str(getattr(self.profile, "name", "agent")),
            runtime_spec=ProcessRuntimeSpec(
                command=tuple(str(part) for part in self.command),
                env=runtime_env,
                cwd=self.workspace if self.mode == "host" else None,
            ),
            instructions=str(getattr(self.profile, "system_message", "")),
        )

    def rebuild_sandbox_command(self) -> bool:
        if self.mode != "sandbox":
            return True
        container_name = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
        rebuilt, is_host = runtime_config.build_cmd_for_mode(
            "sandbox",
            self.env,
            self.profile,
            self.workspace,
            container_name,
            self.run_mem,
            self.run_cpus,
            model_tag=self.model_tag,
        )
        if rebuilt is None or is_host:
            return False
        self.command = list(rebuilt)
        return True

    def start_current(self) -> bool:
        return bool(self.service.start(self.config_for_current()))

    def restart_model(self, tag: str) -> bool:
        previous = self.model_tag
        self.service.stop(timeout=2.0)
        self.model_tag = str(tag)
        if self.rebuild_sandbox_command() and self.start_current():
            return True

        self.model_tag = previous
        self.rebuild_sandbox_command()
        self.start_current()
        return False

    def reload_policy(self):
        current = mount_signature()
        if current == self._signature:
            return False
        self.service.stop(timeout=2.0)
        if not self.rebuild_sandbox_command() or not self.start_current():
            return None
        self._signature = current
        return True

    def restart_service(self) -> bool:
        self.service.stop(timeout=2.0)
        return bool(self.rebuild_sandbox_command() and self.start_current())

    def new_session(self) -> bool:
        self.service.stop(timeout=2.0)
        return bool(self.rebuild_sandbox_command() and self.start_current())

    def stop_service(self) -> str:
        if self.mode == "host" and self.service.cancel():
            return "cancelled"
        self.service.stop(timeout=2.0)
        return "stopped"


__all__ = ["RuntimeCoordinator", "mount_signature", "prepare_runtime"]
