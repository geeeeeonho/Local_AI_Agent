"""Shared module entrypoints and process initialization outside the app layer."""
from pathlib import Path
import runpy
import sys


def initialize_language(project_root, language=None):
    from installer.lang_setup import initialize_language as initialize
    initialize(Path(project_root), override=language)


def install_exit_hooks(project_root):
    """Install the process-wide shutdown hooks used by retained runtimes.

    WARP, Tor and the sandbox register their container teardown through
    ``lifelog.register_cleanup``. Those callbacks are only ever run by the
    atexit and signal handlers installed here, so a shell that skips this
    leaves Docker containers running once its window is closed. Installing
    twice is a no-op, and a failure here must not stop the application.
    """
    try:
        from launcher.core import lifelog
        lifelog.install_global_hooks(Path(project_root))
    except Exception:
        return False
    install_docker_sweep(project_root)
    return True


def install_docker_sweep(project_root):
    """Register the one Docker leftover sweep used by every application shell."""
    try:
        from project_paths import USER_DATA_DIR
        from launcher.core import docker_maint
    except Exception:
        return False
    try:
        return bool(docker_maint.register_exit_sweep(USER_DATA_DIR))
    except Exception:
        return False


def run_exit_cleanups():
    """Run the registered teardown now instead of leaving it to atexit.

    Doing it while the process is still healthy keeps container shutdown
    inside the window the user is waiting on, and the one-shot guard in
    lifelog makes the later atexit pass a no-op.
    """
    lifelog = sys.modules.get('launcher.core.lifelog')
    if lifelog is None:
        return False
    try:
        lifelog.shutdown_then_exit()
    except Exception:
        return False
    return True


def run_module_entry(module, arguments):
    if module not in ('launcher', 'installer'):
        raise ValueError('unsupported module entrypoint')
    from project_paths import RUNTIME_LOCK_PATH
    from services.network.ownership import RuntimeOwner
    owner = RuntimeOwner(RUNTIME_LOCK_PATH)
    owner.acquire()
    previous=sys.argv
    try:
        sys.argv=[module,*arguments]
        try:
            runpy.run_module(module,run_name='__main__')
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0
    finally:
        try:
            # Module cleanup must finish before another app may change the network.
            lifelog = sys.modules.get('launcher.core.lifelog')
            if module == 'launcher' and lifelog is not None:
                lifelog.shutdown_then_exit()
        finally:
            sys.argv=previous
            owner.release()
