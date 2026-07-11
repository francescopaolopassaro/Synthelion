# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Cross-process atomic line append — the primitive the lock-free JSONL stores build on.

POSIX guarantees that a single write() to a file descriptor opened with
O_APPEND is atomic: the kernel seeks to EOF and writes in one step, so
concurrent writers from different processes can never interleave or
overwrite each other's bytes.

Windows does NOT give that guarantee through the C runtime's O_APPEND (as
exposed by Python's os.open): the CRT implements it as a separate seek-to-EOF
followed by a write, which is two syscalls — two processes can race between
them and one write silently clobbers part of the other (verified empirically:
an 8-process/1600-write stress test lost ~28% of records with plain
os.open(O_APPEND)). The documented fix on Windows is to open the file handle
with ONLY the FILE_APPEND_DATA access right (not GENERIC_WRITE) via
CreateFileW — the OS then advances the file pointer and writes atomically per
WriteFile call, the same guarantee POSIX gives natively.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE

    _WriteFile = _kernel32.WriteFile
    _WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    _WriteFile.restype = wintypes.BOOL

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _FILE_APPEND_DATA = 0x0004
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_ALWAYS = 4
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    def append_line(path: Path, data: bytes) -> None:
        """Atomically append *data* to *path*, safe across many processes."""
        handle = _CreateFileW(
            str(path),
            _FILE_APPEND_DATA,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_ALWAYS,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE or not handle:
            raise OSError(ctypes.get_last_error(), "CreateFileW failed", str(path))
        try:
            written = wintypes.DWORD(0)
            ok = _WriteFile(handle, data, len(data), ctypes.byref(written), None)
            if not ok:
                raise OSError(ctypes.get_last_error(), "WriteFile failed", str(path))
        finally:
            _CloseHandle(handle)

else:

    def append_line(path: Path, data: bytes) -> None:
        """Atomically append *data* to *path*, safe across many processes."""
        fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
