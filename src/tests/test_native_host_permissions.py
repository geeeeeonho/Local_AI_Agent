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
    def __init__(self, *, stop_ok=True, start_ok=True, initialize_ok=True):
        self.requests = []
        self.notifications = []
        self.stop_calls = 0
        self.start_calls = 0
        self.stop_ok = stop_ok
        self.start_ok = start_ok
        self.initialize_ok = initialize_ok
        self.running = True

    def is_running(self):
        return self.running

    def start(self):
        self.start_calls += 1
        self.running = self.start_ok
        return self.start_ok

    def stop(self, timeout=3.0):
        self.stop_calls += 1
        if self.stop_ok:
            self.running = False
        return self.stop_ok

    def notify(self, method, params):
        self.notifications.append((method, params))
        return True

    def request(self, method, params, timeout=None):
        self.requests.append((method, params, timeout))
        if method == "initialize":
            if not self.initialize_ok:
                raise RuntimeError("initialize failed")
            return {}
        return {"thread": {"id": params.get("threadId", "thread-new")}}


def _running_backend(tmp_path, old_client, *, fingerprint="fp-a", factory=None):
    backend = NativeOpenInterpreterBackend(client_factory=factory or (lambda *args: FakeClient()))
    backend._config = _config(tmp_path)
    backend._client = old_client
    backend._host_process_policy_fingerprint = fingerprint
    backend._thread_id = "thread-old"
    return backend


def _stub_restart_spec(monkeypatch, backend, tmp_path):
    monkeypatch.setattr(
        backend,
        "_host_process_client_spec",
        lambda config: (["interpreter", "app-server"], {}, Path(tmp_path)),
    )


def test_host_resume_same_fingerprint_reuses_process_and_reapplies_profile(tmp_path, monkeypatch):
    old_client = FakeClient()
    backend = _running_backend(tmp_path, old_client, fingerprint="fp-current")
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-current")

    assert backend.resume("thread-old") is True
    assert old_client.stop_calls == 0
    method, params, _timeout = old_client.requests[-1]
    assert method == "thread/resume"
    assert params["threadId"] == "thread-old"
    assert "sandbox" not in params
    assert params["config"]["default_permissions"] == "local-ai-host"


def test_host_resume_changed_fingerprint_restarts_before_resume(tmp_path, monkeypatch):
    old_client = FakeClient()
    new_client = FakeClient()
    backend = _running_backend(
        tmp_path,
        old_client,
        fingerprint="fp-old",
        factory=lambda *args: new_client,
    )
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-new")
    _stub_restart_spec(monkeypatch, backend, tmp_path)

    assert backend.resume("thread-old") is True
    assert old_client.stop_calls == 1
    assert new_client.start_calls == 1
    assert [method for method, _params, _timeout in new_client.requests] == [
        "initialize",
        "thread/resume",
    ]
    resume_params = new_client.requests[-1][1]
    assert resume_params["threadId"] == "thread-old"
    assert resume_params["config"] == {"default_permissions": "local-ai-host"}
    assert backend._host_process_policy_fingerprint == "fp-new"
    assert backend._host_policy_quarantined is False


def test_host_resume_unknown_process_fingerprint_forces_restart(tmp_path, monkeypatch):
    old_client = FakeClient()
    new_client = FakeClient()
    backend = _running_backend(
        tmp_path,
        old_client,
        fingerprint=None,
        factory=lambda *args: new_client,
    )
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-current")
    _stub_restart_spec(monkeypatch, backend, tmp_path)

    assert backend.resume("persisted-thread") is True
    assert old_client.stop_calls == 1
    assert new_client.requests[-1][0] == "thread/resume"


def test_host_resume_fails_closed_if_current_policy_assets_cannot_be_prepared(tmp_path, monkeypatch):
    old_client = FakeClient()
    backend = _running_backend(tmp_path, old_client)
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: None)

    assert backend.resume("thread-old") is False
    assert old_client.stop_calls == 0
    assert old_client.requests == []


def test_host_resume_fails_closed_if_old_process_will_not_stop(tmp_path, monkeypatch):
    old_client = FakeClient(stop_ok=False)
    created = []
    backend = _running_backend(
        tmp_path,
        old_client,
        fingerprint="fp-old",
        factory=lambda *args: created.append(FakeClient()) or created[-1],
    )
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-new")
    _stub_restart_spec(monkeypatch, backend, tmp_path)

    assert backend.resume("thread-old") is False
    assert old_client.stop_calls == 1
    assert created == []
    assert old_client.requests == []
    assert backend._host_policy_quarantined is True
    assert backend.is_running() is False
    assert backend.send("must not run") is False
    assert backend.approve(99, "accept") is False
    assert backend.cancel() is False
    assert old_client.requests == []


def test_host_resume_fails_closed_if_new_process_cannot_start(tmp_path, monkeypatch):
    old_client = FakeClient()
    new_client = FakeClient(start_ok=False)
    backend = _running_backend(
        tmp_path,
        old_client,
        fingerprint="fp-old",
        factory=lambda *args: new_client,
    )
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-new")
    _stub_restart_spec(monkeypatch, backend, tmp_path)

    assert backend.resume("thread-old") is False
    assert old_client.stop_calls == 1
    assert new_client.start_calls == 1
    assert not any(method == "thread/resume" for method, _params, _timeout in new_client.requests)
    assert backend._client is None
    assert backend._host_policy_quarantined is True


def test_host_resume_fails_closed_if_new_process_initialize_fails(tmp_path, monkeypatch):
    old_client = FakeClient()
    new_client = FakeClient(initialize_ok=False)
    backend = _running_backend(
        tmp_path,
        old_client,
        fingerprint="fp-old",
        factory=lambda *args: new_client,
    )
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-new")
    _stub_restart_spec(monkeypatch, backend, tmp_path)

    assert backend.resume("thread-old") is False
    assert old_client.stop_calls == 1
    assert new_client.stop_calls == 1
    assert not any(method == "thread/resume" for method, _params, _timeout in new_client.requests)
    assert backend._client is None
    assert backend._host_policy_quarantined is True


def test_host_start_records_fingerprint_loaded_by_started_process(tmp_path, monkeypatch):
    client = FakeClient()
    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: client)
    config = _config(tmp_path)
    monkeypatch.setattr(backend, "_runtime_available", lambda config: True)
    monkeypatch.setattr(backend, "_prepare_host_policy_assets", lambda config: "fp-start")
    _stub_restart_spec(monkeypatch, backend, tmp_path)
    monkeypatch.setattr(
        backend,
        "_client_spec",
        lambda config: (
            setattr(backend, "_launch_policy_fingerprint", "fp-start")
            or (["interpreter", "app-server"], {}, Path(tmp_path))
        ),
    )

    assert backend.start(config) is True
    assert backend._host_process_policy_fingerprint == "fp-start"
    assert backend._host_policy_quarantined is False
