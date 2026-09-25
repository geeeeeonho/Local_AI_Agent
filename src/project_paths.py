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

``MODEL_STORAGE_DIR``
    The exception, and deliberately so: the models belong to Ollama, which
    finds them by its own rule, so they sit beside Ollama's install at
    ``C:\\Ollama\\models``. That is the one place every Ollama on the machine
    looks - ours, the tray app Windows starts at login, a user typing
    ``ollama serve`` - and Ollama is this product's relay, so it is not going
    anywhere. A root someone set explicitly still takes the store with it,
    because that means "the whole product lives here".

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


def _on_windows() -> bool:
    """One seam for the platform test.

    Patching ``os.name`` itself is not a substitute: ``pathlib`` reads it on
    every ``Path()``, so a test that flips it globally breaks every other path
    in the process instead of exercising this one branch.
    """
    return os.name == "nt"


def model_dir() -> Path:
    """Where models go, re-read each call.

    ``LLM_MODEL_DIR`` wins, then a store the user configured for Ollama, then
    the one place every Ollama on the machine looks. A root set explicitly -
    a portable run, a test - takes the store with it, and so does a machine
    with no C: drive to install into.
    """
    value = os.environ.get("LLM_MODEL_DIR")
    if value:
        return Path(value).expanduser().resolve()
    configured = ollama_paths.configured_models_dir()
    if configured is not None and not ollama_paths.is_legacy_forced_store(configured):
        return configured
    moved = os.environ.get(runtime_root.ROOT_VARIABLE) or \
        os.environ.get(runtime_root.PORTABLE_VARIABLE)
    if moved or not _on_windows():
        return runtime_dir() / runtime_root.MODELS
    return ollama_paths.SHARED_MODELS_DIR


PROJECT_ROOT = project_root()
RUNTIME_ROOT = runtime_dir()

# Shared by every account on the machine.
ENV_DIR = env_dir()
ACCOUNTS_DIR = accounts_dir()

# This account's alone.
ACCOUNT_ROOT = account_dir()
USER_DATA_DIR = user_data_dir()
LOGS_DIR = logs_dir()
WORKSPACE_DIR = workspace_dir()

# A real user OLLAMA_MODELS override wins, otherwise the store sits beside
# Ollama's install at C:\Ollama\models. Ollama's own default sits in a user
# profile, so a second Windows account would see an empty library and
# re-download everything; the stores this project chose for itself in earlier
# releases (C:\LLM_Models, C:\LocalAI\models) are migration input, not durable
# overrides. LLM_MODEL_DIR remains for controlled deployments and tests.
MODEL_STORAGE_DIR = model_dir()

# Stores earlier releases of this project created. Kept so the installer can
# find models left there and move them, never to write to.
LEGACY_FORCED_MODEL_DIR = ollama_paths.LEGACY_FORCED_STORE
LEGACY_MODEL_DIRS = ollama_paths.LEGACY_STORES

# Folder names under the runtime root, for the callers that compose a path
# from a root they were handed rather than asking for one.
ENV_DIRNAME = runtime_root.ENVIRONMENT
USER_DATA_DIRNAME = runtime_root.USER_DATA
LOGS_DIRNAME = runtime_root.LOGS
ACCOUNTS_DIRNAME = runtime_root.USERS

# The managed environment folder's name in releases before the runtime root.
LEGACY_ENV_DIRNAME = runtime_root.LEGACY_ENVIRONMENT

# Where this project installs Ollama when the machine has none. Binaries only:
# that folder belongs to Ollama's installer, so none of our data lives in it.
OLLAMA_INSTALL_DIR = _override("LLM_OLLAMA_DIR", ollama_paths.PROJECT_INSTALL_DIR)
