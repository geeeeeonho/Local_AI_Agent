"""Single source of truth for every project, runtime and model path.

Importing this module never creates, moves or migrates data. Everything that
needs a path - installer, launcher, services and the desktop shell - reads it
from here, so an override applies everywhere at once instead of drifting.
"""
from __future__ import annotations

import os
from pathlib import Path

from core import ollama_paths


SRC_ROOT = Path(__file__).resolve().parent


def _override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


PROJECT_ROOT = _override("LLM_PROJECT_ROOT", SRC_ROOT.parent)
USER_DATA_DIR = PROJECT_ROOT / "user_data"
ENV_DIR = PROJECT_ROOT / "llm_environment"

# Models live inside Ollama's own install, shared by every account on the
# machine: OLLAMA_MODELS when the user set one, otherwise C:\Ollama\models.
# Ollama's own default lives in a user profile, so a second Windows account
# would see an empty library and re-download everything.
# LLM_MODEL_DIR remains for controlled deployments and tests.
MODEL_STORAGE_DIR = _override("LLM_MODEL_DIR", ollama_paths.models_dir())

# The store this project used to force before Ollama owned the location. Kept so
# the installer can find models left there and move them, never to write to.
LEGACY_FORCED_MODEL_DIR = ollama_paths.LEGACY_FORCED_STORE

# Where this project installs Ollama when the machine has none. The official
# installer is per-user under LOCALAPPDATA; this is the /DIR= target we ask for.
OLLAMA_INSTALL_DIR = _override("LLM_OLLAMA_DIR", ollama_paths.PROJECT_INSTALL_DIR)
