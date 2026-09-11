"""Compatibility entrypoints and initialization outside the application layer."""
from pathlib import Path
import runpy
import sys


def initialize_language(project_root, language=None):
    from installer.lang_setup import initialize_language as initialize
    initialize(Path(project_root), override=language)


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
