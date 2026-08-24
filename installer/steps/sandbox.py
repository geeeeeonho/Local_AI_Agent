"""sandbox — Docker 기반 격리 에이전트 환경 설치."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from installer import utils
from installer.i18n import t
from installer.resources import SafetyProfile

IMAGE_NAME = "llm-agent-sandbox"
OPEN_INTERPRETER_VERSION = "0.0.38"
RUNTIME_LABEL = "local-ai-agent.runtime"
RUNTIME_VALUE = "app-server"
OI_VERSION_LABEL = "local-ai-agent.open-interpreter-version"


class DockerNotAvailable(RuntimeError):
    """Docker not installed / not running."""


DOCKERFILE = """# syntax=docker/dockerfile:1
FROM python:3.11-slim

LABEL local-ai-agent.runtime="app-server" \\
      local-ai-agent.open-interpreter-version="0.0.38"

RUN apt-get update && apt-get install -y --no-install-recommends \\
        git curl wget build-essential ca-certificates tar gzip \\
        nano vim less procps \\
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent
USER agent
WORKDIR /home/agent

ENV PATH="/home/agent/.local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV TERM=xterm-256color

RUN curl -fsSL \\
        https://raw.githubusercontent.com/openinterpreter/openinterpreter/rust-v0.0.38/scripts/install/install.sh \\
        -o /tmp/install-open-interpreter.sh \\
    && OPEN_INTERPRETER_RELEASE=0.0.38 \\
       OPEN_INTERPRETER_NONINTERACTIVE=1 \\
       OPEN_INTERPRETER_INSTALL_DIR=/home/agent/.local/bin \\
       INTERPRETER_HOME=/home/agent/.openinterpreter-package \\
       sh /tmp/install-open-interpreter.sh \\
    && /home/agent/.local/bin/interpreter --version \\
    && rm -f /tmp/install-open-interpreter.sh

RUN mkdir -p /home/agent/workspace
WORKDIR /home/agent/workspace

CMD ["bash"]
"""


def _check_docker():
    try:
        subprocess.run(
            ["docker", "--version"],
            capture_output=True, check=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise DockerNotAvailable("Docker not installed")

    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise DockerNotAvailable("Docker daemon not responding")


def _image_has_current_runtime(image: str = IMAGE_NAME) -> bool:
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 15,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        result = subprocess.run(
            [
                "docker", "image", "inspect", image,
                "--format", "{{json .Config.Labels}}",
            ],
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    try:
        labels = json.loads((result.stdout or "").strip())
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(labels, dict):
        return False
    return (
        labels.get(RUNTIME_LABEL) == RUNTIME_VALUE
        and labels.get(OI_VERSION_LABEL) == OPEN_INTERPRETER_VERSION
    )


def install(
    paths: Dict[str, Path],
    profile: Optional[SafetyProfile] = None,
    build_image: bool = True,
):
    utils.section(t("install.sandbox_section"))

    _check_docker()
    utils.ok(t("install.docker_check_ok"))

    # Existence alone is not enough: old Python-OI images must be rebuilt.
    if _image_has_current_runtime(IMAGE_NAME):
        from installer.i18n import get_language
        _msg = (f"{IMAGE_NAME} App Server {OPEN_INTERPRETER_VERSION} 이미지 이미 존재 — 빌드 건너뜀"
                if get_language() == "ko"
                else f"{IMAGE_NAME} App Server {OPEN_INTERPRETER_VERSION} image already exists - skipping build")
        utils.ok(_msg)
        return

    df = paths["sandbox"] / "Dockerfile"
    df.write_text(DOCKERFILE, encoding="utf-8")
    (paths["sandbox"] / ".dockerignore").write_text(
        "*.bat\n*.md\n*.log\n", encoding="utf-8",
    )
    utils.ok(t("install.dockerfile_written", path=str(df)))

    (paths["workspace"] / "README.txt").write_text(
        "This folder is mounted at /home/agent/workspace inside the container.\n"
        "Files placed here appear in the container, and files created in the\n"
        "container appear here.\n",
        encoding="utf-8",
    )

    if build_image:
        utils.section(t("install.image_build_section", name=IMAGE_NAME))
        utils.warn(t("install.image_build_warn"))

        cmd = ["docker", "build", "-t", IMAGE_NAME]
        if profile:
            cmd += [
                "--memory", profile.docker_build_memory,
                "--cpu-quota", str(int(float(profile.docker_build_cpus) * 100000)),
                "--cpu-period", "100000",
            ]
            utils.info(t("install.image_build_limits",
                         mem=profile.docker_build_memory,
                         cpus=profile.docker_build_cpus))
        cmd.append(str(paths["sandbox"]))

        try:
            subprocess.run(cmd, check=True)
            utils.ok(t("install.image_build_ok"))
        except subprocess.CalledProcessError:
            utils.err(t("install.image_build_fail"))
    else:
        utils.info(t("install.image_skip"))
