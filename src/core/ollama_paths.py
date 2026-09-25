"""Paths for the LocalAI-managed Ollama broker.

Fresh Windows installs keep the broker and its model library inside the one
machine-wide LocalAI root::

    C:\\LocalAI\\ollama
    C:\\LocalAI\\models

The launcher always supplies OLLAMA_MODELS to the broker it starts, so Ollama's
per-user default does not split the model library across Windows accounts.
A user-provided OLLAMA_MODELS remains an explicit override.

This module resolves paths only. It does not migrate old installations.
"""
from __future__ import annotations

import os
from pathlib import Path

from core import runtime_root

# The official Windows installer is per-user and needs no administrator, so the
# binaries land under LOCALAPPDATA rather than Program Files. A system-wide
# install into Program Files is a known-broken mix of per-user and per-machine
# state, so it is not a location we look in or install to.
WINDOWS_DEFAULT_INSTALL = r'%LOCALAPPDATA%\Programs\Ollama'
# Where this project installs Ollama when none is present, via OllamaSetup /DIR.
PROJECT_INSTALL_DIR = runtime_root.WINDOWS_ROOT / 'ollama'
# The store, beside the install and directly under the drive: short, ASCII,
# space-free, one copy for every account, and exactly where Ollama looks.
SHARED_MODELS_DIR = runtime_root.WINDOWS_ROOT / runtime_root.MODELS

def _expanded(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def home(environ=None) -> Path:
    """The home directory Ollama would expand ``~`` to.

    Read from the environment rather than ``Path.home()`` so a caller can ask
    the question for a different account, and so tests need no real home.
    """
    environ = os.environ if environ is None else environ
    for key in ('USERPROFILE', 'HOME'):
        value = environ.get(key)
        if value:
            return _expanded(value)
    return Path.home()


def _ollama_var(value):
    """Read a variable the way Ollama reads it.

    Ollama's envconfig.Var trims whitespace and then strips surrounding quotes,
    so OLLAMA_MODELS="C:\\Ollama\\models" - quotes and all, which is easy to end up
    with from a Windows dialog or a batch file - resolves to the bare path.
    Keeping the quotes would send this project looking in a directory that does
    not exist while Ollama serves happily from the real one.
    """
    if not isinstance(value, str):
        return ''
    return value.strip().strip('"\'')


def configured_models_dir(environ=None) -> Path | None:
    """An OLLAMA_MODELS the user set, or None. Never guessed."""
    environ = os.environ if environ is None else environ
    configured = _ollama_var(environ.get('OLLAMA_MODELS'))
    return _expanded(configured) if configured else None


def user_default_models_dir(environ=None) -> Path:
    """Where Ollama would put models if nobody configured it: per-user."""
    return home(environ) / '.ollama' / 'models'


def _same_windows_path(left, right) -> bool:
    import ntpath
    a = ntpath.normcase(ntpath.normpath(str(left).strip().strip('"\'')))
    b = ntpath.normcase(ntpath.normpath(str(right).strip().strip('"\'')))
    return a == b



def models_dir(environ=None) -> Path:
    """Explicit user override, otherwise the LocalAI machine-wide store."""
    configured = configured_models_dir(environ)
    return configured if configured is not None else SHARED_MODELS_DIR


def models_dir_is_shared(environ=None) -> bool:
    """True when the resolved store is the machine-shared one under the install."""
    return models_dir(environ) == SHARED_MODELS_DIR


def is_per_user_store(path, environ=None) -> bool:
    """True when a path sits inside a single account's profile.

    Used to tell the user that the machine's other accounts will not see it.
    """
    try:
        Path(path).relative_to(home(environ))
    except (ValueError, OSError):
        return False
    return True


def store_candidates(environ=None):
    """Stores a running Ollama may actually be serving from, likeliest first.

    ``models_dir`` answers "where would *we* put models". That is not the same
    question as "where is the Ollama that is already running keeping them", and
    treating the two as one is what made an ordinary machine unusable: install
    Ollama the official way, never set OLLAMA_MODELS, and its models sit in
    ``<home>/.ollama/models`` while this project resolves the shared
    ``C:\\Ollama\\models``. The two disagree, and the disagreement was read as
    "that server is pointed somewhere else" - which it is, at its own default.
    """
    environ = os.environ if environ is None else environ
    seen, out = set(), []
    for candidate in (configured_models_dir(environ), SHARED_MODELS_DIR,
                      user_default_models_dir(environ)):
        if candidate is None:
            continue
        key = os.path.normcase(os.path.abspath(str(candidate)))
        if key not in seen:
            seen.add(key)
            out.append(Path(candidate))
    return tuple(out)


def install_candidates(environ=None):
    """Places an official Ollama may already be installed, most likely first."""
    environ = os.environ if environ is None else environ
    local = environ.get('LOCALAPPDATA')
    seen, out = set(), []
    for candidate in (
        _expanded(local) / 'Programs' / 'Ollama' if local else None,
        PROJECT_INSTALL_DIR,
        Path(r'C:\Program Files\Ollama'),
        home(environ) / '.ollama' / 'bin',
    ):
        if candidate is None:
            continue
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    return tuple(out)


# The portable copy is extracted from ollama-windows-amd64.zip, so it is named
# ollama.exe whatever platform a test happens to run on.
PORTABLE_EXECUTABLE = 'ollama.exe'


def executable_names() -> tuple:
    """Binary names to look for, most likely first."""
    return ('ollama.exe', 'ollama') if os.name == 'nt' else ('ollama', 'ollama.exe')


#: The Windows tray application that owns the server process. It is what the
#: Startup entry launches at login, it spawns ``ollama.exe serve`` with its own
#: environment, and it starts a replacement within milliseconds of that child
#: being killed - so stopping only the listener changes nothing at all.
SUPERVISOR_EXECUTABLE = 'ollama app.exe'
SUPERVISOR_PROCESS = 'ollama app'


def supervisor_beside(executable) -> Path:
    """Where the tray application sits, given the server binary's path."""
    return Path(executable).parent / SUPERVISOR_EXECUTABLE


# Ollama's Windows installer is Inno Setup, so /DIR= chooses where the binaries
# land and the silent switches make it scriptable. Installing into Program Files
# is deliberately not attempted: it produces a mix of per-machine files and
# per-user registry/start-menu state.
SETUP_URL = 'https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe'


def setup_command(installer: Path, target: Path) -> list:
    """Silent install of the official Ollama into ``target``.

    /DIR only moves the program files. Models keep resolving by Ollama's own
    rule, which is the point: the location stays Ollama's to decide.
    """
    return [str(installer), '/DIR=' + str(target), '/VERYSILENT', '/NORESTART']


def find_executable(environ=None, extra=(), fallback=()) -> Path | None:
    """An Ollama already on this machine, or None.

    Checked before installing anything, so a machine that already runs Ollama
    keeps the install it has instead of gaining a second one.

    ``fallback`` is searched last. The portable copy this project used to unzip
    into its own folder goes there: an officially installed Ollama is the one
    other programs and other accounts on the machine talk to, so it wins.
    """
    import shutil
    environ = os.environ if environ is None else environ
    for folder in tuple(extra) + install_candidates(environ) + tuple(fallback):
        for name in executable_names():
            candidate = Path(folder) / name
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
    found = shutil.which('ollama', path=environ.get('PATH'))
    return Path(found) if found else None
