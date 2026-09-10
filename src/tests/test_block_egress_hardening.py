from types import SimpleNamespace

import pytest


def _result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_block_quiesce_stops_all_managed_egress_relays(monkeypatch):
    from launcher import config, network_policy
    from launcher.services import docker as docker_module

    running = {
        str(config.SEARXNG_CONTAINER),
        str(config.HTTP_BRIDGE_CONTAINER),
        str(config.WARP_CONTAINER),
        str(config.TOR_CONTAINER),
    }
    stopped = []

    class Docker:
        @staticmethod
        def run(args, **kwargs):
            assert args[0:2] == ["ps", "--filter"]
            token = args[2]
            name = token[len("name=^"):-1]
            return _result(stdout=(name + "\n") if name in running else "")

        @staticmethod
        def stop_container(name, timeout=5):
            stopped.append(name)
            running.discard(name)
            return True

    monkeypatch.setattr(docker_module, "DockerService", Docker)

    assert network_policy.quiesce_block_relays() is True
    assert set(stopped) == {
        str(config.SEARXNG_CONTAINER),
        str(config.HTTP_BRIDGE_CONTAINER),
        str(config.WARP_CONTAINER),
        str(config.TOR_CONTAINER),
    }
    assert running == set()


def test_block_quiesce_fails_closed_when_relay_state_cannot_be_proven(monkeypatch):
    from launcher import network_policy
    from launcher.services import docker as docker_module

    class Docker:
        @staticmethod
        def run(args, **kwargs):
            return None

        @staticmethod
        def stop_container(name, timeout=5):
            pytest.fail("stop must not run when relay state inspection itself failed")

    monkeypatch.setattr(docker_module, "DockerService", Docker)

    assert network_policy.quiesce_block_relays() is False


def test_production_block_network_preparation_aborts_when_relay_quiesce_fails(monkeypatch):
    from launcher import network_policy
    from launcher.services import docker as docker_module

    monkeypatch.setattr(network_policy, "quiesce_block_relays", lambda **kwargs: False)

    class Docker:
        @staticmethod
        def network_inspect(*args, **kwargs):
            pytest.fail("Block network inspection must not run after relay cleanup failure")

    monkeypatch.setattr(docker_module, "DockerService", Docker)

    assert network_policy.ensure_block_network() is False


def test_block_probe_rejects_reachable_managed_host_relay():
    from tools import verify_block_egress as diagnostic

    verdict = diagnostic.evaluate_probe_result({
        "host_service": True,
        "public_ip_tcp": False,
        "public_dns": False,
        "managed_host_relays": {
            "tor_socks_9050": True,
            "tor_http_8118": False,
            "warp_socks_1080": False,
            "warp_http_8119": False,
            "searxng_8888": False,
        },
    })

    assert verdict.public_egress_blocked is True
    assert verdict.managed_relays_blocked is False
    assert verdict.ok is False
    assert "tor_socks_9050" in verdict.relay_message


def test_block_probe_accepts_clean_managed_relay_surface():
    from tools import verify_block_egress as diagnostic

    verdict = diagnostic.evaluate_probe_result({
        "host_service": True,
        "public_ip_tcp": False,
        "public_dns": False,
        "managed_host_relays": {
            "tor_socks_9050": False,
            "tor_http_8118": False,
            "warp_socks_1080": False,
            "warp_http_8119": False,
            "searxng_8888": False,
        },
    })

    assert verdict.public_egress_blocked is True
    assert verdict.managed_relays_blocked is True
    assert verdict.ok is True


def test_block_probe_command_matches_runtime_dns_guard_and_relay_probes(monkeypatch):
    from tools import verify_block_egress as diagnostic

    monkeypatch.setattr(diagnostic.network_policy, "block_network_name", lambda: "llm_block_net")
    cmd = diagnostic.build_probe_command(image="llm-agent-sandbox")

    assert "--dns=0.0.0.0" in cmd
    script = cmd[-1]
    for marker in (
        "tor_socks_9050",
        "tor_http_8118",
        "warp_socks_1080",
        "warp_http_8119",
        "searxng_8888",
    ):
        assert marker in script
