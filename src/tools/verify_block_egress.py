"""Opt-in Docker Desktop diagnostic for the managed Block network.

Hosted unit tests verify only this module's command and verdict contracts. Run
this tool on the target Windows/Docker Desktop machine to prove the *real*
network boundary:

    python -m tools.verify_block_egress --image llm-agent-sandbox

The diagnostic deliberately performs no package installation. It expects the
sandbox image to provide Python, which is already required by the agent image.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Mapping

from launcher import network_policy

PUBLIC_IP = "1.1.1.1"
PUBLIC_PORT = 443
PUBLIC_DNS_NAME = "example.com"


@dataclass(frozen=True)
class ProbeVerdict:
    public_egress_blocked: bool
    host_service_reachable: bool | None
    ok: bool
    host_message: str


def build_network_inspect_command(network_name: str | None = None) -> list[str]:
    name = network_name or network_policy.block_network_name()
    return [
        "docker", "network", "inspect", "--format",
        "{{.Internal}}|{{.Driver}}", name,
    ]


def _probe_script(ollama_port: int, skip_host_probe: bool) -> str:
    """Return a stdlib-only Python probe executed inside the Block network."""
    host_expr = "None" if skip_host_probe else (
        "can_connect('host.docker.internal', %d)" % int(ollama_port)
    )
    return "\n".join([
        "import json, socket",
        "def can_connect(host, port, timeout=2.0):",
        "    try:",
        "        s = socket.create_connection((host, port), timeout=timeout)",
        "        s.close()",
        "        return True",
        "    except Exception:",
        "        return False",
        "def can_resolve(host):",
        "    try:",
        "        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)",
        "        return True",
        "    except Exception:",
        "        return False",
        "result = {",
        "    'host_service': %s," % host_expr,
        "    'public_ip_tcp': can_connect('%s', %d)," % (PUBLIC_IP, PUBLIC_PORT),
        "    'public_dns': can_resolve('%s')," % PUBLIC_DNS_NAME,
        "}",
        "print(json.dumps(result, sort_keys=True))",
    ])


def build_probe_command(
    image: str,
    ollama_port: int = 11434,
    skip_host_probe: bool = False,
    network_name: str | None = None,
) -> list[str]:
    """Build the one-shot container command used for the real probe."""
    name = network_name or network_policy.block_network_name()
    return [
        "docker", "run", "--rm",
        "--network", name,
        "--add-host", "host.docker.internal:host-gateway",
        "--entrypoint", "python",
        image,
        "-c", _probe_script(ollama_port, skip_host_probe),
    ]


def evaluate_probe_result(result: Mapping[str, object]) -> ProbeVerdict:
    """Interpret probe JSON without performing Docker I/O."""
    public_ip = bool(result.get("public_ip_tcp"))
    public_dns = bool(result.get("public_dns"))
    blocked = not public_ip and not public_dns

    raw_host = result.get("host_service")
    if raw_host is None:
        host_reachable = None
        host_message = (
            "Host service probe skipped; this is not proof that host Ollama "
            "remains reachable from the Block network."
        )
        host_ok = True
    else:
        host_reachable = bool(raw_host)
        host_message = (
            "Host Ollama TCP endpoint is reachable."
            if host_reachable
            else "Host Ollama TCP endpoint is not reachable."
        )
        host_ok = host_reachable

    return ProbeVerdict(
        public_egress_blocked=blocked,
        host_service_reachable=host_reachable,
        ok=blocked and host_ok,
        host_message=host_message,
    )


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_probe_output(stdout: str) -> dict[str, object]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("probe container did not emit a JSON result")


def run_diagnostic(
    image: str,
    ollama_port: int = 11434,
    skip_host_probe: bool = False,
) -> bool:
    """Run the real Docker boundary check and print a human-readable verdict."""
    name = network_policy.block_network_name()
    if not network_policy.ensure_block_network(log=print):
        print("[FAIL] managed Block network could not be prepared safely:", name)
        return False

    try:
        inspected = _run(build_network_inspect_command(name), timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("[FAIL] network inspection failed:", type(exc).__name__)
        return False
    properties = (inspected.stdout or "").strip().lower()
    internal_ok = inspected.returncode == 0 and properties == "true|bridge"
    print("[OK]" if internal_ok else "[FAIL]", "network:", name, properties or "unavailable")
    if not internal_ok:
        return False

    cmd = build_probe_command(
        image=image,
        ollama_port=ollama_port,
        skip_host_probe=skip_host_probe,
        network_name=name,
    )
    try:
        probed = _run(cmd, timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("[FAIL] probe container failed:", type(exc).__name__)
        return False
    if probed.returncode != 0:
        print("[FAIL] probe container exit:", probed.returncode)
        tail = (probed.stderr or probed.stdout or "").strip()
        if tail:
            print(tail[-800:])
        return False

    try:
        result = _parse_probe_output(probed.stdout)
    except ValueError as exc:
        print("[FAIL]", str(exc))
        return False

    verdict = evaluate_probe_result(result)
    print(
        "[OK]" if verdict.public_egress_blocked else "[FAIL]",
        "public raw-IP TCP and public DNS blocked:",
        verdict.public_egress_blocked,
    )
    host_prefix = "[WARN]" if verdict.host_service_reachable is None else (
        "[OK]" if verdict.host_service_reachable else "[FAIL]"
    )
    print(host_prefix, verdict.host_message)
    return verdict.ok


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Local_AI_Agent's real Docker Block egress boundary.",
    )
    parser.add_argument("--image", default="llm-agent-sandbox")
    parser.add_argument("--ollama-port", type=int, default=11434)
    parser.add_argument(
        "--skip-host-probe",
        action="store_true",
        help="Skip the host Ollama TCP check (does not prove host reachability).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return 0 if run_diagnostic(
        image=args.image,
        ollama_port=args.ollama_port,
        skip_host_probe=args.skip_host_probe,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
