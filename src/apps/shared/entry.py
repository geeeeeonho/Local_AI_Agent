"""Four source applications, one argument parser and composition root."""
from __future__ import annotations
import argparse
import sys
from .specs import SPECS


def parse_args(app,argv=None):
    parser=argparse.ArgumentParser(description='LocalAI Studio / Chat / Interpreter / Setup')
    parser.add_argument('--app',choices=tuple(SPECS),default=app,help='Select a standalone application')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--gui',action='store_true',help='Open the shared desktop shell (default)')
    mode.add_argument('--tui',action='store_true',help='Use the retained legacy terminal launcher')
    parser.add_argument('--lang',choices=('ko','en'))
    install=parser.add_mutually_exclusive_group()
    install.add_argument('--install',action='store_true',help='Run the explicit legacy installer (Setup only)')
    install.add_argument('--manage',action='store_true',help='Open retained installer management (Setup only)')
    for flag in ('model','sandbox','build','search'):
        parser.add_argument('--skip-'+flag,action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    flags=args.install or args.manage or any(getattr(args,'skip_'+key) for key in ('model','sandbox','build','search'))
    if flags and args.app!='setup':parser.error('Installation flags are valid only for --app setup.')
    return args


def main(app='studio',argv=None):
    args=parse_args(app,argv)
    from services.system.bootstrap import legacy_entry, initialize_language
    installer_flags=[]
    for flag in ('install','manage','skip_model','skip_sandbox','skip_build','skip_search'):
        if getattr(args,flag):installer_flags.append('--'+flag.replace('_','-'))
    language=['--lang',args.lang] if args.lang else []
    if args.app=='setup' and installer_flags:
        return legacy_entry('installer',installer_flags+language)
    if args.tui:
        return legacy_entry('launcher',['--tui',*language])
    services=None
    try:
        from services.desktop import create_services
        from .window import DesktopWindow
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
            messagebox.showerror('LocalAI startup error',str(exc)+'\n\nUse RUN.bat --tui for the legacy terminal launcher.',parent=root)
            root.destroy()
        except Exception:pass
        return 3
    finally:
        if services is not None:
            services.close()
