"""Single source of truth for every project, runtime and model path.

Importing this module never creates, moves or migrates data. Everything that
needs a path - installer, launcher, services and the desktop shell - reads it
from here, so an override applies everywhere at once instead of drifting.

Two roots, and they are not the same thing:

``PROJECT_ROOT``
    The checkout: source, ``RUN.bat``, bundled resources. Wherever the user
    unzipped it. Read-only as far as this product is concerned.

``RUNTIME_ROOT``
    Everything the product owns and writes - models, managed environment,
    user data, logs - in one folder directly under the drive root
    (``C:\\LocalAI``). Keeping state out of the checkout is what lets the user
    move, rename or re-download the project folder without orphaning tens of
    gigabytes, and what keeps Docker Desktop bind mounts off OneDrive paths
    with spaces in them.

Off Windows there is no C: drive to install into, so a development checkout is
its own runtime root and the same layout appears inside it.
"""
from __future__ import annotations

import os
from pathlib import Path

from core import ollama_paths, runtime_root


SRC_ROOT = Path(__file__).resolve().parent
CHECKOUT_ROOT = SRC_ROOT.parent


def _override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def project_root() -> Path:
    """The checkout, re-read each call so tests and portable runs can move it."""
    return _override("LLM_PROJECT_ROOT", CHECKOUT_ROOT)


def runtime_dir() -> Path:
    """The single runtime root, re-read each call.

    ``LOCAL_AI_ROOT`` wins; ``LLM_PROJECT_ROOT`` moves the whole product for a
    portable run or a test; otherwise it is ``C:\\LocalAI`` on Windows and the
    checkout on a development machine.
    """
    return runtime_root.root(fallback=CHECKOUT_ROOT)


def env_dir() -> Path:
    return runtime_dir() / runtime_root.ENVIRONMENT


def user_data_dir() -> Path:
    return runtime_dir() / runtime_root.USER_DATA


def logs_dir() -> Path:
    return runtime_dir() / runtime_root.LOGS


def model_dir() -> Path:
    value = os.environ.get("LLM_MODEL_DIR")
    if value:
        return Path(value).expanduser().resolve()
    configured = ollama_paths.configured_models_dir()
    if configured is not None and not ollama_paths.is_legacy_forced_store(configured):
        return configured
    return runtime_dir() / runtime_root.MODELS


PROJECT_ROOT = project_root()
RUNTIME_ROOT = runtime_dir()
USER_DATA_DIR = user_data_dir()
ENV_DIR = env_dir()
LOGS_DIR = logs_dir()

# A real user OLLAMA_MODELS override wins, otherwise the store lives in the
# runtime root: C:\LocalAI\models. Ollama's own default sits in a user profile,
# so a second Windows account would see an empty library and re-download
# everything; the stores this project chose in earlier releases
# (C:\LLM_Models, C:\Ollama\models) are migration input, not durable overrides.
# LLM_MODEL_DIR remains for controlled deployments and tests.
MODEL_STORAGE_DIR = model_dir()

# Stores earlier releases of this project created. Kept so the installer can
# find models left there and move them, never to write to.
LEGACY_FORCED_MODEL_DIR = ollama_paths.LEGACY_FORCED_STORE
LEGACY_MODEL_DIRS = ollama_paths.LEGACY_STORES

# Folder names under the runtime root, for the two callers that compose a path
# from a root they were handed rather than asking for one.
ENV_DIRNAME = runtime_root.ENVIRONMENT
USER_DATA_DIRNAME = runtime_root.USER_DATA

# The managed environment folder's name in releases before the runtime root.
LEGACY_ENV_DIRNAME = runtime_root.LEGACY_ENVIRONMENT

# Where this project installs Ollama when the machine has none. Binaries only:
# that folder belongs to Ollama's installer, so none of our data lives in it.
OLLAMA_INSTALL_DIR = _override("LLM_OLLAMA_DIR", ollama_paths.PROJECT_INSTALL_DIR)
