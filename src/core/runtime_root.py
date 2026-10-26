"""Machine-wide LocalAI runtime layout.

A Windows machine has one shared runtime root::

    C:\\LocalAI\\
        app\\                  shared program everyone runs (admins update it)
        machine.json         who administers LocalAI, who may use it
        environment\\          shared managed runtimes/tools
        ollama\\               shared LocalAI-managed Ollama broker
        models\\               shared local model library
        users\\<account>\\
            user_data\\        private settings/projects/chat/traces
            logs\\             private session/runtime logs
            workspace\\        private working files

Each Windows account may keep its own checkout and RUN.bat. Those launchers all
resolve the same shared environment, Ollama broker and model store, while every
piece of usage data resolves below that account's private directory.

This module only resolves paths. It never creates, moves or deletes data.
"""
from __future__ import annotations

import os
from pathlib import Path

from core import accounts

#: This checkout, derived from where this file sits: core/ -> src/ -> root.
#: Used off Windows, where there is no C: drive to install into. Deriving it
#: rather than falling back to the current directory matters - a product that
#: writes its state wherever it happened to be started from is how the same
#: install ended up in three places.
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]

#: The single root on Windows. Directly under the drive so the path is short,
#: ASCII, space-free and stable - Docker Desktop bind mounts, Inno Setup /DIR
#: arguments and ``cmd`` quoting all get simpler the moment that is true.
WINDOWS_ROOT = Path(r'C:\LocalAI')

#: Set by a deployment that wants the root elsewhere (a second drive, a test).
ROOT_VARIABLE = 'LOCAL_AI_ROOT'
#: Older name, still honoured: tests and portable runs point the whole product
#: at a temporary folder with it, and that has to keep working.
PORTABLE_VARIABLE = 'LLM_PROJECT_ROOT'

#: Folder names under the root. One spelling, used by every component.
MODELS = 'models'
APP = 'app'
MACHINE_POLICY = 'machine.json'
OLLAMA = 'ollama'
ENVIRONMENT = 'environment'
USERS = 'users'
USER_DATA = 'user_data'
LOGS = 'logs'
WORKSPACE = 'workspace'


def _expanded(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def _windows(windows=None) -> bool:
    return os.name == 'nt' if windows is None else bool(windows)


def root(environ=None, windows=None, fallback: Path | None = None) -> Path:
    """The single runtime root.

    ``LOCAL_AI_ROOT`` wins, then the portable override, then ``C:\\LocalAI`` on
    Windows. Off Windows there is no C: drive to install into, so a development
    checkout keeps its own folder as the root and every path below stays inside
    it - the same layout, somewhere a Linux box can actually write.
    """
    environ = os.environ if environ is None else environ
    for name in (ROOT_VARIABLE, PORTABLE_VARIABLE):
        value = environ.get(name)
        if value:
            return _expanded(value).resolve()
    if _windows(windows):
        return WINDOWS_ROOT
    return Path(fallback) if fallback is not None else CHECKOUT_ROOT


def models_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    """Shared model store for every Windows account on the machine."""
    return root(environ, windows, fallback) / MODELS


def ollama_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    """Shared LocalAI-managed Ollama installation."""
    return root(environ, windows, fallback) / OLLAMA


def env_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    """Shared. The runtimes setup installed, not anybody's records."""
    return root(environ, windows, fallback) / ENVIRONMENT


def accounts_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    return root(environ, windows, fallback) / USERS


def account_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    """Private. Everything this Windows account did, and nobody else's."""
    return accounts_dir(environ, windows, fallback) / accounts.current_slug(environ)


def user_data_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    return account_dir(environ, windows, fallback) / USER_DATA


def logs_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    return account_dir(environ, windows, fallback) / LOGS


def workspace_dir(environ=None, windows=None, fallback: Path | None = None) -> Path:
    return account_dir(environ, windows, fallback) / WORKSPACE


def layout(environ=None, windows=None, fallback: Path | None = None) -> dict:
    """Every directory the root owns, by the name the rest of the code uses."""
    base = root(environ, windows, fallback)
    account = account_dir(environ, windows, fallback)
    return {
        'root': base,
        'models': base / MODELS,
        'ollama': base / OLLAMA,
        'env': base / ENVIRONMENT,
        'accounts': base / USERS,
        'account': account,
        'user_data': account / USER_DATA,
        'logs': account / LOGS,
        'workspace': account / WORKSPACE,
    }


#: What each directory in the layout is, so a caller never has to guess which
#: side of the split it is on. Shared is readable by every account on the PC.
SHARED = ('root', 'models', 'ollama', 'env', 'accounts')
PRIVATE = ('account', 'user_data', 'logs', 'workspace')


def is_inside(path, environ=None, windows=None, fallback: Path | None = None) -> bool:
    """True when ``path`` lives under the runtime root."""
    try:
        Path(path).resolve().relative_to(root(environ, windows, fallback).resolve())
    except (ValueError, OSError):
        return False
    return True


__all__ = [
    'CHECKOUT_ROOT', 'WINDOWS_ROOT', 'ROOT_VARIABLE', 'PORTABLE_VARIABLE',
    'MODELS', 'OLLAMA', 'ENVIRONMENT', 'USERS', 'USER_DATA', 'LOGS', 'WORKSPACE',
    'SHARED', 'PRIVATE',
    'root', 'models_dir', 'ollama_dir', 'env_dir', 'accounts_dir', 'account_dir',
    'user_data_dir', 'logs_dir', 'workspace_dir', 'layout', 'is_inside',
]
