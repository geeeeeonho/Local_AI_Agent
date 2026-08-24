from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class AgentEventType(str, Enum):
    TEXT = "text"
    STATUS = "status"
    WARNING = "warning"
    ERROR = "error"
    TERMINATED = "terminated"
    STARTED = "started"
    SESSION_STARTED = "session_started"
    TEXT_DELTA = "text_delta"
    REASONING = "reasoning"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    FILE_CHANGED = "file_changed"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    content: str
    source_level: str | None = None
    request_id: int | str | None = None
    data: Mapping[str, Any] | None = None


_LEGACY_TYPES = {
    "stdout": AgentEventType.TEXT,
    "stderr": AgentEventType.ERROR,
    "info": AgentEventType.STATUS,
    "warn": AgentEventType.WARNING,
    "error": AgentEventType.ERROR,
    "terminated": AgentEventType.TERMINATED,
}


def from_legacy_message(message: Any) -> AgentEvent:
    level = str(getattr(message, "level", ""))
    text = str(getattr(message, "text", ""))
    return AgentEvent(
        type=_LEGACY_TYPES.get(level, AgentEventType.STATUS),
        content=text,
        source_level=level,
    )
