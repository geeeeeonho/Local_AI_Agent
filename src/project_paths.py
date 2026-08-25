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
