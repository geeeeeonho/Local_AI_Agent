from tools import verify_block_egress as diagnostic


def test_network_inspection_targets_the_canonical_block_network(monkeypatch):
    monkeypatch.setattr(diagnostic.network_policy, "block_network_name", lambda: "llm_block_net")

    cmd = diagnostic.build_network_inspect_command()

    assert cmd == [
        "docker", "network", "inspect", "--format",
        "{{.Internal}}|{{.Driver}}", "llm_block_net",
    ]


def test_probe_command_uses_internal_network_host_gateway_and_public_probes(monkeypatch):
    monkeypatch.setattr(diagnostic.network_policy, "block_network_name", lambda: "llm_block_net")

    cmd = diagnostic.build_probe_command(
        image="llm-agent-sandbox",
        ollama_port=11434,
        skip_host_probe=False,
    )

    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("--network") + 1] == "llm_block_net"
    assert "host.docker.internal:host-gateway" in cmd
    assert "llm-agent-sandbox" in cmd
    script = cmd[-1]
    assert "host.docker.internal" in script
    assert "11434" in script
    assert diagnostic.PUBLIC_IP in script
    assert diagnostic.PUBLIC_DNS_NAME in script


def test_skipped_host_probe_is_explicitly_not_counted_as_host_reachability():
    verdict = diagnostic.evaluate_probe_result({
        "host_service": None,
        "public_ip_tcp": False,
        "public_dns": False,
    })

    assert verdict.public_egress_blocked is True
    assert verdict.host_service_reachable is None
    assert verdict.ok is True
    assert "not proof" in verdict.host_message.lower()


def test_required_host_probe_must_succeed_for_overall_verdict():
    verdict = diagnostic.evaluate_probe_result({
        "host_service": False,
        "public_ip_tcp": False,
        "public_dns": False,
    })

    assert verdict.public_egress_blocked is True
    assert verdict.host_service_reachable is False
    assert verdict.ok is False
