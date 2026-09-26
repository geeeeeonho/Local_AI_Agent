from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import project_paths

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "client_secret",
}
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(\b(?:api[_-]?key|token|password|passwd|secret)\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(\bBearer\s+)([A-Za-z0-9._~+\-/=]+)"),
)
_MAX_TEXT = 12000

#: How many past trace files to keep. One file is written per agent session and
#: nothing else prunes them, so the trace directory would otherwise grow without
#: bound.
_KEEP_TRACE_FILES = 20

_OMITTED = "[OMITTED: detailed logging disabled]"


def _project_root() -> Path:
    return project_paths.project_root()


def detailed_logging_enabled(project_root: Path | None = None) -> bool:
    """Read the canonical ``logging_enabled`` user setting.

    The settings menu promises that turning logging off stops detailed agent
    input/output from reaching the session log, so the live trace has to honour
    it. Failing open (True) keeps diagnostics available when settings cannot be
    read at all.
    """
    try:
        from launcher import settings_store
        if project_root is None:
            return bool(settings_store.load().logging_enabled)
        return bool(settings_store.load(Path(project_root)).logging_enabled)
    except Exception:
        return True


def _redact_text(value: str) -> str:
    text = value
    for pattern in _SECRET_TEXT_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + "...[TRUNCATED]"
    return text


def redact(value: Any, *, _key: str = "") -> Any:
    if _key.lower() in _SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


def _prune_old_traces(log_dir: Path, keep: int | None = None) -> None:
    # Read the module constant at call time so it stays overridable.
    keep = _KEEP_TRACE_FILES if keep is None else keep
    try:
        existing = sorted(
            log_dir.glob("agent_trace_*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in existing[max(0, keep):]:
        try:
            stale.unlink()
        except OSError:
            pass


class AgentTrace:
    """Append-only diagnostic trace for observable Agent/Open Interpreter events.

    Rows carrying agent input/output are only written when the user has detailed
    logging enabled. Lifecycle and failure rows are always written so that a
    start failure stays diagnosable with logging off.
    """

    def __init__(
        self,
        *,
        mode: str,
        model: str,
        network_mode: str,
        profile_name: str,
        workspace: Path,
        detailed: bool | None = None,
    ):
        log_dir = project_paths.logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        _prune_old_traces(log_dir)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = log_dir / f"agent_trace_{stamp}_{os.getpid()}.jsonl"
        self.mode = str(mode)
        self.model = str(model)
        self.network_mode = str(network_mode)
        self.profile_name = str(profile_name)
        self.workspace = str(Path(workspace).resolve())
        self.detailed = (detailed_logging_enabled() if detailed is None
                         else bool(detailed))
        self._lock = threading.RLock()
        self._handle = None
        self._closed = False

    def _stream(self):
        if self._handle is None and not self._closed:
            self._handle = self.path.open("a", encoding="utf-8")
        return self._handle

    def record(
        self,
        event: str,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        details: Any = None,
        detailed: bool = False,
    ) -> None:
        """Append one trace row.

        ``detailed`` marks a row whose ``details`` carry agent or user payload
        (prompts, model output, commands, tool arguments and results). Those
        payloads are dropped when the user has detailed logging switched off;
        the row itself is still written so the timeline stays readable.
        """
        omit = bool(detailed) and not self.detailed
        row = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "event": str(event),
            "mode": self.mode,
            "model": self.model,
            "network_mode": self.network_mode,
            "profile_name": self.profile_name,
            "workspace": self.workspace,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "details": _OMITTED if omit else redact(details),
        }
        if omit:
            row["detail_omitted"] = True
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            stream = self._stream()
            if stream is None:
                return
            # Flush keeps the row readable by tailing tools straight away. The
            # previous per-row os.fsync() ran once per streamed token, which is
            # prohibitively slow on Windows for a diagnostic log.
            stream.write(encoded)
            stream.flush()

    def close(self) -> None:
        with self._lock:
            handle, self._handle = self._handle, None
            self._closed = True
        if handle is None:
            return
        try:
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass
