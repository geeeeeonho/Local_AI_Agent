"""Single source of truth for every project, runtime and model path.

Importing this module never creates, moves or migrates data. Everything that
needs a path - installer, launcher, services and the desktop shell - reads it
from here, so an override applies everywhere at once instead of drifting.
"""
from __future__ import annotations

import os
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parent


def _override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


PROJECT_ROOT = _override("LLM_PROJECT_ROOT", SRC_ROOT.parent)
USER_DATA_DIR = PROJECT_ROOT / "user_data"
ENV_DIR = PROJECT_ROOT / "llm_environment"

# Large Ollama model files are machine-shared rather than tied to one checkout.
# LLM_MODEL_DIR exists mainly for controlled deployments/tests; normal installs use C:\LLM_Models.
MODEL_STORAGE_DIR = _override("LLM_MODEL_DIR", Path(r"C:\LLM_Models"))

# Where an official Ollama runtime would be installed. LLM_OLLAMA_DIR keeps the
# same controlled-deployment escape hatch as the model store.
OLLAMA_INSTALL_DIR = _override("LLM_OLLAMA_DIR", Path(r"C:\Ollama"))
