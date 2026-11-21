"""Initialize screen controls before Rich detects the Windows console."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
import sys

from rich.console import Console


def _enable_virtual_terminal():
    if sys.platform != "win32" or not sys.stdout.isatty():
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL

    handle = kernel32.GetStdHandle(wintypes.DWORD(-11).value)
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    # Keep existing flags and enable processed output plus VT screen controls.
    if not kernel32.SetConsoleMode(handle, mode.value | 0x0001 | 0x0004):
        return None
    return kernel32, handle, mode.value


@contextmanager
def terminal_session():
    saved_mode = _enable_virtual_terminal()
    saved_term = os.environ.get("TERM")
    reset_term = saved_mode is not None and (saved_term or "").lower() in {"dumb", "unknown"}
    try:
        # A native console may inherit TERM=dumb from a noninteractive launcher.
        # Rich suppresses every screen control in that mode, even when VT works.
        if reset_term:
            os.environ["TERM"] = "xterm-256color"
        # Explicitly bypass Rich's cached legacy detection after enabling VT.
        console = Console(legacy_windows=False if saved_mode else None)
        with console.screen(hide_cursor=False):
            yield console
    finally:
        if reset_term:
            os.environ["TERM"] = saved_term
        if saved_mode is not None:
            kernel32, handle, mode = saved_mode
            kernel32.SetConsoleMode(handle, mode)
