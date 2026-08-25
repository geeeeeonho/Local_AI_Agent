from __future__ import annotations

import datetime as _dt
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

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


def _project_root() -> Path:
    override = os.environ.get("LLM_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent.parent


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


class AgentTrace:
    """Append-only diagnostic trace for observable Agent/Open Interpreter events."""

    def __init__(self, *, mode: str, model: str, network_mode: str, profile_name: str, workspace: Path):
        root = _project_root()
        log_dir = root / "user_data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = log_dir / f"agent_trace_{stamp}_{os.getpid()}.jsonl"
        self.mode = str(mode)
        self.model = str(model)
        self.network_mode = str(network_mode)
        self.profile_name = str(profile_name)
        self.workspace = str(Path(workspace).resolve())
        self._lock = threading.RLock()

    def record(
        self,
        event: str,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        details: Any = None,
    ) -> None:
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
            "details": redact(details),
        }
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8", buffering=1) as fh:
                fh.write(encoded)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
