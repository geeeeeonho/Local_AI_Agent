from __future__ import annotations

from pathlib import Path

from .backend import AgentConfig
from .interpreter_backend import OpenInterpreterBackend, runtime_interpreter_home
from .runtime_assets import prepare_host_runtime_assets, prepare_sandbox_runtime_assets
from .sandbox_backend import SandboxOpenInterpreterBackend


class NativeOpenInterpreterBackend(OpenInterpreterBackend):
    """Host OI backend with product-managed MCP runtime assets."""

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        try:
            from launcher import config as launcher_config
            searxng_url = str(launcher_config.SEARXNG_URL)
        except Exception:
            searxng_url = "http://127.0.0.1:8888"
        prepare_host_runtime_assets(runtime_interpreter_home(), searxng_url=searxng_url)
        return super()._client_spec(config)


class NativeSandboxOpenInterpreterBackend(SandboxOpenInterpreterBackend):
    """Docker OI backend with MCP assets mounted through agent state."""

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        from launcher.core import user_data

        state_dir = user_data.interpreter_dir("sandbox")
        prepare_sandbox_runtime_assets(
            state_dir,
            searxng_url="http://llm_searxng:8080",
        )
        return super()._client_spec(config)
