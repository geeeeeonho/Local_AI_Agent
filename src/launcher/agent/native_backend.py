from __future__ import annotations

from pathlib import Path

from .app_server_protocol import INITIALIZE, INITIALIZED, initialize_params
from .backend import AgentConfig
from .events import AgentEvent, AgentEventType
from .interpreter_backend import OpenInterpreterBackend, runtime_interpreter_home
from .runtime_assets import (
    prepare_host_runtime_assets_with_fingerprint,
    prepare_sandbox_runtime_assets,
)
from .sandbox_backend import SandboxOpenInterpreterBackend


class NativeOpenInterpreterBackend(OpenInterpreterBackend):
    """Host OI backend with product-managed MCP and permission assets."""

    def __init__(self, client_factory=None):
        if client_factory is None:
            super().__init__()
        else:
            super().__init__(client_factory=client_factory)
        self._host_process_policy_fingerprint: str | None = None
        self._launch_policy_fingerprint: str | None = None

    def _searxng_url(self) -> str:
        try:
            from launcher import config as launcher_config
            return str(launcher_config.SEARXNG_URL)
        except Exception:
            return "http://127.0.0.1:8888"

    def _prepare_host_policy_assets(self, config: AgentConfig) -> str | None:
        try:
            _config_path, fingerprint = prepare_host_runtime_assets_with_fingerprint(
                runtime_interpreter_home(),
                searxng_url=self._searxng_url(),
                network_mode=config.network_mode,
                workspace=config.workspace,
            )
            return fingerprint
        except Exception as exc:
            self._trace_record(
                "host_permission_prepare_failed",
                {"error": str(exc)},
            )
            return None

    def _host_process_client_spec(
        self, config: AgentConfig
    ) -> tuple[list[str], dict[str, str], Path]:
        """Return process parameters without rewriting Host permission assets."""
        return super()._client_spec(config)

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        fingerprint = self._prepare_host_policy_assets(config)
        if fingerprint is None:
            raise RuntimeError("Host permission assets could not be prepared")
        self._launch_policy_fingerprint = fingerprint
        return self._host_process_client_spec(config)

    def start(self, config: AgentConfig) -> bool:
        self._launch_policy_fingerprint = None
        self._host_process_policy_fingerprint = None
        ok = super().start(config)
        if ok:
            fingerprint = self._launch_policy_fingerprint
            if fingerprint is None:
                # The App Server must never be treated as policy-bound when the
                # exact permission identity loaded at launch is unknown.
                super().stop(timeout=2.0)
                return False
            self._host_process_policy_fingerprint = fingerprint
        else:
            self._host_process_policy_fingerprint = None
        return ok

    def _thread_params(self, config: AgentConfig):
        params = super()._thread_params(config)
        policy = __import__(
            "launcher.agent.execution_policy", fromlist=["policy_for_mode"]
        ).policy_for_mode(config.mode)
        params.pop("sandbox", None)
        if policy.permission_profile:
            params["config"] = {"default_permissions": policy.permission_profile}
        return params

    def _emit_host_resume_error(self, text: str) -> None:
        self._trace_record("host_permission_resume_failed", {"error": text})
        self._emit(AgentEvent(AgentEventType.ERROR, text, "error"))

    def _restart_for_resume(self, session_id: str, fingerprint: str) -> bool:
        config = self._config
        old_client = self._client
        if (
            config is None
            or old_client is None
            or not old_client.is_running()
            or not session_id
            or self._turn_id
        ):
            self._emit_host_resume_error(
                "Host permission policy changed, but the current App Server cannot be safely replaced"
            )
            return False

        self._trace_record(
            "host_permission_process_restart",
            {
                "session_id": session_id,
                "old_fingerprint": self._host_process_policy_fingerprint,
                "new_fingerprint": fingerprint,
            },
        )
        if old_client.stop(timeout=3.0) is not True:
            self._emit_host_resume_error(
                "Host permission policy changed, but the previous Open Interpreter process did not stop"
            )
            return False

        self._client = None
        self._thread_id = None
        self._turn_id = None
        self._host_process_policy_fingerprint = None

        try:
            command, runtime_env, process_cwd = self._host_process_client_spec(config)
            new_client = self._client_factory(command, runtime_env, process_cwd)
        except Exception as exc:
            self._emit_host_resume_error(
                f"Host permission policy changed, but the replacement App Server could not be prepared: {exc}"
            )
            return False

        if not new_client.start():
            self._emit_host_resume_error(
                "Host permission policy changed, but the replacement Open Interpreter App Server failed to start"
            )
            return False

        try:
            new_client.request(INITIALIZE, initialize_params(), timeout=10.0)
            if not new_client.notify(INITIALIZED, {}):
                raise RuntimeError("failed to send initialized notification")
        except Exception as exc:
            new_client.stop(timeout=2.0)
            self._emit_host_resume_error(
                f"Host permission policy changed, but the replacement App Server failed to initialize: {exc}"
            )
            return False

        self._client = new_client
        self._host_process_policy_fingerprint = fingerprint
        if not super().resume(session_id):
            new_client.stop(timeout=2.0)
            self._client = None
            self._thread_id = None
            self._host_process_policy_fingerprint = None
            return False

        self._register_cleanup()
        return True

    def resume(self, session_id: str) -> bool:
        config = self._config
        client = self._client
        if (
            config is None
            or client is None
            or not client.is_running()
            or not session_id
            or self._turn_id
        ):
            return False

        current_fingerprint = self._prepare_host_policy_assets(config)
        if current_fingerprint is None:
            return False

        if current_fingerprint == self._host_process_policy_fingerprint:
            return super().resume(session_id)

        return self._restart_for_resume(session_id, current_fingerprint)

    def stop(self, timeout: float = 3.0) -> None:
        try:
            super().stop(timeout=timeout)
        finally:
            self._host_process_policy_fingerprint = None
            self._launch_policy_fingerprint = None


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
