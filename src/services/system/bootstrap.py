"""Compatibility entrypoints and initialization outside the application layer."""
from pathlib import Path
import runpy
import sys


def initialize_language(project_root, language=None):
    from installer.lang_setup import initialize_language as initialize
    initialize(Path(project_root), override=language)


def install_exit_hooks(project_root):
    """Install the process-wide shutdown hooks the legacy runtimes rely on.

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
    return True


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


def legacy_entry(module, arguments):
    if module not in ('launcher', 'installer'):
        raise ValueError('unsupported legacy entrypoint')
    from project_paths import USER_DATA_DIR
    from services.network.ownership import RuntimeOwner
    owner = RuntimeOwner(USER_DATA_DIR / 'cache' / 'desktop-runtime.lock')
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
            # Legacy cleanup must finish before another app may change the network.
            lifelog = sys.modules.get('launcher.core.lifelog')
            if module == 'launcher' and lifelog is not None:
                lifelog.shutdown_then_exit()
        finally:
            sys.argv=previous
            owner.release()
