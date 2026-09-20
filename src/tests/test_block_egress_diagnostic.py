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
        "managed_host_relays": {},
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
        "managed_host_relays": {},
    })

    assert verdict.public_egress_blocked is True
    assert verdict.host_service_reachable is False
    assert verdict.ok is False


# ── absence of evidence is not evidence of blocking ──────────────────────
# bool(None) is False, so a probe that never ran a check read exactly like
# one that ran it and was refused: evaluate_probe_result({}) returned
# ok=True and the tool printed "public raw-IP TCP and public DNS blocked:
# True" and exited 0. A security check must not pass on a missing answer.

COMPLETE = {"public_ip_tcp": False, "public_dns": False,
            "host_service": True, "managed_host_relays": {}}


def test_a_probe_that_reported_nothing_is_not_a_pass():
    import pytest
    with pytest.raises(ValueError, match="did not report"):
        diagnostic.evaluate_probe_result({})


def test_every_fact_the_verdict_rests_on_must_be_present():
    import pytest
    for key in diagnostic.REQUIRED_PROBE_KEYS:
        partial = {k: v for k, v in COMPLETE.items() if k != key}
        with pytest.raises(ValueError, match=key):
            diagnostic.evaluate_probe_result(partial)


def test_a_non_boolean_answer_is_refused_rather_than_coerced():
    import pytest
    for key, value in [("public_ip_tcp", "no"), ("public_dns", 0),
                       ("host_service", "yes"), ("managed_host_relays", [])]:
        with pytest.raises(ValueError, match=key):
            diagnostic.evaluate_probe_result({**COMPLETE, key: value})


def test_an_unrelated_json_line_is_not_mistaken_for_the_result():
    """Any JSON object used to be accepted, including a stray log line."""
    import json
    import pytest
    with pytest.raises(ValueError, match="complete"):
        diagnostic._parse_probe_output('{"level": "info", "msg": "starting"}\n{}')
    noisy = '{"level": "info"}\n' + json.dumps(COMPLETE) + '\nplain text'
    assert diagnostic._parse_probe_output(noisy) == COMPLETE


def test_a_complete_result_still_evaluates():
    assert diagnostic.evaluate_probe_result(COMPLETE).ok is True
    leaky = {**COMPLETE, "public_dns": True}
    assert diagnostic.evaluate_probe_result(leaky).public_egress_blocked is False
