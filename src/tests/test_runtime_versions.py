"""The pinned Open Interpreter version must agree everywhere at once.

If the installer, the image label and the launcher's label check drift apart,
the sandbox silently stops working: the label check fails forever, the launcher
reports only a generic "runtime is not available", and the installer rebuilds
the image on every run.
"""
import re

import runtime_versions
from installer.steps import python_tools, sandbox
from launcher.agent.interpreter_backend import OI_VERSION
from launcher.agent.sandbox_backend import (
    SANDBOX_OI_LABEL,
    SANDBOX_RUNTIME_LABEL,
    SANDBOX_RUNTIME_VALUE,
)


def test_every_consumer_reads_the_same_constant():
    version = runtime_versions.OPEN_INTERPRETER_VERSION
    assert OI_VERSION == version
    assert python_tools.OPEN_INTERPRETER_VERSION == version


def test_dockerfile_label_is_interpolated_not_written_out():
    dockerfile = sandbox.DOCKERFILE
    version = runtime_versions.OPEN_INTERPRETER_VERSION

    assert f'{SANDBOX_RUNTIME_LABEL}="{SANDBOX_RUNTIME_VALUE}"' in dockerfile
    assert f'{SANDBOX_OI_LABEL}="{version}"' in dockerfile
    assert f"OPEN_INTERPRETER_RELEASE={version}" in dockerfile
    assert runtime_versions.OPEN_INTERPRETER_TAG in dockerfile

    # A bumped constant must move the label with it.
    bumped = sandbox.build_dockerfile("9.9.9")
    assert f'{SANDBOX_OI_LABEL}="9.9.9"' in bumped
    assert version not in bumped.replace(runtime_versions.OPEN_INTERPRETER_TAG, "")


def test_installer_and_image_label_checks_agree():
    assert sandbox.RUNTIME_LABEL == SANDBOX_RUNTIME_LABEL
    assert sandbox.RUNTIME_VALUE == SANDBOX_RUNTIME_VALUE
    assert sandbox.OI_VERSION_LABEL == SANDBOX_OI_LABEL


def test_install_scripts_are_pinned_to_the_same_tag():
    tag = runtime_versions.OPEN_INTERPRETER_TAG
    assert tag in python_tools.OPEN_INTERPRETER_INSTALL_SCRIPT
    assert python_tools.OPEN_INTERPRETER_INSTALL_SCRIPT.endswith("install.ps1")
    assert runtime_versions.open_interpreter_install_script("sh").endswith("install.sh")


def test_no_module_writes_the_version_as_a_bare_literal():
    """Any 0.0.x literal outside runtime_versions is a drift waiting to happen."""
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[1]
    version = runtime_versions.OPEN_INTERPRETER_VERSION
    offenders = []
    for path in src_root.rglob("*.py"):
        if "__pycache__" in path.parts or path.parts[-2] == "tests":
            continue
        if path.name == "runtime_versions.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"['\"][^'\"]*{re.escape(version)}", line):
                offenders.append(f"{path}:{number}")
    assert offenders == [], offenders
