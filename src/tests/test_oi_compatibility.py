import json
from pathlib import Path

from tools import oi_compatibility as compat


def test_candidate_command_uses_supplied_executable_without_product_pin(tmp_path):
    exe = tmp_path / "candidate" / "interpreter.exe"
    cmd = compat.build_app_server_command(exe)
    assert cmd[0] == str(exe)
    assert cmd[-3:] == ["app-server", "--listen", "stdio://"]
    assert "0.0.38" not in " ".join(cmd)


def test_required_matrix_covers_transition_contract():
    expected = {
        "initialize", "thread_start", "thread_resume", "turn_start",
        "text_streaming", "reasoning_streaming", "ollama_provider",
        "command_execution", "file_write", "approval_accept",
        "approval_reject", "turn_interrupt", "mcp_local_search", "fetch_page",
        "warp_environment", "tor_environment", "direct_mode", "block_mode",
        "host_permission_profile", "sandbox_docker", "session_persistence",
    }
    assert set(compat.REQUIRED_CHECKS) == expected


def test_report_fails_closed_until_every_required_check_passes(tmp_path):
    report = compat.CompatibilityReport.create(
        candidate_version="0.0.42",
        interpreter_exe=tmp_path / "candidate.exe",
    )
    assert report.ok is False
    assert report.as_dict()["summary"]["not_run"] == len(compat.REQUIRED_CHECKS)

    for name in compat.REQUIRED_CHECKS:
        report.record(name, "pass", "verified")
    assert report.ok is True
    assert report.as_dict()["summary"] == {
        "pass": len(compat.REQUIRED_CHECKS),
        "fail": 0,
        "not_run": 0,
    }


def test_any_failed_or_not_run_required_check_blocks_version_bump(tmp_path):
    report = compat.CompatibilityReport.create("0.0.42", tmp_path / "candidate.exe")
    for name in compat.REQUIRED_CHECKS:
        report.record(name, "pass")
    report.record("block_mode", "fail", "raw IP escaped")
    assert report.ok is False
    report.record("block_mode", "not_run", "Docker unavailable")
    assert report.ok is False


def test_unknown_check_or_status_is_rejected(tmp_path):
    report = compat.CompatibilityReport.create("0.0.42", tmp_path / "candidate.exe")
    for name, status in (("made_up", "pass"), ("initialize", "maybe")):
        try:
            report.record(name, status)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown checks/statuses must be rejected")


def test_dry_run_reports_candidate_provenance_without_spawning(tmp_path):
    exe = tmp_path / "candidate.exe"
    result = compat.dry_run(candidate_version="0.0.42", interpreter_exe=exe)
    assert result["candidate_version"] == "0.0.42"
    assert result["interpreter_exe"] == str(exe.resolve())
    assert result["product_pin_unchanged"] is True
    assert result["required_checks"] == list(compat.REQUIRED_CHECKS)


def test_result_argument_parser_preserves_detail():
    name, status, detail = compat.parse_result_arg("initialize=pass:stdio handshake ok")
    assert (name, status, detail) == ("initialize", "pass", "stdio handshake ok")


def test_cli_dry_run_emits_json_and_does_not_require_existing_candidate(tmp_path, capsys):
    exe = tmp_path / "future.exe"
    code = compat.main([
        "--candidate-version", "0.0.42",
        "--interpreter-exe", str(exe),
        "--dry-run",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_version"] == "0.0.42"
    assert payload["product_pin_unchanged"] is True
