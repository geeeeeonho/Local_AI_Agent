"""Four source applications, one argument parser and composition root."""
from __future__ import annotations
import argparse
import sys
from .specs import SPECS


def parse_args(app,argv=None):
    # 기본값은 '__main__.py' 라서 사용법 줄이 어느 프로그램인지 말해 주지 않는다.
    parser=argparse.ArgumentParser(prog='apps.'+app,
        description='LocalAI Studio / Chat / Interpreter / Setup')
    parser.add_argument('--app',choices=tuple(SPECS),default=None,help='Select a standalone application')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--gui',action='store_true',help='Open the shared desktop shell (default)')
    mode.add_argument('--tui',action='store_true',help='Use the terminal launcher')
    parser.add_argument('--lang',choices=('ko','en'))
    install=parser.add_mutually_exclusive_group()
    install.add_argument('--install',action='store_true',help='Run install / repair (Setup only)')
    install.add_argument('--manage',action='store_true',help='Open the current Setup management app')
    for flag in ('model','sandbox','build','search'):
        parser.add_argument('--skip-'+flag,action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    install_flags=args.install or any(getattr(args,'skip_'+key) for key in ('model','sandbox','build','search'))
    setup_flags=install_flags or args.manage
    if args.manage and install_flags:
        parser.error('--manage cannot be combined with install/skip flags.')
    if args.tui and install_flags:
        parser.error('--tui cannot be combined with install/repair flags.')
    if args.app is None:
        # RUN.bat forwards these flags to the shared parser. Install/skip flags
        # select install/repair; --manage selects the current Setup desktop app.
        args.app='setup' if setup_flags else app
    elif setup_flags and args.app!='setup':
        parser.error('Setup/install flags are valid only for --app setup.')
    if args.manage and args.tui:
        parser.error('--manage opens the desktop Setup app and cannot be combined with --tui.')
    return args


def main(app='studio',argv=None):
    args=parse_args(app,argv)
    from services.system.bootstrap import (run_module_entry, initialize_language,
                                           install_exit_hooks, run_exit_cleanups)
    installer_flags=[]
    for flag in ('install','skip_model','skip_sandbox','skip_build','skip_search'):
        if getattr(args,flag):installer_flags.append('--'+flag.replace('_','-'))
    language=['--lang',args.lang] if args.lang else []
    if args.app=='setup' and installer_flags:
        return run_module_entry('installer',installer_flags+language)
    if args.tui:
        return run_module_entry('launcher',['--tui',*language])
    services=None
    try:
        from services.desktop import create_services
        from .window import DesktopWindow
        from project_paths import PROJECT_ROOT
        # Before anything can start a container: WARP, Tor and the sandbox
        # hand their teardown to these hooks, so a shell without them leaves
        # containers running after the window closes.
        install_exit_hooks(PROJECT_ROOT)
        services=create_services()
        initialize_language(services.project_root,args.lang)
        DesktopWindow(args.app,services).run()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        import traceback
        text=traceback.format_exc()
        if sys.stderr is not None:print(text,file=sys.stderr)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk();root.withdraw()
            messagebox.showerror('LocalAI startup error',str(exc)+'\n\nUse RUN.bat --tui for the terminal launcher.',parent=root)
            root.destroy()
        except Exception:pass
        return 3
    finally:
        if services is not None:
            services.close()
        # Runs the callbacks services.close() does not own — the WARP and Tor
        # containers among them. atexit would eventually do this; doing it here
        # keeps the teardown inside the shutdown the user is waiting on.
        run_exit_cleanups()
