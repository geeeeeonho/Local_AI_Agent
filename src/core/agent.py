"""Neutral hand-off from the existing Interpreter integration to shared services."""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AgentBinding:
    coordinator: Any
    controller_factory: Callable
    approval_decider: Callable
    metadata: dict
