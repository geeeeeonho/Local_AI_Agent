"""Single source of truth for every project, runtime and model path.

Importing this module never creates, moves or migrates data. Everything that
needs a path - installer, launcher, services and the desktop shell - reads it
from here, so an override applies everywhere at once instead of drifting.

Two roots, and they are not the same thing:

``PROJECT_ROOT``
    The checkout: source, ``RUN.bat``, bundled resources. Wherever the user
    unzipped it. Read-only as far as this product is concerned.

``RUNTIME_ROOT``
    Everything the product owns and writes, in one folder directly under the
    drive root (``C:\\LocalAI``). Keeping state out of the checkout is what lets
    the user move, rename or re-download the project folder without orphaning
    tens of gigabytes, and what keeps Docker Desktop bind mounts off OneDrive
    paths with spaces in them.

Inside that root, who a folder belongs to decides where it sits.
``environment`` is shared: the runtimes setup installed, identical for
everyone. ``ACCOUNT_ROOT`` is this Windows account's own - settings, projects,
chat, traces, logs - and the machine's other accounts are locked out of it,
because sharing those between two signed-in users does not merely leak, it
corrupts.

Shared machine assets are all below the runtime root:
``environment``, ``ollama`` and ``models``. Ollama's own per-user default is
not used for the managed broker; LocalAI starts it with the shared model path.
Only LocalAI's explicit deployment override may move the managed model store.

Off Windows there is no C: drive to install into, so a development checkout is
its own runtime root and the same layout appears inside it.
"""
from __future__ import annotations

import os
from pathlib import Path

from core import accounts, ollama_paths, runtime_root


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
    """Shared: the runtimes setup installed."""
    return runtime_dir() / runtime_root.ENVIRONMENT


def accounts_dir() -> Path:
    """Shared parent of the private folders. The folders themselves are not."""
    return runtime_dir() / runtime_root.USERS


def account_dir() -> Path:
    """Private: what this Windows account did, re-read each call."""
    return accounts_dir() / accounts.current_slug()


def user_data_dir() -> Path:
    return account_dir() / runtime_root.USER_DATA


def logs_dir() -> Path:
    return account_dir() / runtime_root.LOGS


def workspace_dir() -> Path:
    """Private: the agent's default working folder for this account."""
    return account_dir() / runtime_root.WORKSPACE


def model_dir() -> Path:
    """Shared LocalAI model store.

    ``OLLAMA_MODELS`` is an Ollama process setting, not the LocalAI layout
    source of truth. Reading a per-user value here would split a machine-wide
    install back into different stores for different Windows accounts.
    ``LLM_MODEL_DIR`` remains the explicit deployment/test override.
    """
    value = os.environ.get("LLM_MODEL_DIR")
    if value:
        return Path(value).expanduser().resolve()
    return runtime_dir() / runtime_root.MODELS


def model_control_dir(storage_dir=None) -> Path:
    """Shared control state for one LocalAI-managed model library."""
    root = model_dir() if storage_dir is None else Path(storage_dir)
    return root / ".localai"


def model_registry_path(storage_dir=None) -> Path:
    """Shared role/selection registry. Never falls back to one account."""
    return model_control_dir(storage_dir) / "registry.json"


def model_mutation_lock_path(storage_dir=None) -> Path:
    """One cross-process lock for every install/remove touching the shared store."""
    return model_control_dir(storage_dir) / "model-mutation.lock"


def model_files_path(storage_dir=None) -> Path:
    """The one machine-wide human-readable model file index."""
    root = model_dir() if storage_dir is None else Path(storage_dir)
    return root / "MODEL_FILES.csv"


PROJECT_ROOT = project_root()
RUNTIME_ROOT = runtime_dir()

# Shared by every account on the machine.
ENV_DIR = env_dir()
RUNTIME_LOCK_PATH = ENV_DIR / "desktop-runtime.lock"
ACCOUNTS_DIR = accounts_dir()

# This account's alone.
ACCOUNT_ROOT = account_dir()
USER_DATA_DIR = user_data_dir()
LOGS_DIR = logs_dir()
WORKSPACE_DIR = workspace_dir()

# One shared model library and one shared control plane per machine. An explicit
# LocalAI deployment override still wins, but ordinary installs resolve to
# <runtime root>\models and keep every model-management record below it.
MODEL_STORAGE_DIR = model_dir()
MODEL_CONTROL_DIR = model_control_dir(MODEL_STORAGE_DIR)
MODEL_REGISTRY_PATH = model_registry_path(MODEL_STORAGE_DIR)
MODEL_MUTATION_LOCK = model_mutation_lock_path(MODEL_STORAGE_DIR)
MODEL_FILES_PATH = model_files_path(MODEL_STORAGE_DIR)


# Folder names under the runtime root, for the callers that compose a path
# from a root they were handed rather than asking for one.
ENV_DIRNAME = runtime_root.ENVIRONMENT
USER_DATA_DIRNAME = runtime_root.USER_DATA
LOGS_DIRNAME = runtime_root.LOGS
ACCOUNTS_DIRNAME = runtime_root.USERS


# Shared LocalAI-managed Ollama broker.
OLLAMA_INSTALL_DIR = _override("LLM_OLLAMA_DIR", runtime_dir() / runtime_root.OLLAMA)
