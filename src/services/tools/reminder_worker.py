"""Studio와 독립적으로 실행하는 사용자별 로컬 알림 프로세스.

외부 캘린더/MCP/LLM이 필요하지 않습니다. Windows HKCU Run 자동 시작은
사용자가 명시적으로 요청할 때만 등록합니다.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

# Windows pythonw가 이 파일을 직접 실행해도 src 경로를 찾을 수 있도록 합니다.
if __name__ == '__main__' and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'
_REG_NAME = 'LocalAI-Reminders'


def _launcher() -> tuple[str, str]:
    script = str(Path(__file__).resolve())
    executable = Path(sys.executable)
    if os.name == 'nt':
        pythonw = executable.with_name('pythonw.exe')
        if pythonw.exists():
            executable = pythonw
    return str(executable), script


class ReminderManager:
    """Win11 계정별 알림 실행/시작 프로그램 등록. 설정만으로 설치하지 않습니다."""
    def is_registered(self) -> bool:
        if os.name != 'nt':
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
                value, _ = winreg.QueryValueEx(key, _REG_NAME)
        except FileNotFoundError:
            return False
        executable, script = _launcher()
        return value == f'"{executable}" "{script}"'

    def register(self) -> None:
        if os.name != 'nt':
            raise RuntimeError('로그인 자동 실행은 Windows에서만 지원합니다.')
        import winreg
        exe, script = _launcher()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _REG_NAME, 0, winreg.REG_SZ, f'"{exe}" "{script}"')

    def unregister(self) -> None:
        if os.name != 'nt':
            raise RuntimeError('로그인 자동 실행은 Windows에서만 지원합니다.')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _REG_NAME)
        except FileNotFoundError:
            pass

    def start_now(self) -> int:
        if os.name != 'nt':
            raise RuntimeError('백그라운드 알림 실행은 Windows에서만 지원합니다.')
        exe, script = _launcher()
        proc = subprocess.Popen([exe, script], cwd=str(Path(script).parents[2]),
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=(subprocess.DETACHED_PROCESS |
                                               subprocess.CREATE_NEW_PROCESS_GROUP))
        return proc.pid


def _log(message: str):
    try:
        from project_paths import LOGS_DIR
        from core.vault import open_log
        path = LOGS_DIR / 'reminder_worker.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        with open_log(path, 'a') as stream:
            stream.write(datetime.now().isoformat(timespec='seconds') + ' ' + str(message)[:500] + '\n')
    except (OSError, ValueError):
        pass


def run() -> None:
    from core.persistence import file_lock
    from project_paths import USER_DATA_DIR
    from services.tools.calendar import CalendarService

    path = USER_DATA_DIR / 'tools' / 'calendar' / 'items.json'
    lock_path = path.parent / 'reminder-worker.lock'
    service = CalendarService(path)
    try:
        # 두 번 실행됐을 때 같은 일정 알림이 중복되지 않도록 한 프로세스만 유지합니다.
        with file_lock(lock_path, timeout=0):
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
            root.withdraw()
            active = []

            def notify(item):
                popup = tk.Toplevel(root)
                popup.title('LocalAI 알림')
                popup.resizable(False, False)
                popup.attributes('-topmost', True)
                position = len(active)
                width, height = 355, 140
                x = max(0, root.winfo_screenwidth() - width - 30)
                y = max(0, root.winfo_screenheight() - height - 80 - position * (height + 8))
                popup.geometry(f'{width}x{height}+{x}+{y}')
                content = ttk.Frame(popup, padding=14)
                content.pack(fill='both', expand=True)
                ttk.Label(content, text='LocalAI 일정 알림', font=('Segoe UI', 11, 'bold')).pack(anchor='w')
                ttk.Label(content, text=item['title'], wraplength=315).pack(anchor='w', pady=(8, 4))
                ttk.Label(content, text=item['occurrence_at'].replace('T', ' ')).pack(anchor='w')
                ttk.Button(content, text='확인', command=popup.destroy).pack(anchor='e')
                active.append(popup)
                popup.bind('<Destroy>', lambda _e, p=popup: active.remove(p) if p in active else None)
                popup.after(60000, lambda p=popup: p.destroy() if p.winfo_exists() else None)
                try:
                    root.bell()
                except tk.TclError:
                    pass

            def poll():
                try:
                    for item in service.claim_due(limit=5):
                        notify(item)
                except Exception as exc:
                    _log('알림 검사 실패: ' + str(exc))
                root.after(20000, poll)

            root.after(500, poll)
            root.mainloop()
    except TimeoutError:
        # 이미 내 계정의 알림 worker가 실행 중입니다.
        return
    except Exception as exc:
        _log('알림 worker 시작 실패: ' + str(exc))
        raise


if __name__ == '__main__':
    run()