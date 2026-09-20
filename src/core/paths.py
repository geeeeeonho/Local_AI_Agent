"""Shared path policy. Importing this module never creates or migrates data.

``src/project_paths.py`` stays the one place the project root and the shared
model store are decided (see README, "경로 정책"). This module re-exports them
and adds only what the new service layer needs on top, so the two trees cannot
drift into two different answers for the same directory.
"""
from __future__ import annotations
import os
from pathlib import Path

from project_paths import (
    ENV_DIR,
    MODEL_STORAGE_DIR,
    PROJECT_ROOT,
    SRC_ROOT,
    USER_DATA_DIR,
)

__all__ = ['SRC_ROOT', 'PROJECT_ROOT', 'USER_DATA_DIR', 'ENV_DIR',
           'MODEL_STORAGE_DIR', 'OLLAMA_INSTALL_DIR']

def _override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default

# Staged official-Ollama location. Nothing here moves models into it; the
# desktop shell keeps using MODEL_STORAGE_DIR until that migration ships.
OLLAMA_INSTALL_DIR = _override('LLM_OLLAMA_DIR', Path(r'C:\Ollama'))
