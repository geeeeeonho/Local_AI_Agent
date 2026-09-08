from pathlib import Path
from types import SimpleNamespace

import pytest


class Presenter:
    def __init__(self):
        self.messages = []

    def info(self, text):
        self.messages.append(("info", str(text)))

    def warn(self, text):
        self.messages.append(("warn", str(text)))

    def error(self, text):
        self.messages.append(("error", str(text)))


def _profile():
    return SimpleNamespace(name="coding", system_message="coding profile")


def test_action_delegates_runtime_service_ownership_to_coordinator():
    root = Path(__file__).resolve().parents[1]
    action = (root / "launcher/actions/agent_chat.py").read_text(encoding="utf-8")
    coordinator = (root / "launcher/agent/runtime_coordinator.py").read_text(encoding="utf-8")

    assert "launcher.agent.runtime_coordinator" in action
    for forbidden in (
        "AgentService(",
        "create_backend(",
        "AgentConfig(",
        "ProcessRuntimeSpec(",
        "DockerService.ensure_daemon",
        "network_policy.prepare_runtime",
        "network_policy.ensure_block_network",
        "searxng_runtime.start",
        "OllamaService(",
    ):
        assert forbidden not in action
    for required in (
        "class RuntimeCoordinator",
        "AgentService(",
        "create_backend(",
        "AgentConfig(",
        "ProcessRuntimeSpec(",
        "def prepare_runtime(",
    ):
        assert required in coordinator


def test_prepare_runtime_warp_failure_is_fail_closed(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_coordinator

    presenter = Presenter()
    monkeypatch.setattr(runtime_coordinator, "_ensure_ollama", lambda env, p: True)

    class Docker:
        @staticmethod
        def ensure_daemon(**kwargs):
            return True

        @staticmethod
        def daemon_alive():
            return True

    monkeypatch.setattr(runtime_coordinator, "DockerService", Docker)
    monkeypatch.setattr(network_policy, "prepare_runtime", lambda *args, **kwargs: False)

    assert runtime_coordinator.prepare_runtime(
        tmp_path, presenter, "host", network_policy.NetworkMode.WARP
    ) is False
    assert any("우회하지 않습니다" in text for _level, text in presenter.messages)


def test_prepare_runtime_rejects_host_block_before_network_start(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_coordinator

    presenter = Presenter()
    monkeypatch.setattr(runtime_coordinator, "_ensure_ollama", lambda env, p: True)
    called = []
    monkeypatch.setattr(
        network_policy,
        "ensure_block_network",
        lambda **kwargs: called.append(True) or True,
    )

    assert runtime_coordinator.prepare_runtime(
        tmp_path, presenter, "host", network_policy.NetworkMode.BLOCK
    ) is False
    assert called == []


def test_coordinator_builds_current_host_config_with_proxy_env(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_coordinator

    service = SimpleNamespace()
    monkeypatch.setattr(
        network_policy,
        "host_proxy_env",
        lambda mode: {"ALL_PROXY": "socks5://127.0.0.1:40000"},
    )
    coordinator = runtime_coordinator.RuntimeCoordinator(
        env=tmp_path / "env",
        profile=_profile(),
        workspace=tmp_path / "workspace",
        mode="host",
        selected_network=network_policy.NetworkMode.TOR,
        model_tag="qwen3:8b",
        run_mem="2g",
        run_cpus="1",
        command=["managed-open-interpreter"],
        service=service,
    )

    config = coordinator.config_for_current()
    assert config.mode == "host"
    assert config.model == "qwen3:8b"
    assert config.network_mode == "tor"
    assert config.runtime_spec.env["ALL_PROXY"].startswith("socks5://")
    assert config.runtime_spec.cwd == (tmp_path / "workspace")


def test_restart_model_rolls_back_if_replacement_start_fails(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_coordinator

    class Service:
        def __init__(self):
            self.starts = []
            self.stops = 0

        def stop(self, timeout=2.0):
            self.stops += 1

        def start(self, config):
            self.starts.append(config.model)
            return len(self.starts) > 1

    service = Service()
    coordinator = runtime_coordinator.RuntimeCoordinator(
        env=tmp_path / "env",
        profile=_profile(),
        workspace=tmp_path / "workspace",
        mode="host",
        selected_network=network_policy.NetworkMode.DIRECT,
        model_tag="old:8b",
        run_mem="2g",
        run_cpus="1",
        command=["managed-open-interpreter"],
        service=service,
    )

    assert coordinator.restart_model("new:8b") is False
    assert coordinator.model_tag == "old:8b"
    assert service.starts == ["new:8b", "old:8b"]


def test_stop_service_prefers_host_turn_cancel(monkeypatch, tmp_path):
    from launcher import network_policy
    from launcher.agent import runtime_coordinator

    class Service:
        def __init__(self):
            self.stops = 0

        def cancel(self):
            return True

        def stop(self, timeout=2.0):
            self.stops += 1

    service = Service()
    coordinator = runtime_coordinator.RuntimeCoordinator(
        env=tmp_path / "env",
        profile=_profile(),
        workspace=tmp_path / "workspace",
        mode="host",
        selected_network=network_policy.NetworkMode.DIRECT,
        model_tag="qwen3:8b",
        run_mem="2g",
        run_cpus="1",
        command=["managed-open-interpreter"],
        service=service,
    )

    assert coordinator.stop_service() == "cancelled"
    assert service.stops == 0
