"""작업이 끝났을 때 다른 창을 보고 있는 사용자에게 알린다.

창이 이미 앞에 있으면 아무것도 하지 않는다(초록 줄로 충분하다). 뒤에 있으면 Windows에서는 작업
표시줄 단추를 창이 다시 앞으로 올 때까지 깜박이고, 그 밖의 환경에서는 시스템 알림음만 낸다.
알림이 실패해도 작업 결과에는 영향이 없어야 하므로 모든 오류를 삼킨다.
"""
from __future__ import annotations

import sys

FLASHW_TRAY = 0x2          # 작업 표시줄 단추
FLASHW_TIMERNOFG = 0xC     # 창이 앞으로 올 때까지 계속


def _focused(root) -> bool:
    try:
        return root.focus_displayof() is not None
    except Exception:
        return True


def _flash_windows(root) -> bool:
    import ctypes
    from ctypes import wintypes

    class FLASHWINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND), ('dwFlags', wintypes.DWORD),
                    ('uCount', wintypes.UINT), ('dwTimeout', wintypes.DWORD)]

    hwnd = int(root.wm_frame(), 16)
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_TRAY | FLASHW_TIMERNOFG, 0, 0)
    ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    return True


def request_attention(root) -> None:
    """창이 앞에 있지 않을 때만 사용자 주의를 끈다."""
    if _focused(root):
        return
    try:
        if sys.platform == 'win32' and _flash_windows(root):
            return
    except Exception:
        pass
    try:
        root.bell()
    except Exception:
        pass
