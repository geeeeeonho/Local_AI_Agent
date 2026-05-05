"""model — Gemma 4 26B ARA-abliterated 다운로드."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional

from . import utils, ollama
from .i18n import t

PRIMARY  = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M"
FALLBACK = "hf.co/jenerallee78/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M"


def download(paths: Dict[str, Path]) -> Optional[str]:
    utils.section(t("install.model_section", tag=PRIMARY))
    utils.warn(t("install.model_size_warn"))

    exe = paths["ollama"] / "ollama.exe"
    env = ollama.env_for(paths)

    # 1차
    utils.info(t("install.model_try1", tag=PRIMARY))
    r = subprocess.run([str(exe), "pull", PRIMARY], env=env, check=False)
    if r.returncode == 0:
        utils.ok(t("install.model_done"))
        return PRIMARY

    # 2차 (HuggingFace 직접)
    utils.warn(t("install.model_try2", tag=FALLBACK))
    r2 = subprocess.run([str(exe), "pull", FALLBACK], env=env, check=False)
    if r2.returncode == 0:
        utils.ok(t("install.model_done"))
        return FALLBACK

    utils.err(t("install.model_failed"))
    utils.warn(t("install.model_manual", tag=PRIMARY))
    return None
