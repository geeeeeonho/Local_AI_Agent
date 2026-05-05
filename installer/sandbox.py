"""sandbox — Docker 기반 격리 에이전트 환경 설치."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional

from . import utils
from .i18n import t
from .resources import SafetyProfile

IMAGE_NAME = "llm-agent-sandbox"


class DockerNotAvailable(RuntimeError):
    """Docker not installed / not running."""


DOCKERFILE = """# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \\
        git curl wget build-essential ca-certificates \\
        nano vim less procps \\
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent
USER agent
WORKDIR /home/agent

RUN pip install --user --no-cache-dir --upgrade pip \\
    && pip install --user --no-cache-dir open-interpreter

ENV PATH="/home/agent/.local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV TERM=xterm-256color

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


def install(
    paths: Dict[str, Path],
    profile: Optional[SafetyProfile] = None,
    build_image: bool = True,
):
    utils.section(t("install.sandbox_section"))

    _check_docker()
    utils.ok(t("install.docker_check_ok"))

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
