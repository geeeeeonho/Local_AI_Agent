"""Read this account's encrypted LocalAI records.

Logs and agent traces under ``users\\<account>\\logs`` are encrypted for the
Windows account that wrote them, so opening one in Notepad shows ``#LAV1``
lines. Run this as that account to read them::

    RUN.bat --records                  list the records
    RUN.bat --records show <file>      print one, decrypted
    RUN.bat --records export <folder>  write decrypted copies to a folder

An export is plaintext again: put it somewhere only you can read, and delete
it when done. Another account - an administrator included - gets
"cannot be decrypted" instead of the contents.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import project_paths
from core import vault


def _records():
    logs = Path(project_paths.logs_dir())
    data = Path(project_paths.user_data_dir())
    found = sorted(logs.glob('*.log')) + sorted(logs.glob('*.jsonl'))
    for folder in ('settings', 'projects', 'runtime'):
        found += sorted((data / folder).glob('*.json'))
    return [path for path in found if path.is_file()]


def _is_lines(path: Path) -> bool:
    return path.suffix in ('.log', '.jsonl')


def _decrypted(path: Path) -> str:
    if _is_lines(path):
        return ''.join(vault.iter_lines(path))
    return vault.read_text(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='RUN.bat --records',
                                     description='이 계정의 암호화된 LocalAI 기록 보기')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('list')
    show = sub.add_parser('show')
    show.add_argument('file')
    export = sub.add_parser('export')
    export.add_argument('folder')
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['--records']:
        argv = argv[1:]      # RUN.bat forwards its own flag
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

    if args.command in (None, 'list'):
        print('기록 위치: %s' % project_paths.account_dir())
        for path in _records():
            raw = path.read_bytes()[:64]
            state = ('암호화됨' if raw.startswith(vault.MAGIC_FILE)
                     or raw.startswith(vault.LINE_PREFIX.encode()) else '평문')
            print('  %-8s %s' % (state, path.relative_to(project_paths.account_dir())))
        return 0

    if args.command == 'show':
        path = Path(args.file)
        if not path.is_absolute():
            matches = [p for p in _records() if p.name == args.file]
            path = matches[0] if matches else path
        try:
            sys.stdout.write(_decrypted(path))
        except (OSError, vault.VaultError) as exc:
            print('읽을 수 없습니다: %s' % exc, file=sys.stderr)
            return 1
        return 0

    target = Path(args.folder)
    target.mkdir(parents=True, exist_ok=True)
    failed = 0
    for path in _records():
        try:
            (target / path.name).write_text(_decrypted(path), encoding='utf-8')
        except (OSError, vault.VaultError) as exc:
            failed += 1
            print('건너뜀 %s: %s' % (path.name, exc), file=sys.stderr)
    print('복호화 사본을 %s 에 썼습니다. 다 본 뒤 지우세요.' % target)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
