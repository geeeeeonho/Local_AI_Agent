"""Encrypt bytes with this Windows account's own key (DPAPI).

``CryptProtectData`` with no machine flag binds the result to the signed-in
account: Windows derives the key from that account's logon secret and keeps
it in the account's profile. Another account cannot decrypt it, and neither
can an administrator who takes ownership of the file, copies the disk, or
resets this account's password - a reset makes the old key unrecoverable,
which is the point. Available on every Windows edition, Home included; EFS
and BitLocker are not.

What it does not stop: a program running *as this account* while it is
signed in. That is the account itself, as far as Windows can tell.

The output also carries an integrity check, so a modified file fails to
decrypt instead of decrypting into something else.
"""
from __future__ import annotations

import os
from typing import Optional

CRYPTPROTECT_UI_FORBIDDEN = 0x1

#: Shown by Windows tools that list protected blobs; never used for access.
DESCRIPTION = 'LocalAI'


class DpapiError(OSError):
    """Windows refused to protect or unprotect; ``winerror`` says why."""


def available() -> bool:
    return os.name == 'nt'


def _api():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    blob_p = ctypes.POINTER(DATA_BLOB)
    crypt32.CryptProtectData.argtypes = [
        blob_p, wintypes.LPCWSTR, blob_p, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, blob_p]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_p, ctypes.c_void_p, blob_p, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, blob_p]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return ctypes, DATA_BLOB, crypt32, kernel32


_cached = None


def _loaded():
    global _cached
    if _cached is None:
        _cached = _api()
    return _cached


def _blob(ctypes, DATA_BLOB, data: bytes):
    # A zero-length buffer is not a valid pointer target; DPAPI still gets a
    # length of zero.
    buffer = ctypes.create_string_buffer(bytes(data), max(1, len(data)))
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _call(name, data: bytes, entropy: bytes) -> bytes:
    if not available():
        raise DpapiError(0, 'DPAPI is only available on Windows')
    ctypes, DATA_BLOB, crypt32, kernel32 = _loaded()
    source, keep_source = _blob(ctypes, DATA_BLOB, data)
    extra, keep_extra = (_blob(ctypes, DATA_BLOB, entropy) if entropy
                         else (None, None))
    result = DATA_BLOB()
    function = getattr(crypt32, name)
    description = DESCRIPTION if name == 'CryptProtectData' else None
    ok = function(ctypes.byref(source), description,
                  ctypes.byref(extra) if extra is not None else None,
                  None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result))
    del keep_source, keep_extra
    if not ok:
        code = ctypes.get_last_error()
        raise DpapiError(code, '%s failed (Windows error %d)' % (name, code))
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        if result.pbData:
            kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def protect(data: bytes, entropy: Optional[bytes] = None) -> bytes:
    """Encrypt ``data`` so only this Windows account can read it."""
    return _call('CryptProtectData', data, entropy or b'')


def unprotect(blob: bytes, entropy: Optional[bytes] = None) -> bytes:
    """Decrypt a blob this account protected. Raises on tampering or wrong account."""
    return _call('CryptUnprotectData', blob, entropy or b'')


class Protector:
    """The vault's view of DPAPI: a name and two functions."""

    name = 'dpapi'

    def protect(self, data: bytes) -> bytes:
        return protect(data)

    def unprotect(self, blob: bytes) -> bytes:
        return unprotect(blob)


__all__ = ['DpapiError', 'DESCRIPTION', 'available', 'protect', 'unprotect',
           'Protector']
