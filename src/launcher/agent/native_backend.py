from __future__ import annotations

from pathlib import Path

from .backend import AgentConfig
from .interpreter_backend import OpenInterpreterBackend, runtime_interpreter_home
from .runtime_assets import prepare_host_runtime_assets, prepare_sandbox_runtime_assets
from .sandbox_backend import SandboxOpenInterpreterBackend


class NativeOpenInterpreterBackend(OpenInterpreterBackend):
    """Host OI backend with product-managed MCP and permission assets."""

    def _searxng_url(self) -> str:
        try:
            from launcher import config as launcher_config
            return str(launcher_config.SEARXNG_URL)
        except Exception:
            return "http://127.0.0.1:8888"

    def _prepare_host_policy_assets(self, config: AgentConfig) -> bool:
        try:
            prepare_host_runtime_assets(
                runtime_interpreter_home(),
                searxng_url=self._searxng_url(),
                network_mode=config.network_mode,
                workspace=config.workspace,
            )
            return True
        except Exception:
            return False

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        if not self._prepare_host_policy_assets(config):
            raise RuntimeError("Host permission assets could not be prepared")
        return super()._client_spec(config)

    def _thread_params(self, config: AgentConfig):
        params = super()._thread_params(config)
        policy = __import__(
            "launcher.agent.execution_policy", fromlist=["policy_for_mode"]
        ).policy_for_mode(config.mode)
        params.pop("sandbox", None)
        if policy.permission_profile:
            params["config"] = {"default_permissions": policy.permission_profile}
        return params

    def resume(self, session_id: str) -> bool:
        config = self._config
        if config is None or not self._prepare_host_policy_assets(config):
            return False
        return super().resume(session_id)


class NativeSandboxOpenInterpreterBackend(SandboxOpenInterpreterBackend):
    """Docker OI backend with MCP assets mounted through agent state."""

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        from launcher.core import user_data

        try:
            from launcher import config as launcher_config
            searxng_url = str(launcher_config.SEARXNG_INTERNAL_URL)
        except Exception:
            from .sandbox_backend import SANDBOX_SEARXNG_URL_FALLBACK
            searxng_url = SANDBOX_SEARXNG_URL_FALLBACK
        state_dir = user_data.interpreter_dir("sandbox")
        prepare_sandbox_runtime_assets(
            state_dir,
            searxng_url=searxng_url,
            network_mode=config.network_mode,
        )
        return super()._client_spec(config)
