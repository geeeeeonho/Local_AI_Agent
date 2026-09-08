"""Single source of truth for Open Interpreter execution/approval policy."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    approval_policy: str
    approvals_reviewer: str
    sandbox_mode: str


_POLICIES = {
    "host": ExecutionPolicy(
        approval_policy="on-request",
        approvals_reviewer="user",
        sandbox_mode="workspace-write",
    ),
    "sandbox": ExecutionPolicy(
        approval_policy="on-request",
        approvals_reviewer="user",
        sandbox_mode="danger-full-access",
    ),
}


def policy_for_mode(mode: str) -> ExecutionPolicy:
    """Return the explicit OI policy for one supported execution boundary."""
    key = str(mode or "").strip().lower()
    try:
        return _POLICIES[key]
    except KeyError as exc:
        raise ValueError("unsupported execution mode: %s" % (mode,)) from exc


__all__ = ["ExecutionPolicy", "policy_for_mode"]
