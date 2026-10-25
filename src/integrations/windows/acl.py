"""Run ``icacls`` and read back what it did, in a language-neutral way.

Two callers need exactly this: the model store has to be readable/manageable by every
account on the machine, and each account's records folder has to be readable
by *no one else*. Both questions are answered by the same descriptor, and both
are asked by running the same tool, so the plumbing lives here once.

Reading goes to the Win32 security API first and to ``icacls`` only when that
is unavailable. ``icacls /save`` needs a temporary file, a child process and a
UTF-16 round trip, and any one of those can fail on a real machine - a Store
Python writes its TEMP into a private copy, an antivirus holds the save file,
a busy machine times the tool out. Every one of those used to come back as the
same "ACL unreadable", which stopped Setup with nothing the user could act on.
``GetNamedSecurityInfoW`` answers in-process and, when it cannot, says why
with a Windows error code.

``core.sddl`` decides what a descriptor means. Nothing here interprets one.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

#: Do not flash a console window out of a GUI process.
NO_WINDOW = 0x08000000

# Win32 values used below. Named here so the ctypes calls read like the API.
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
SDDL_REVISION_1 = 1
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
TOKEN_ELEVATION_CLASS = 20
ERROR_ACCESS_DENIED = 5
ERROR_CANCELLED = 1223

#: SID text as Windows writes it. Anything else from a tool is not a SID.
_SID = re.compile(r'S-1-\d+(?:-\d+)+')

_REASONS = {
    2: '파일을 찾을 수 없음',
    3: '경로를 찾을 수 없음',
    5: '액세스 거부',
    32: '다른 프로세스가 사용 중',
    1223: '사용자가 취소함',
    1332: '계정 이름을 SID로 바꿀 수 없음',
}


def on_windows(windows=None) -> bool:
    return (os.name == 'nt') if windows is None else bool(windows)


def run(command, timeout=20):
    """Run a Windows console tool without decode-thread crashes.

    RUN.bat enables Python UTF-8 mode, but localized Windows tools such as
    icacls and setx still write using the active ANSI code page. Decode those
    bytes with mbcs on Windows and always replace undecodable bytes.
    """
    try:
        encoding = "mbcs" if on_windows() else "utf-8"
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None

def succeeded(result) -> bool:
    return result is not None and result.returncode == 0


def describe_error(code) -> str:
    """A Windows error code in words, keeping the number for a search."""
    if code is None:
        return '알 수 없는 오류'
    reason = _REASONS.get(int(code))
    if reason is None:
        try:
            import ctypes
            reason = ctypes.FormatError(int(code)).strip()
        except (AttributeError, ImportError, OSError, ValueError):
            reason = ''
    return ('Windows 오류 %d (%s)' % (int(code), reason)) if reason else (
        'Windows 오류 %d' % int(code))


# ── the Win32 security API, directly ─────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _api():
    """advapi32/kernel32 with prototypes, or None where there is no Win32."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    except (AttributeError, ImportError, OSError):
        return None
    void_p = ctypes.c_void_p
    out = ctypes.POINTER(ctypes.c_void_p)

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
        out, out, out, out, out]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        void_p, wintypes.DWORD, wintypes.DWORD, out, void_p]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [void_p, out]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [void_p]
    kernel32.LocalFree.restype = void_p
    return ctypes, advapi32, kernel32


def _native_sddl(path, information) -> Tuple[Optional[str], Optional[int]]:
    """(SDDL text, Windows error code) for one part of a descriptor.

    ``(None, None)`` means the API is not there to ask; ``(None, code)`` means
    Windows answered and refused, which is the part a user can act on.
    """
    api = _api()
    if api is None:
        return None, None
    ctypes, advapi32, kernel32 = api
    descriptor = ctypes.c_void_p()
    try:
        status = advapi32.GetNamedSecurityInfoW(
            str(path), SE_FILE_OBJECT, information,
            None, None, None, None, ctypes.byref(descriptor))
    except Exception:  # ctypes.ArgumentError is not an OSError
        return None, None
    if status != 0:
        return None, int(status)
    text = ctypes.c_void_p()
    try:
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, SDDL_REVISION_1, information,
                ctypes.byref(text), None):
            return None, ctypes.get_last_error() or None
        return (ctypes.wstring_at(text.value) if text.value else None), None
    except Exception:  # ctypes.ArgumentError is not an OSError
        return None, None
    finally:
        if text.value:
            kernel32.LocalFree(text)
        if descriptor.value:
            kernel32.LocalFree(descriptor)


def _token_information(token_class):
    """Raw TOKEN_* bytes for this process, or None."""
    api = _api()
    if api is None:
        return None
    ctypes, advapi32, kernel32 = api
    from ctypes import wintypes
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                         TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, token_class, None, 0,
                                         ctypes.byref(size))
            if not size.value:
                return None
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(
                    token, token_class, ctypes.cast(buffer, ctypes.c_void_p),
                    size, ctypes.byref(size)):
                return None
            return buffer
        finally:
            kernel32.CloseHandle(token)
    except Exception:  # ctypes.ArgumentError is not an OSError
        return None


def _native_user_sid() -> Optional[str]:
    buffer = _token_information(TOKEN_USER_CLASS)
    if buffer is None:
        return None
    ctypes, advapi32, kernel32 = _api()
    # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is the PSID.
    sid = ctypes.c_void_p.from_buffer(buffer).value
    if not sid:
        return None
    text = ctypes.c_void_p()
    try:
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        value = ctypes.wstring_at(text.value) if text.value else None
    except Exception:  # ctypes.ArgumentError is not an OSError
        return None
    finally:
        if text.value:
            kernel32.LocalFree(text)
    return value if value and _SID.fullmatch(value) else None


_known_sid: Optional[str] = None


def current_user_sid() -> Optional[str]:
    """The SID this process runs as, e.g. ``S-1-5-21-...-1001``. None off Windows.

    A grant by SID needs no name lookup. ``%USERDOMAIN%\\%USERNAME%`` does, and
    that lookup fails for an Entra ID (``AzureAD\\...``) account, a renamed
    account whose profile folder kept the old name, or a domain account off
    the domain network - in each case the whole icacls call fails and the
    folder is left as it was.
    """
    global _known_sid
    if not on_windows():
        return None
    if _known_sid:
        return _known_sid
    sid = _native_user_sid()
    if not sid:
        result = run(['whoami', '/user', '/fo', 'csv', '/nh'])
        found = _SID.findall(result.stdout or '') if succeeded(result) else []
        sid = found[-1] if found else None
    # A process never changes user, so a found SID is kept; a miss is retried.
    if sid:
        _known_sid = sid
    return sid


def is_elevated() -> Optional[bool]:
    """Is this process running with an elevated (UAC) token? None = unknown."""
    buffer = _token_information(TOKEN_ELEVATION_CLASS)
    if buffer is None:
        return None
    import ctypes
    return bool(ctypes.c_uint32.from_buffer(buffer).value)


# ── reading a descriptor, three ways ─────────────────────────────────────

def _icacls_sddl(path: Path) -> Optional[str]:
    """A folder's DACL in SDDL form, via ``icacls /save``. None if unavailable.

    ``icacls`` on its own prints account names in the language Windows is
    installed in, so reading its normal output meant matching "BUILTIN\\Users"
    against "BUILTIN\\사용자" on a Korean machine. SDDL names that group "BU" in
    every language.
    """
    handle, name = tempfile.mkstemp(prefix='localai-acl-', suffix='.txt')
    os.close(handle)
    saved = Path(name)
    try:
        # icacls will not overwrite an existing save file.
        saved.unlink(missing_ok=True)
        result = run(['icacls', str(path), '/save', str(saved), '/Q'])
        if not succeeded(result) or not saved.is_file():
            return None
        return saved.read_text(encoding='utf-16', errors='replace')
    except (OSError, UnicodeError):
        return None
    finally:
        try:
            saved.unlink(missing_ok=True)
        except OSError:
            pass


def _powershell_sddl(path: Path) -> Optional[str]:
    """``Get-Acl``'s SDDL: no temporary file, a different code path again."""
    if not on_windows():
        return None
    literal = str(path).replace("'", "''")
    result = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                  "[Console]::Out.Write((Get-Acl -LiteralPath '%s').Sddl)" % literal],
                 timeout=30)
    if not succeeded(result):
        return None
    text = (result.stdout or '').strip()
    return text if 'D:' in text else None


def dacl_error(path) -> Optional[int]:
    """Why Windows will not show this folder's DACL, as an error code."""
    _text, error = _native_sddl(path, DACL_SECURITY_INFORMATION)
    return error


def owner_sid(path) -> Optional[str]:
    """Who owns this folder, as a SID (or an SDDL alias such as ``BA``)."""
    text, _error = _native_sddl(path, OWNER_SECURITY_INFORMATION)
    if not text:
        full = _powershell_sddl(Path(path))
        text = full.split('G:')[0].split('D:')[0] if full else None
    if not text or not text.startswith('O:'):
        return None
    return text[2:].strip() or None


def saved_sddl(path: Path) -> Optional[str]:
    """A folder's DACL in SDDL form. None if no method could read it.

    The name is kept from when ``icacls /save`` was the only reader; callers
    look for the ``D:`` line, which every method below provides.
    """
    text, _error = _native_sddl(path, DACL_SECURITY_INFORMATION)
    if text and 'D:' in text:
        return text
    text = _icacls_sddl(Path(path))
    if text and 'D:' in text:
        return text
    return _powershell_sddl(Path(path))


# ── running one repair as administrator ──────────────────────────────────

def run_elevated(executable, parameters, *, timeout=900) -> Tuple[Optional[int], Optional[int]]:
    """Run one program through the UAC prompt and wait for it.

    Returns ``(exit code, None)`` when it ran, ``(None, error code)`` when it
    did not - ``ERROR_CANCELLED`` is the user answering "No". The window stays
    hidden; the UAC prompt itself is the only thing the user sees.
    """
    if os.name != 'nt':
        return None, None
    try:
        import ctypes
        from ctypes import wintypes

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ('cbSize', wintypes.DWORD),
                ('fMask', wintypes.ULONG),
                ('hwnd', wintypes.HWND),
                ('lpVerb', wintypes.LPCWSTR),
                ('lpFile', wintypes.LPCWSTR),
                ('lpParameters', wintypes.LPCWSTR),
                ('lpDirectory', wintypes.LPCWSTR),
                ('nShow', ctypes.c_int),
                ('hInstApp', wintypes.HINSTANCE),
                ('lpIDList', ctypes.c_void_p),
                ('lpClass', wintypes.LPCWSTR),
                ('hkeyClass', wintypes.HKEY),
                ('dwHotKey', wintypes.DWORD),
                ('hIconOrMonitor', wintypes.HANDLE),
                ('hProcess', wintypes.HANDLE),
            ]

        shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        shell32.ShellExecuteExW.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        info.fMask = 0x00000040                 # SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = 'runas'
        info.lpFile = str(executable)
        info.lpParameters = str(parameters)
        info.nShow = 0                          # SW_HIDE
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            return None, ctypes.get_last_error() or None
        if not info.hProcess:
            return None, None
        try:
            waited = kernel32.WaitForSingleObject(info.hProcess,
                                                  int(max(1, timeout) * 1000))
            if waited != 0:
                return None, 1460               # ERROR_TIMEOUT
            code = wintypes.DWORD(0)
            if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
                return None, ctypes.get_last_error() or None
            return int(code.value), None
        finally:
            kernel32.CloseHandle(info.hProcess)
    except Exception:  # ctypes.ArgumentError is not an OSError
        return None, None


__all__ = ['NO_WINDOW', 'ERROR_ACCESS_DENIED', 'ERROR_CANCELLED',
           'on_windows', 'run', 'succeeded', 'describe_error',
           'current_user_sid', 'is_elevated', 'dacl_error', 'owner_sid',
           'saved_sddl', 'run_elevated']
