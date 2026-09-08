from pathlib import Path

from launcher.agent.backend import AgentConfig
from launcher.agent.native_backend import NativeOpenInterpreterBackend


def _config(tmp_path):
    return AgentConfig(
        workspace=tmp_path,
        mode="host",
        model="qwen3:8b",
        network_mode="direct",
        profile_name="coding",
        instructions="coding profile",
    )


def test_host_thread_params_use_permission_profile_not_legacy_sandbox(tmp_path):
    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: None)
    params = backend._thread_params(_config(tmp_path))
    assert "sandbox" not in params
    assert params["config"]["default_permissions"] == "local-ai-host"
    assert params["approvalPolicy"] == "on-request"
    assert params["approvalsReviewer"] == "user"


class FakeClient:
    def __init__(self):
        self.requests = []

    def is_running(self):
        return True

    def request(self, method, params, timeout=None):
        self.requests.append((method, params, timeout))
        return {"thread": {"id": params.get("threadId", "thread-new")}}


def test_host_resume_reapplies_current_permission_profile(tmp_path, monkeypatch):
    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: None)
    backend._config = _config(tmp_path)
    backend._client = FakeClient()
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: True)

    assert backend.resume("thread-old") is True
    method, params, _timeout = backend._client.requests[-1]
    assert method == "thread/resume"
    assert params["threadId"] == "thread-old"
    assert "sandbox" not in params
    assert params["config"]["default_permissions"] == "local-ai-host"


def test_host_resume_fails_closed_if_current_policy_assets_cannot_be_prepared(tmp_path, monkeypatch):
    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: None)
    backend._config = _config(tmp_path)
    backend._client = FakeClient()
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: False)

    assert backend.resume("thread-old") is False
    assert backend._client.requests == []


def test_new_backend_resume_uses_same_current_policy_override(tmp_path, monkeypatch):
    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: None)
    backend._config = _config(tmp_path)
    backend._client = FakeClient()
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: True)

    assert backend.resume("persisted-thread") is True
    params = backend._client.requests[-1][1]
    assert params["config"] == {"default_permissions": "local-ai-host"}
