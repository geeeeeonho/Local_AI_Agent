"""Runtime construction for the automation agent.

UI selection belongs to :mod:`setup_flow`. This module translates the selected
execution/network policy into a deterministic Host marker or Sandbox Docker
command and exposes canonical network labels for the GUI/evaluation tools.
"""
from __future__ import annotations

from pathlib import Path

from launcher import config, network_policy


def resolve_resource_limits(env: Path) -> tuple[str, str]:
    try:
        from installer.resources import compute_safety_profile, detect
        profile = compute_safety_profile(detect(Path(env)))
        return profile.container_memory, profile.container_cpus
    except Exception:
        return config.DEFAULT_CONTAINER_MEM, config.DEFAULT_CONTAINER_CPUS


def build_cmd_for_mode(
    mode,
    env,
    profile,
    workspace,
    container_name,
    run_mem,
    run_cpus,
    model_tag=None,
    tor_proxy=False,
):
    """Build the process marker/command for Host or Sandbox execution.

    ``profile`` and ``tor_proxy`` remain in the signature for existing callers;
    profile instructions travel in AgentConfig and canonical ``network_policy``
    is the only source of network meaning.
    """
    del profile, tor_proxy
    env = Path(env)
    workspace = Path(workspace)

    if mode == "sandbox":
        from launcher.agent.sandbox_policy import build_sandbox_docker_command

        selected = network_policy.current_mode()
        command = build_sandbox_docker_command(
            image=config.SANDBOX_IMAGE,
            container_name=container_name,
            workspace=workspace,
            workspace_mount=config.SANDBOX_WORKSPACE_MOUNT,
            memory_limit=run_mem,
            cpu_limit=run_cpus,
            block_internet=(selected is network_policy.NetworkMode.BLOCK),
            tor_proxy=selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR),
            network_mode=selected.value,
        )
        return command, False

    if mode != "host":
        return None, False

    tag = model_tag or config.MODEL_TAG
    try:
        from launcher.agent.interpreter_backend import managed_interpreter_exe
        if not managed_interpreter_exe(env.parent).is_file():
            return None, True
    except Exception:
        return None, True

    # Structured Host backend constructs its own App Server process. This is a
    # non-executable marker retained for existing orchestration/UI code.
    return ["managed-open-interpreter", "--model", "ollama/" + tag], True


def network_label(mode=None) -> str:
    return network_policy.display_label(mode or network_policy.current_mode())


def network_flags(mode=None) -> tuple[bool, bool]:
    """Return compatibility booleans ``(proxy_enabled, block_enabled)``."""
    selected = network_policy.normalize_mode(mode or network_policy.current_mode())
    return (
        selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR),
        selected is network_policy.NetworkMode.BLOCK,
    )


__all__ = [
    "resolve_resource_limits",
    "build_cmd_for_mode",
    "network_label",
    "network_flags",
]
