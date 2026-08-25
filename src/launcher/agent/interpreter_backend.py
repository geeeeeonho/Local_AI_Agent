from __future__ import annotations

import os
import queue
from pathlib import Path
from typing import Any

from project_paths import PROJECT_ROOT, SRC_ROOT
from runtime_versions import OPEN_INTERPRETER_VERSION as OI_VERSION
from .agent_trace import AgentTrace
from .app_server_client import AppServerClient
from .backend import AgentConfig
from .events import AgentEvent, AgentEventType
from .instructions import build_structured_instructions

_SIMPLE_APPROVAL_DECISIONS = {"accept", "acceptForSession", "decline", "cancel"}

#: Notifications the App Server emits once per streamed token. They are counted
#: rather than traced individually.
_STREAM_DELTA_METHODS = frozenset({
    "item/agentMessage/delta",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/textDelta",
    "item/commandExecution/outputDelta",
})


def _project_root() -> Path:
    override = os.environ.get("LLM_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    return PROJECT_ROOT


def managed_interpreter_exe(project_root: Path | None = None) -> Path:
    root = Path(project_root).resolve() if project_root is not None else _project_root()
    return root / "llm_environment" / "open_interpreter" / "bin" / "interpreter.exe"


def managed_interpreter_home(project_root: Path | None = None) -> Path:
    root = Path(project_root).resolve() if project_root is not None else _project_root()
    return root / "llm_environment" / "open_interpreter" / "home"


def runtime_interpreter_home(project_root: Path | None = None) -> Path:
    root = Path(project_root).resolve() if project_root is not None else _project_root()
    path = root / "user_data" / "open_interpreter"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merge_no_proxy(env: dict[str, str]) -> None:
    required = ["localhost", "127.0.0.1", "::1"]
    current = env.get("NO_PROXY") or env.get("no_proxy") or ""
    values = [part.strip() for part in current.split(",") if part.strip()]
    for value in required:
        if value not in values:
            values.append(value)
    merged = ",".join(values)
    env["NO_PROXY"] = merged
    env["no_proxy"] = merged


class OpenInterpreterBackend:
    """Structured backend backed by Open Interpreter App Server.

    The default runtime hooks describe managed Host mode. Sandbox mode derives
    from this class and overrides only availability/process/thread isolation.
    """

    def __init__(self, client_factory=AppServerClient):
        self._client_factory = client_factory
        self._client = None
        self._config: AgentConfig | None = None
        self._thread_id: str | None = None
        self._turn_id: str | None = None
        self._events: queue.Queue = queue.Queue(maxsize=10000)
        self._cleanup_registered = False
        self._trace: AgentTrace | None = None
        self._stream_deltas: dict[str, int] = {}

    def _trace_record(
        self,
        event: str,
        details: Any = None,
        *,
        turn_id: str | None = None,
        detailed: bool = False,
    ) -> None:
        """Append one trace row.

        ``detailed`` marks rows whose details carry prompt, model output,
        command or tool payload. AgentTrace drops those payloads when the user
        has turned detailed logging off.
        """
        trace = self._trace
        if trace is None:
            return
        try:
            trace.record(
                event,
                thread_id=self._thread_id,
                turn_id=self._turn_id if turn_id is None else turn_id,
                details=details,
                detailed=detailed,
            )
        except Exception:
            pass

    def _flush_stream_counts(self, turn_id: str | None) -> None:
        if not self._stream_deltas:
            return
        counts, self._stream_deltas = self._stream_deltas, {}
        self._trace_record("stream_summary", counts, turn_id=turn_id)

    def _command(self) -> list[str]:
        return [
            str(managed_interpreter_exe()),
            "-c", "check_for_update_on_startup=false",
            "-c", 'web_search="disabled"',
            "app-server", "--listen", "stdio://",
        ]

    def _runtime_env(self, config: AgentConfig) -> dict[str, str]:
        env = dict(os.environ)
        runtime = config.runtime_spec
        if runtime is not None and runtime.env:
            env.update({str(k): str(v) for k, v in runtime.env.items()})
        env["INTERPRETER_HOME"] = str(runtime_interpreter_home())
        env["CODEX_OSS_BASE_URL"] = "http://127.0.0.1:11434/v1"
        src = str(SRC_ROOT)
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src if not current_pythonpath else src + os.pathsep + current_pythonpath
        _merge_no_proxy(env)
        return env

    def _runtime_available(self, config: AgentConfig) -> bool:
        return managed_interpreter_exe().is_file()

    def _client_spec(self, config: AgentConfig) -> tuple[list[str], dict[str, str], Path]:
        return self._command(), self._runtime_env(config), config.workspace.resolve()

    def _thread_sandbox_mode(self, config: AgentConfig) -> str:
        return "workspace-write"

    def _thread_cwd(self, config: AgentConfig) -> str:
        return str(config.workspace.resolve())

    def _instruction_profile(self, config: AgentConfig) -> str:
        try:
            from launcher.agent.profiles import build_host_session_addendum
            return config.instructions + build_host_session_addendum(config.workspace)
        except Exception:
            return config.instructions

    def _instruction_is_sandbox(self, config: AgentConfig) -> bool:
        return False

    def _thread_params(self, config: AgentConfig) -> dict[str, Any]:
        instructions = build_structured_instructions(
            self._instruction_profile(config),
            sandbox=self._instruction_is_sandbox(config),
        )
        return {
            "model": config.model,
            "modelProvider": "ollama",
            "cwd": self._thread_cwd(config),
            "approvalPolicy": "on-request",
            "approvalsReviewer": "user",
            "sandbox": self._thread_sandbox_mode(config),
            "serviceName": "Local_AI_Agent",
            "developerInstructions": instructions,
        }

    def start(self, config: AgentConfig) -> bool:
        if self.is_running():
            return False
        self._trace = AgentTrace(
            mode=config.mode,
            model=config.model,
            network_mode=config.network_mode,
            profile_name=config.profile_name,
            workspace=config.workspace,
        )
        self._trace_record(
            "backend_starting",
            {
                "oi_version": OI_VERSION,
                "runtime": str(managed_interpreter_exe()),
                "sandbox": self._thread_sandbox_mode(config),
            },
        )
        if not self._runtime_available(config):
            self._trace_record("backend_start_failed", {"reason": "runtime_unavailable"})
            self._emit(AgentEvent(AgentEventType.ERROR, "Open Interpreter runtime is not available", "error"))
            return False
        try:
            config.workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._trace_record("backend_start_failed", {"reason": "workspace_unavailable", "error": str(exc)})
            self._emit(AgentEvent(AgentEventType.ERROR, f"Workspace unavailable: {exc}", "error"))
            return False

        try:
            command, runtime_env, process_cwd = self._client_spec(config)
            self._trace_record(
                "app_server_starting",
                {
                    "command": command,
                    "cwd": str(process_cwd),
                    "interpreter_home": runtime_env.get("INTERPRETER_HOME"),
                    "ollama_base_url": runtime_env.get("CODEX_OSS_BASE_URL"),
                },
                detailed=True,
            )
        except Exception as exc:
            self._trace_record("backend_start_failed", {"reason": "runtime_setup", "error": str(exc)})
            self._emit(AgentEvent(AgentEventType.ERROR, f"Open Interpreter runtime setup failed: {exc}", "error"))
            return False
        client = self._client_factory(command, runtime_env, process_cwd)
        if not client.start():
            self._trace_record("backend_start_failed", {"reason": "app_server_start"})
            self._emit(AgentEvent(AgentEventType.ERROR, "Open Interpreter App Server failed to start", "error"))
            return False

        self._client = client
        self._config = config
        self._thread_id = None
        self._turn_id = None
        try:
            client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "local_ai_agent",
                        "title": "Local_AI_Agent",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": False},
                },
                timeout=10.0,
            )
            if not client.notify("initialized", {}):
                raise RuntimeError("failed to send initialized notification")
            thread_params = self._thread_params(config)
            self._trace_record("thread_starting", thread_params, detailed=True)
            result = client.request("thread/start", thread_params, timeout=20.0)
            thread = result.get("thread") or {}
            thread_id = thread.get("id")
            if not thread_id:
                raise RuntimeError("thread/start returned no thread id")
            self._thread_id = str(thread_id)
        except Exception as exc:
            self._trace_record("backend_start_failed", {"reason": "initialization", "error": str(exc)})
            self._emit(AgentEvent(AgentEventType.ERROR, f"Open Interpreter initialization failed: {exc}", "error"))
            client.stop(timeout=2.0)
            self._client = None
            return False

        self._register_cleanup()
        self._trace_record("session_started", {"session_id": self._thread_id, "resumed": False})
        self._emit(AgentEvent(AgentEventType.STARTED, "Open Interpreter App Server started", "info"))
        self._emit(AgentEvent(
            AgentEventType.SESSION_STARTED,
            self._thread_id,
            "info",
            data={"session_id": self._thread_id, "resumed": False},
        ))
        return True

    def _register_cleanup(self) -> None:
        try:
            from launcher.agent import agent_lifecycle
            agent_lifecycle.register(self)
        except Exception:
            pass

        if self._cleanup_registered:
            return
        try:
            from launcher.core import lifelog
            lifelog.register_cleanup(lambda: self.stop(timeout=2.0))
        except Exception:
            pass
        self._cleanup_registered = True

    def send(self, message: str) -> bool:
        client = self._client
        if client is None or not client.is_running() or not self._thread_id or self._turn_id:
            self._trace_record("turn_start_rejected", {"reason": "backend_not_ready_or_busy"})
            return False
        try:
            self._trace_record("turn_starting", {"input": message}, detailed=True)
            result = client.request(
                "turn/start",
                {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": message}],
                },
                timeout=20.0,
            )
            turn = result.get("turn") or {}
            turn_id = turn.get("id")
            if not turn_id:
                self._trace_record("turn_start_failed", {"reason": "missing_turn_id"})
                return False
            self._turn_id = str(turn_id)
            self._trace_record("turn_started", {"input": message}, detailed=True)
            return True
        except Exception as exc:
            self._trace_record("turn_start_failed", {"error": str(exc)})
            self._emit(AgentEvent(AgentEventType.ERROR, f"turn/start failed: {exc}", "error"))
            return False

    def approve(self, request_id: int | str, decision: str) -> bool:
        if decision not in _SIMPLE_APPROVAL_DECISIONS:
            self._trace_record("approval_rejected", {"request_id": request_id, "decision": decision, "reason": "invalid_decision"})
            return False
        client = self._client
        if client is None or not client.is_running():
            self._trace_record("approval_rejected", {"request_id": request_id, "decision": decision, "reason": "backend_not_running"})
            return False
        ok = client.respond(request_id, {"decision": decision})
        self._trace_record("approval_response", {"request_id": request_id, "decision": decision, "sent": ok})
        return ok

    def cancel(self) -> bool:
        client = self._client
        if client is None or not client.is_running() or not self._thread_id or not self._turn_id:
            self._trace_record("turn_interrupt_rejected", {"reason": "no_active_turn"})
            return False
        turn_id = self._turn_id
        try:
            client.request(
                "turn/interrupt",
                {"threadId": self._thread_id, "turnId": turn_id},
                timeout=10.0,
            )
            self._trace_record("turn_interrupted", {"turn_id": turn_id}, turn_id=turn_id)
            self._turn_id = None
            return True
        except Exception as exc:
            self._trace_record("turn_interrupt_failed", {"error": str(exc)}, turn_id=turn_id)
            self._emit(AgentEvent(AgentEventType.ERROR, f"turn/interrupt failed: {exc}", "error"))
            return False

    def resume(self, session_id: str) -> bool:
        client = self._client
        config = self._config
        if client is None or not client.is_running() or config is None or not session_id:
            self._trace_record("session_resume_rejected", {"session_id": session_id})
            return False
        if self._turn_id:
            self._trace_record("session_resume_rejected", {"session_id": session_id, "reason": "turn_active"})
            return False
        params = self._thread_params(config)
        params["threadId"] = session_id
        try:
            self._trace_record("session_resuming", {"session_id": session_id})
            result = client.request("thread/resume", params, timeout=20.0)
            thread = result.get("thread") or {}
            thread_id = thread.get("id") or session_id
            self._thread_id = str(thread_id)
            self._trace_record("session_started", {"session_id": self._thread_id, "resumed": True})
            self._emit(AgentEvent(
                AgentEventType.SESSION_STARTED,
                self._thread_id,
                "info",
                data={"session_id": self._thread_id, "resumed": True},
            ))
            return True
        except Exception as exc:
            self._trace_record("session_resume_failed", {"session_id": session_id, "error": str(exc)})
            self._emit(AgentEvent(AgentEventType.ERROR, f"thread/resume failed: {exc}", "error"))
            return False

    def session_id(self) -> str | None:
        return self._thread_id

    def stop(self, timeout: float = 3.0) -> None:
        thread_id = self._thread_id
        turn_id = self._turn_id
        self._flush_stream_counts(turn_id)
        self._trace_record("backend_stopping", {"timeout": timeout}, turn_id=turn_id)
        if self._turn_id:
            self.cancel()
        client = self._client
        if client is not None:
            client.stop(timeout=timeout)
        self._trace_record("backend_stopped", {"thread_id": thread_id}, turn_id=turn_id)
        self._client = None
        self._turn_id = None
        self._thread_id = None
        trace, self._trace = self._trace, None
        if trace is not None:
            try:
                trace.close()
            except Exception:
                pass
        try:
            from launcher.agent import agent_lifecycle
            agent_lifecycle.unregister(self)
        except Exception:
            pass

    def is_running(self) -> bool:
        return self._client is not None and self._client.is_running()

    def poll_events(self, max_n: int = 200) -> list[AgentEvent]:
        out: list[AgentEvent] = []
        for _ in range(max_n):
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        remaining = max(0, max_n - len(out))
        if remaining and self._client is not None:
            for message in self._client.drain_messages(remaining):
                event = self._map_message(message)
                if event is not None:
                    out.append(event)
        return out

    def _emit(self, event: AgentEvent) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:
            try:
                self._events.get_nowait()
                self._events.put_nowait(event)
            except queue.Empty:
                pass

    def _map_message(self, message: dict) -> AgentEvent | None:
        method = str(message.get("method") or "")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        current_turn_id = self._turn_id
        if method in _STREAM_DELTA_METHODS:
            # These arrive once per streamed token. Writing a trace row for each
            # one duplicates content that item/completed already carries and
            # dominates the cost of streaming, so only their volume is kept.
            self._stream_deltas[method] = self._stream_deltas.get(method, 0) + 1
        else:
            self._trace_record(
                "oi_notification",
                {"method": method, "params": params},
                turn_id=current_turn_id,
                detailed=True,
            )

        if method == "item/agentMessage/delta":
            return AgentEvent(AgentEventType.TEXT_DELTA, str(params.get("delta") or ""), "stdout", data=params)
        if method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            return AgentEvent(AgentEventType.REASONING, str(params.get("delta") or ""), "info", data=params)
        if method == "item/commandExecution/outputDelta":
            return AgentEvent(AgentEventType.TOOL_PROGRESS, str(params.get("delta") or ""), "system", data=params)
        if method == "item/started":
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            item_type = str(item.get("type") or "tool")
            if item_type == "mcpToolCall":
                self._trace_record("mcp_tool_started", item, turn_id=current_turn_id, detailed=True)
            else:
                self._trace_record("tool_started", item, turn_id=current_turn_id, detailed=True)
            content = str(item.get("command") or item.get("tool") or item_type)
            return AgentEvent(AgentEventType.TOOL_STARTED, content, "system", data=params)
        if method == "item/completed":
            item = params.get("item") if isinstance(params.get("item"), dict) else {}
            item_type = str(item.get("type") or "tool")
            if item_type == "mcpToolCall":
                self._trace_record("mcp_tool_completed", item, turn_id=current_turn_id, detailed=True)
            else:
                self._trace_record("tool_completed", item, turn_id=current_turn_id, detailed=True)
            if item_type == "fileChange":
                return AgentEvent(AgentEventType.FILE_CHANGED, "File changes completed", "system", data=params)
            if item_type == "agentMessage":
                return None
            content = str(item.get("command") or item.get("tool") or item_type)
            return AgentEvent(AgentEventType.TOOL_COMPLETED, content, "system", data=params)
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            kind = "command" if "commandExecution" in method else "file_change"
            reason = str(params.get("reason") or "Approval required")
            data = dict(params)
            data["kind"] = kind
            self._trace_record(
                "approval_required",
                {"request_id": message.get("id"), "kind": kind, "params": data},
                turn_id=current_turn_id,
                detailed=True,
            )
            return AgentEvent(
                AgentEventType.APPROVAL_REQUIRED,
                reason,
                "approval",
                request_id=message.get("id"),
                data=data,
            )
        if method == "turn/completed":
            self._flush_stream_counts(current_turn_id)
            self._trace_record("turn_completed", params, turn_id=current_turn_id, detailed=True)
            self._turn_id = None
            return AgentEvent(AgentEventType.STATUS, "Turn completed", "info", data=params)
        if method == "local/stderr":
            return AgentEvent(AgentEventType.WARNING, str(params.get("text") or ""), "warn", data=params)
        if method == "local/protocolError":
            self._trace_record("protocol_error", params, turn_id=current_turn_id)
            return AgentEvent(AgentEventType.ERROR, str(params.get("text") or "Protocol error"), "error", data=params)
        if method == "local/terminated":
            self._flush_stream_counts(current_turn_id)
            self._trace_record("app_server_terminated", params, turn_id=current_turn_id)
            self._turn_id = None
            return AgentEvent(
                AgentEventType.TERMINATED,
                f"Open Interpreter process exited (rc={params.get('returncode')})",
                "terminated",
                data=params,
            )
        if method == "error":
            self._trace_record("app_server_error", params, turn_id=current_turn_id)
            return AgentEvent(AgentEventType.ERROR, str(params.get("message") or params), "error", data=params)
        if method:
            return AgentEvent(AgentEventType.STATUS, method, "info", data=params)
        return None
