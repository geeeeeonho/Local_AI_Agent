"""Where Ollama itself keeps things, resolved the way Ollama resolves it.

This project used to dictate the store: it forced ``OLLAMA_MODELS`` to
``C:\\LLM_Models`` and ran a portable ``ollama.exe`` it had unzipped into the
project folder. That made the models ours rather than Ollama's, so nothing else
on the machine could see them, an official Ollama installed later would look at
an empty directory, and a user who had already set ``OLLAMA_MODELS`` to move
models off C: had that choice silently overridden.

Ollama is the intermediary now, and the store sits inside Ollama's own install
so every account on the machine reaches the same models by Ollama's own rule:

    OLLAMA_MODELS if the user set it, otherwise C:\\Ollama\\models

That folder is the one Ollama itself is pointed at, which is the whole reason
to use it: any Ollama on this machine - ours, the tray app Windows starts at
login, a user typing ``ollama serve`` - finds the same library without this
project having to be running. A previous release moved the store to
``C:\\LocalAI\\models`` to keep it clear of Ollama's uninstaller; that is a real
risk only for someone uninstalling Ollama, and Ollama is this product's relay,
so uninstalling it stops the product either way. Two spare copies of forty
gigabytes is the larger cost, so the store stays where Ollama looks.

Locations this project itself chose in earlier releases are read as migration
input rather than as a user's choice: the forced ``C:\\LLM_Models`` and the
runtime-root ``C:\\LocalAI\\models``. Anything else the user set wins, because
overriding someone who had already moved their store off C: was the specific
failure of the forced store.

Ollama's own default, ``<home>/.ollama/models``, is per-user: a second Windows
account on the same PC sees an empty library and re-downloads tens of gigabytes.
So the default is machine-shared, directly under the drive root.

Nothing here creates, moves or deletes a directory; resolving a path must stay
free of side effects so callers can ask "where would this go" before deciding.
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
PROJECT_INSTALL_DIR = Path(r'C:\Ollama')
# The store, beside the install and directly under the drive: short, ASCII,
# space-free, one copy for every account, and exactly where Ollama looks.
SHARED_MODELS_DIR = PROJECT_INSTALL_DIR / 'models'
# Stores this project itself created in earlier releases. Migration input.
LEGACY_FORCED_STORE = Path(r'C:\LLM_Models')
LEGACY_ROOT_STORE = runtime_root.WINDOWS_ROOT / 'models'
LEGACY_STORES = (LEGACY_FORCED_STORE, LEGACY_ROOT_STORE)


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


def is_legacy_forced_store(path) -> bool:
    """True for a store an older Local AI Agent release chose on its own.

    Those values are migration input, not a lasting user preference. An older
    release could leave OLLAMA_MODELS=C:\\LLM_Models - or, after the release that
    followed it, C:\\LocalAI\\models - in the machine environment; treating
    either like a deliberate override would stop the installer from ever
    bringing those models back to the one place every Ollama on the machine
    looks, and would leave a second copy nobody serves.
    """
    if path is None:
        return False
    return any(_same_windows_path(path, legacy) for legacy in LEGACY_STORES)


def models_dir(environ=None) -> Path:
    """The active store: a real user choice, otherwise the shared store.

    The exceptions are the values older releases of this project set for
    themselves. They are deliberately ignored here so setup can see those
    directories as legacy input and migrate them into C:\\Ollama\\models.
    """
    configured = configured_models_dir(environ)
    if configured is not None and not is_legacy_forced_store(configured):
        return configured
    return SHARED_MODELS_DIR


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
    for candidate in ((configured_models_dir(environ), SHARED_MODELS_DIR,
                       user_default_models_dir(environ)) + LEGACY_STORES):
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
