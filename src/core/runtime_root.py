"""One folder directly under C: holds everything this product runs on.

Until now the parts lived wherever each of them had historically landed: the
managed environment and ``user_data`` inside whatever folder the repository was
unzipped into, the model store inside Ollama's own install at
``C:\\Ollama\\models``, and the logs under the environment. That spread has cost
real time:

* The checkout is where a user puts a download - Desktop, Downloads, a OneDrive
  folder that syncs tens of gigabytes to the cloud, a path with spaces and
  non-ASCII characters that Docker Desktop refuses to bind-mount. Moving or
  renaming that folder silently orphaned the whole environment.
* Models inside ``C:\\Ollama`` are deleted by Ollama's own uninstaller, taking
  the downloads with them.
* Nothing could answer "where is this installed" with a single path.

So there is one runtime root, directly under the drive root, holding every
piece of state this product owns - split by who it belongs to::

    C:\\LocalAI\\
        models\\               shared: the Ollama store, one copy per machine
        environment\\          shared: managed runtimes, container config
        users\\<account>\\
            user_data\\        private: settings, projects, chat, traces
            logs\\             private: session logs
            workspace\\        private: the agent's default working folder

The models are a machine asset: identical for everyone, a day to download, so
every Windows account reads the same copy. What a person *does* with them is
theirs, and a shared ``user_data`` does not merely leak it - two signed-in
accounts write the same settings file and the same session state. ``core.
accounts`` names the folders and says what makes one private.

Ollama's own binaries stay where they are (``C:\\Ollama``); they belong to
Ollama's installer, not to us, and keeping our data out of that folder is what
lets an Ollama uninstall leave the models alone.

Nothing here creates or moves a directory. Resolving a path must stay free of
side effects so the installer can ask "where would this go" before deciding
whether anything needs migrating.
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
ENVIRONMENT = 'environment'
USERS = 'users'
USER_DATA = 'user_data'
LOGS = 'logs'
WORKSPACE = 'workspace'

#: What earlier releases called the managed environment folder. Kept so setup
#: can find one and move it, never to write to.
LEGACY_ENVIRONMENT = 'llm_environment'


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
    """Shared. One copy of the models for the whole machine."""
    return root(environ, windows, fallback) / MODELS


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
        'env': base / ENVIRONMENT,
        'accounts': base / USERS,
        'account': account,
        'user_data': account / USER_DATA,
        'logs': account / LOGS,
        'workspace': account / WORKSPACE,
    }


#: What each directory in the layout is, so a caller never has to guess which
#: side of the split it is on. Shared is readable by every account on the PC.
SHARED = ('root', 'models', 'env', 'accounts')
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
    'MODELS', 'ENVIRONMENT', 'USERS', 'USER_DATA', 'LOGS', 'WORKSPACE',
    'LEGACY_ENVIRONMENT', 'SHARED', 'PRIVATE',
    'root', 'models_dir', 'env_dir', 'accounts_dir', 'account_dir',
    'user_data_dir', 'logs_dir', 'workspace_dir', 'layout', 'is_inside',
]
