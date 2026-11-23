"""Check the shared LocalAI program copy against the Git commit it came from.

Run from a trusted Git checkout (the one an administrator deploys from)::

    cd <checkout>\\src
    python -m tools.verify_app                       C:\\LocalAI\\app vs this checkout
    python -m tools.verify_app --app D:\\LocalAI\\app   another install
    python -m tools.verify_app --no-git               manifest only (no checkout)

Exit code 0 means every file of the copy matches its manifest *and* the
manifest matches the checkout's HEAD commit (``git ls-tree``), so even a
manifest rewritten after tampering is caught. Nothing is changed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import project_paths
from core import program_integrity as integrity
from installer.steps import app as app_step


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--app', type=Path, default=Path(project_paths.app_dir()))
    parser.add_argument('--source', type=Path, default=Path(project_paths.project_root()))
    parser.add_argument('--no-git', action='store_true',
                        help='check the copy against its own manifest only')
    args = parser.parse_args(argv)
    manifest = integrity.load(args.app)
    source = None if args.no_git or app_step.same_place(args.source, args.app) else args.source
    problems = app_step.verify_deployed(args.app, source)
    commit = str((manifest or {}).get('commit') or '?')
    if problems:
        print('FAIL %s (commit %s)' % (args.app, commit[:12]))
        for line in problems:
            print('  - ' + line)
        return 1
    print('OK   %s = commit %s%s' % (args.app, commit,
                                     '' if source is None else ' (Git ls-tree 확인)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
