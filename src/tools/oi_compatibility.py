"""Version-parameterized Open Interpreter compatibility evaluation harness.

This module deliberately does not modify ``runtime_versions.py``. It records a
fail-closed matrix for a separately installed candidate executable so an
upstream release can be evaluated before the product pin changes.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from runtime_versions import OPEN_INTERPRETER_VERSION


REQUIRED_CHECKS = (
    "initialize",
    "thread_start",
    "thread_resume",
    "turn_start",
    "text_streaming",
    "reasoning_streaming",
    "ollama_provider",
    "command_execution",
    "file_write",
    "approval_accept",
    "approval_reject",
    "turn_interrupt",
    "mcp_local_search",
    "warp_environment",
    "tor_environment",
    "direct_mode",
    "block_mode",
    "host_permission_profile",
    "sandbox_docker",
    "session_persistence",
)

_STATUSES = frozenset({"pass", "fail", "not_run"})


@dataclass(frozen=True)
class CheckResult:
    status: str = "not_run"
    detail: str = ""


@dataclass
class CompatibilityReport:
    candidate_version: str
    interpreter_exe: Path
    checks: dict[str, CheckResult] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        candidate_version: str,
        interpreter_exe: Path,
    ) -> "CompatibilityReport":
        return cls(
            candidate_version=str(candidate_version),
            interpreter_exe=Path(interpreter_exe).expanduser().resolve(),
            checks={name: CheckResult() for name in REQUIRED_CHECKS},
        )

    def record(self, name: str, status: str, detail: str = "") -> None:
        check_name = str(name).strip()
        check_status = str(status).strip().lower()
        if check_name not in REQUIRED_CHECKS:
            raise ValueError(f"unknown compatibility check: {check_name}")
        if check_status not in _STATUSES:
            raise ValueError(f"unknown compatibility status: {check_status}")
        self.checks[check_name] = CheckResult(check_status, str(detail))

    @property
    def ok(self) -> bool:
        return all(
            self.checks.get(name, CheckResult()).status == "pass"
            for name in REQUIRED_CHECKS
        )

    def as_dict(self) -> dict:
        counts = {status: 0 for status in ("pass", "fail", "not_run")}
        rows = {}
        for name in REQUIRED_CHECKS:
            result = self.checks.get(name, CheckResult())
            counts[result.status] += 1
            rows[name] = {"status": result.status, "detail": result.detail}
        return {
            "candidate_version": self.candidate_version,
            "interpreter_exe": str(self.interpreter_exe),
            "product_pin": OPEN_INTERPRETER_VERSION,
            "ready_for_version_bump": self.ok,
            "summary": counts,
            "checks": rows,
        }


def build_app_server_command(interpreter_exe: Path) -> list[str]:
    """Build the same App Server command shape as the product backend."""
    return [
        str(Path(interpreter_exe)),
        "-c", "check_for_update_on_startup=false",
        "-c", 'web_search="disabled"',
        "app-server", "--listen", "stdio://",
    ]


def dry_run(*, candidate_version: str, interpreter_exe: Path) -> dict:
    """Return an evaluation plan without starting or installing anything."""
    exe = Path(interpreter_exe).expanduser().resolve()
    return {
        "candidate_version": str(candidate_version),
        "interpreter_exe": str(exe),
        "product_pin": OPEN_INTERPRETER_VERSION,
        "product_pin_unchanged": True,
        "command": build_app_server_command(exe),
        "required_checks": list(REQUIRED_CHECKS),
    }


def parse_result_arg(value: str) -> tuple[str, str, str]:
    """Parse ``CHECK=STATUS[:DETAIL]`` used to attach real-machine evidence."""
    raw = str(value)
    if "=" not in raw:
        raise ValueError("result must use CHECK=STATUS[:DETAIL]")
    name, remainder = raw.split("=", 1)
    status, sep, detail = remainder.partition(":")
    name = name.strip()
    status = status.strip().lower()
    detail = detail.strip() if sep else ""
    if name not in REQUIRED_CHECKS:
        raise ValueError(f"unknown compatibility check: {name}")
    if status not in _STATUSES:
        raise ValueError(f"unknown compatibility status: {status}")
    return name, status, detail


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a separately installed Open Interpreter candidate without "
            "changing Local_AI_Agent's pinned runtime version."
        )
    )
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--interpreter-exe", type=Path, required=True)
    parser.add_argument(
        "--result",
        action="append",
        default=[],
        metavar="CHECK=STATUS[:DETAIL]",
        help="Record one observed matrix result (pass/fail/not_run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the candidate command and required matrix without spawning it.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.dry_run:
        print(json.dumps(dry_run(
            candidate_version=args.candidate_version,
            interpreter_exe=args.interpreter_exe,
        ), ensure_ascii=False, indent=2))
        return 0

    report = CompatibilityReport.create(args.candidate_version, args.interpreter_exe)
    try:
        for raw in args.result:
            report.record(*parse_result_arg(raw))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
