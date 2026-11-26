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


#: Pinned whisper.cpp release (subtitle tool). Windows assets are taken from
#: this tag only and checked against the SHA-256 digest GitHub records for them.
WHISPER_CPP_VERSION = "1.9.5"
WHISPER_CPP_TAG = f"v{WHISPER_CPP_VERSION}"
#: v1.9.5 release notes explicitly link this separate Windows binary release.
WHISPER_CPP_BUILD_TAG = "b5454"
#: The commit that tag names; the voice-activity model is fetched from it.
WHISPER_CPP_COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"

#: Pinned FFmpeg build (LGPL, static executables) used to read audio from video.
#: BtbN keeps each month-end build; the archive is checked against both the
#: release's checksums.sha256 and GitHub's own digest.
FFMPEG_BUILD_TAG = "autobuild-2026-10-31-12-59"


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
    "WHISPER_CPP_VERSION",
    "WHISPER_CPP_TAG",
    "WHISPER_CPP_BUILD_TAG",
    "WHISPER_CPP_COMMIT",
    "FFMPEG_BUILD_TAG",
    "open_interpreter_install_script",
]
