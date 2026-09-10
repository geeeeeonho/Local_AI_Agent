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
MANAGED_HOST_RELAYS = {
    "tor_socks_9050": 9050,
    "tor_http_8118": 8118,
    "warp_socks_1080": 1080,
    "warp_http_8119": 8119,
    "searxng_8888": 8888,
}


@dataclass(frozen=True)
class ProbeVerdict:
    public_egress_blocked: bool
    host_service_reachable: bool | None
    managed_relays_blocked: bool
    ok: bool
    host_message: str
    relay_message: str


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
        "import ipaddress, json, socket",
        "PUBLIC_IP = %r" % PUBLIC_IP,
        "PUBLIC_PORT = %d" % PUBLIC_PORT,
        "HOST = 'host.docker.internal'",
        "def recvn(sock, n):",
        "    data = b''",
        "    while len(data) < n:",
        "        chunk = sock.recv(n - len(data))",
        "        if not chunk: raise OSError('short read')",
        "        data += chunk",
        "    return data",
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
        "def socks5_connect_public(port, timeout=3.0):",
        "    s = None",
        "    try:",
        "        s = socket.create_connection((HOST, port), timeout=timeout)",
        "        s.settimeout(timeout)",
        "        s.sendall(b'\\x05\\x01\\x00')",
        "        if recvn(s, 2) != b'\\x05\\x00': return False",
        "        addr = ipaddress.ip_address(PUBLIC_IP).packed",
        "        s.sendall(b'\\x05\\x01\\x00\\x01' + addr + PUBLIC_PORT.to_bytes(2, 'big'))",
        "        reply = recvn(s, 4)",
        "        return reply[0] == 5 and reply[1] == 0",
        "    except Exception:",
        "        return False",
        "    finally:",
        "        try:",
        "            if s: s.close()",
        "        except Exception: pass",
        "def http_connect_public(port, timeout=3.0):",
        "    s = None",
        "    try:",
        "        s = socket.create_connection((HOST, port), timeout=timeout)",
        "        s.settimeout(timeout)",
        "        target = PUBLIC_IP + ':' + str(PUBLIC_PORT)",
        "        req = ('CONNECT ' + target + ' HTTP/1.1\\r\\nHost: ' + target + '\\r\\n\\r\\n').encode('ascii')",
        "        s.sendall(req)",
        "        head = s.recv(256).split(b'\\r\\n', 1)[0]",
        "        return b' 200 ' in head or head.endswith(b' 200')",
        "    except Exception:",
        "        return False",
        "    finally:",
        "        try:",
        "            if s: s.close()",
        "        except Exception: pass",
        "result = {",
        "    'host_service': %s," % host_expr,
        "    'public_ip_tcp': can_connect(PUBLIC_IP, PUBLIC_PORT),",
        "    'public_dns': can_resolve(%r)," % PUBLIC_DNS_NAME,
        "    'managed_host_relays': {",
        "        'tor_socks_9050': socks5_connect_public(9050),",
        "        'tor_http_8118': http_connect_public(8118),",
        "        'warp_socks_1080': socks5_connect_public(1080),",
        "        'warp_http_8119': http_connect_public(8119),",
        "        'searxng_8888': can_connect(HOST, 8888),",
        "    },",
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
        "--dns=0.0.0.0",
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

    raw_relays = result.get("managed_host_relays")
    relays = raw_relays if isinstance(raw_relays, Mapping) else {}
    reachable_relays = sorted(str(name) for name, value in relays.items() if bool(value))
    relays_blocked = not reachable_relays
    relay_message = (
        "Managed Host relay endpoints cannot provide public egress from Block."
        if relays_blocked
        else "Reachable managed Host relay paths: " + ", ".join(reachable_relays)
    )

    return ProbeVerdict(
        public_egress_blocked=blocked,
        host_service_reachable=host_reachable,
        managed_relays_blocked=relays_blocked,
        ok=blocked and host_ok and relays_blocked,
        host_message=host_message,
        relay_message=relay_message,
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
        probed = _run(cmd, timeout=30)
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
    print(
        "[OK]" if verdict.managed_relays_blocked else "[FAIL]",
        verdict.relay_message,
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
