"""Opt-in check that every catalogue tag still resolves, with its real size.

The catalogue is hand-maintained against a registry that moves underneath it.
Two entries have already been wrong in exactly this way - ``devstral-small:24b``
was never a library name, and ``qwen3.5:27b`` had to be swapped out - and a tag
that does not resolve fails at ``ollama pull`` time, after the user has chosen
it. Declared sizes drift the same way and are what the memory ladder budgets
against, so a stale number silently changes which model a role loads.

Run it on a machine with internet access:

    set PYTHONPATH=%CD%\\src
    python -m tools.verify_model_catalog
    python -m tools.verify_model_catalog --json

This makes DIRECT outbound HTTPS requests to the Ollama registry. It is a
developer command, never called by the desktop or the installer, and it is not
routed through the managed WARP/Tor/Block policy. Do not run it when the point
of the exercise is that the machine has no public egress.

Only manifests are read; nothing is downloaded, installed or removed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Iterable

from integrations.ollama.client import is_cloud_tag
from launcher.models import model_catalog as catalog

REGISTRY = "https://registry.ollama.ai/v2"
MANIFEST_ACCEPT = ", ".join((
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
))
# A manifest is a small JSON document. Anything larger is not one.
_MAX_BYTES = 1024 * 1024
_GB = 1024 ** 3
# Declared sizes are hand-rounded, so only report a real drift.
DEFAULT_TOLERANCE_GB = 1.0


@dataclass(frozen=True)
class TagReport:
    tag: str
    exists: bool | None          # None = could not be determined
    declared_gb: float
    actual_gb: float | None
    detail: str

    @property
    def drift_gb(self) -> float | None:
        return None if self.actual_gb is None else self.actual_gb - self.declared_gb


def split_tag(tag: str) -> tuple[str, str]:
    """'ns/name:label' or 'name:label' -> (repository path, label)."""
    name, _, label = tag.partition(":")
    label = label or "latest"
    return (name if "/" in name else "library/" + name), label


def _opener():
    # No environment proxy and no cross-host redirect, matching how the rest of
    # the project talks to a network it did not prepare itself.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.URLError("registry redirect refused: " + str(newurl))

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def fetch_manifest(tag: str, *, opener=None, timeout: float = 15) -> tuple[dict | None, str]:
    repository, label = split_tag(tag)
    url = "%s/%s/manifests/%s" % (REGISTRY, repository, label)
    request = urllib.request.Request(url, headers={"Accept": MANIFEST_ACCEPT})
    try:
        with (opener or _opener()).open(request, timeout=timeout) as response:
            raw = response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return None, "HTTP %s" % exc.code
    except Exception as exc:                      # network, TLS, timeout
        return None, "%s: %s" % (type(exc).__name__, exc)
    if len(raw) > _MAX_BYTES:
        return None, "manifest exceeds size limit"
    try:
        document = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        return None, "unreadable manifest: %s" % exc
    return (document, "ok") if isinstance(document, dict) else (None, "manifest is not an object")


def manifest_gb(document: dict) -> float | None:
    """Download size: the sum of the layer sizes the registry declares."""
    layers = document.get("layers")
    if not isinstance(layers, list):
        return None
    total = 0
    for layer in layers:
        size = layer.get("size") if isinstance(layer, dict) else None
        if not isinstance(size, int) or size < 0:
            return None
        total += size
    return total / _GB


def check(tag: str, declared_gb: float, *, opener=None, timeout: float = 15) -> TagReport:
    # A cloud tag has no downloadable manifest, so asking the registry would
    # report it as simply missing. It is a different and worse problem: it runs
    # on Ollama's servers, outside every network mode this project offers.
    if is_cloud_tag(tag):
        return TagReport(tag, False, declared_gb, None, 'cloud tag - runs remotely')
    document, detail = fetch_manifest(tag, opener=opener, timeout=timeout)
    if document is None:
        # 404 is a real answer: the tag is gone. Anything else is "unknown", and
        # must not be reported as a missing model.
        missing = detail == "HTTP 404"
        return TagReport(tag, False if missing else None, declared_gb, None, detail)
    actual = manifest_gb(document)
    return TagReport(tag, True, declared_gb, actual,
                     "ok" if actual is not None else "manifest has no readable layer sizes")


def report(tags: Iterable[tuple[str, float]], *, opener=None, timeout: float = 15) -> list[TagReport]:
    return [check(tag, declared, opener=opener, timeout=timeout) for tag, declared in tags]


def catalogue_tags() -> list[tuple[str, float]]:
    return [(entry.tag, float(entry.size_gb)) for entry in catalog.all_entries()]


def summarise(reports: list[TagReport], tolerance_gb: float = DEFAULT_TOLERANCE_GB) -> list[str]:
    cloud = [r for r in reports if r.detail == 'cloud tag - runs remotely']
    missing = [r for r in reports if r.exists is False and r not in cloud]
    unknown = [r for r in reports if r.exists is None]
    drifted = [r for r in reports
               if r.drift_gb is not None and abs(r.drift_gb) > tolerance_gb]
    lines = ["%d catalogue tags checked against %s" % (len(reports), REGISTRY), ""]
    if cloud:
        lines.append("CLOUD - these run on Ollama's servers, not this machine:")
        lines += ["  %s" % r.tag for r in cloud]
        lines.append("")
    if missing:
        lines.append("MISSING - these cannot be installed at all:")
        lines += ["  %-52s %s" % (r.tag, r.detail) for r in missing]
        lines.append("")
    if drifted:
        lines.append("SIZE DRIFT over %.1fGB - the memory ladder budgets against these:" % tolerance_gb)
        lines += ["  %-52s declared %5.1f  actual %5.1f  (%+.1f)"
                  % (r.tag, r.declared_gb, r.actual_gb, r.drift_gb) for r in drifted]
        lines.append("")
    if unknown:
        lines.append("UNKNOWN - not answered, so not a verdict:")
        lines += ["  %-52s %s" % (r.tag, r.detail) for r in unknown]
        lines.append("")
    if not cloud and not missing and not drifted:
        lines.append("Every tag is local, resolves, and is within %.1fGB of its declared size."
                     % tolerance_gb)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.verify_model_catalog",
        description="Check catalogue tags against the Ollama registry (direct outbound HTTPS).")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--tolerance-gb", type=float, default=DEFAULT_TOLERANCE_GB)
    args = parser.parse_args(argv)

    reports = report(catalogue_tags(), timeout=args.timeout)
    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2, ensure_ascii=False))
    else:
        print("\n".join(summarise(reports, args.tolerance_gb)))
    # A tag that does not resolve is a failure. "Unknown" is not.
    return 1 if any(r.exists is False for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
