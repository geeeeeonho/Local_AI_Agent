"""Where Ollama itself keeps things, resolved the way Ollama resolves it.

This project used to dictate the store: it forced ``OLLAMA_MODELS`` to
``C:\\LLM_Models`` and ran a portable ``ollama.exe`` it had unzipped into the
project folder. That made the models ours rather than Ollama's, so nothing else
on the machine could see them, an official Ollama installed later would look at
an empty directory, and a user who had already set ``OLLAMA_MODELS`` to move
models off C: had that choice silently overridden.

Ollama is the intermediary now, and the store sits inside Ollama's own install
so every account on the machine can reach the same models:

    OLLAMA_MODELS if the user set it, otherwise C:\\Ollama\\models

Ollama's own default, ``<home>/.ollama/models``, is per-user: a second Windows
account on the same PC sees an empty library and re-downloads tens of gigabytes.
So the default is machine-shared - but an explicit OLLAMA_MODELS still wins,
because overriding a user who had already moved their store was the specific
failure of the old forced ``C:\\LLM_Models``.

Nothing here creates, moves or deletes a directory; resolving a path must stay
free of side effects so callers can ask "where would this go" before deciding.
"""
from __future__ import annotations

import os
from pathlib import Path

# The official Windows installer is per-user and needs no administrator, so the
# binaries land under LOCALAPPDATA rather than Program Files. A system-wide
# install into Program Files is a known-broken mix of per-user and per-machine
# state, so it is not a location we look in or install to.
WINDOWS_DEFAULT_INSTALL = r'%LOCALAPPDATA%\Programs\Ollama'
# Where this project installs Ollama when none is present, via OllamaSetup /DIR.
PROJECT_INSTALL_DIR = Path(r'C:\Ollama')
# Models live under that install rather than in a profile, so the machine's
# other accounts share one copy instead of each holding their own.
SHARED_MODELS_DIR = PROJECT_INSTALL_DIR / 'models'
# The store this project used to force before Ollama owned the location.
LEGACY_FORCED_STORE = Path(r'C:\LLM_Models')


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


def configured_models_dir(environ=None) -> Path | None:
    """An OLLAMA_MODELS the user set, or None. Never guessed."""
    environ = os.environ if environ is None else environ
    configured = environ.get('OLLAMA_MODELS')
    return _expanded(configured.strip()) if configured and configured.strip() else None


def user_default_models_dir(environ=None) -> Path:
    """Where Ollama would put models if nobody configured it: per-user."""
    return home(environ) / '.ollama' / 'models'


def models_dir(environ=None) -> Path:
    """The store this machine should use: the user's choice, else the shared one."""
    return configured_models_dir(environ) or SHARED_MODELS_DIR


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


def executable_name() -> str:
    return executable_names()[0]


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
