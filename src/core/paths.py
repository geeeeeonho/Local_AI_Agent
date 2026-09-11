"""Shared path policy. Importing this module never creates or migrates data."""
from __future__ import annotations
import os
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]

def _override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default

PROJECT_ROOT = _override('LLM_PROJECT_ROOT', SRC_ROOT.parent)
USER_DATA_DIR = PROJECT_ROOT / 'user_data'
ENV_DIR = PROJECT_ROOT / 'llm_environment'
OLLAMA_INSTALL_DIR = _override('LLM_OLLAMA_DIR', Path(r'C:\Ollama'))
MODEL_STORAGE_DIR = _override('LLM_MODEL_DIR', Path(r'C:\LLM_Models'))
LEGACY_SHARED_MODEL_DIR = Path(r'C:\LLM_Models')

# All new services use the same process-birth proof, not separate app-local files.
OFFICIAL_RUNTIME_STATE = USER_DATA_DIR / 'cache' / 'ollama-process.json'
