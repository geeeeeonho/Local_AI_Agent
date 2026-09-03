from __future__ import annotations

import os
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT_OVERRIDE = os.environ.get("LLM_PROJECT_ROOT")
PROJECT_ROOT = (
    Path(_PROJECT_ROOT_OVERRIDE).expanduser().resolve()
    if _PROJECT_ROOT_OVERRIDE
    else SRC_ROOT.parent
)
USER_DATA_DIR = PROJECT_ROOT / "user_data"
ENV_DIR = PROJECT_ROOT / "llm_environment"

# Large Ollama model files are machine-shared rather than tied to one checkout.
# LLM_MODEL_DIR exists mainly for controlled deployments/tests; normal installs use C:\LLM_Models.
_MODEL_STORAGE_OVERRIDE = os.environ.get("LLM_MODEL_DIR")
MODEL_STORAGE_DIR = (
    Path(_MODEL_STORAGE_OVERRIDE).expanduser().resolve()
    if _MODEL_STORAGE_OVERRIDE
    else Path(r"C:\LLM_Models")
)
