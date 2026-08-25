"""Single source of truth for pinned external runtime versions.

The Open Interpreter version is consumed by three independent places that must
agree exactly or the product silently degrades:

* the installer, which downloads the pinned standalone release for the host;
* the sandbox image build, which stamps the version as a Docker image label;
* the launcher, which refuses to start the sandbox unless that label matches.

When these drifted apart the sandbox failed the label check forever and
reported only a generic "runtime is not available", while the installer
rebuilt the image on every run. Import the constant instead of repeating it.
"""
from __future__ import annotations

#: Pinned Open Interpreter (Rust standalone) release.
OPEN_INTERPRETER_VERSION = "0.0.38"

#: Upstream git tag for the pinned release.
OPEN_INTERPRETER_TAG = f"rust-v{OPEN_INTERPRETER_VERSION}"

#: Docker image labels the launcher checks before using the sandbox.
SANDBOX_RUNTIME_LABEL = "local-ai-agent.runtime"
SANDBOX_RUNTIME_VALUE = "app-server"
SANDBOX_OI_LABEL = "local-ai-agent.open-interpreter-version"


def open_interpreter_install_script(extension: str) -> str:
    """Return the pinned upstream install script URL for ``ps1`` or ``sh``."""
    return (
        "https://raw.githubusercontent.com/openinterpreter/openinterpreter/"
        f"{OPEN_INTERPRETER_TAG}/scripts/install/install.{extension}"
    )


__all__ = [
    "OPEN_INTERPRETER_VERSION",
    "OPEN_INTERPRETER_TAG",
    "SANDBOX_RUNTIME_LABEL",
    "SANDBOX_RUNTIME_VALUE",
    "SANDBOX_OI_LABEL",
    "open_interpreter_install_script",
]
