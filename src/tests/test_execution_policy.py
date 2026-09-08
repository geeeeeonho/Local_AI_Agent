from pathlib import Path

import pytest


def test_host_policy_is_user_reviewed_workspace_write():
    from launcher.agent.execution_policy import policy_for_mode

    policy = policy_for_mode("host")
    assert policy.approval_policy == "on-request"
    assert policy.approvals_reviewer == "user"
    assert policy.sandbox_mode == "workspace-write"


def test_sandbox_policy_keeps_docker_as_outer_boundary():
    from launcher.agent.execution_policy import policy_for_mode

    policy = policy_for_mode("sandbox")
    assert policy.approval_policy == "on-request"
    assert policy.approvals_reviewer == "user"
    assert policy.sandbox_mode == "danger-full-access"


def test_unknown_execution_mode_is_rejected():
    from launcher.agent.execution_policy import policy_for_mode

    with pytest.raises(ValueError):
        policy_for_mode("legacy")


def test_policy_literals_live_in_one_runtime_module():
    root = Path(__file__).resolve().parents[1] / "launcher" / "agent"
    policy = (root / "execution_policy.py").read_text(encoding="utf-8")
    host = (root / "interpreter_backend.py").read_text(encoding="utf-8")
    sandbox = (root / "sandbox_backend.py").read_text(encoding="utf-8")

    assert '"on-request"' in policy
    assert '"workspace-write"' in policy
    assert '"danger-full-access"' in policy
    assert '"on-request"' not in host
    assert '"workspace-write"' not in host
    assert '"danger-full-access"' not in sandbox
