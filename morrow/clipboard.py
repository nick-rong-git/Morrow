"""读取用户在 Windows 上刚复制的文本。"""

try:
    import win32clipboard
    from pywintypes import error as ClipboardError
except ImportError:
    win32clipboard = None
    ClipboardError = OSError


def clipboard_sequence() -> int | None:
    if win32clipboard is None:
        return None
    try:
        return win32clipboard.GetClipboardSequenceNumber() or None
    except ClipboardError:
        return None


def read_copied_text(previous_sequence: int) -> str:
    if win32clipboard is None:
        return ""
    try:
        win32clipboard.OpenClipboard()
        try:
            current = clipboard_sequence()
            if current is None or current == previous_sequence:
                return ""
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except ClipboardError:
        pass
    return ""
