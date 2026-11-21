import ctypes
from ctypes import wintypes
import os
from unittest import TestCase
from unittest.mock import Mock, patch

from morrow import terminal


class TerminalRegressions(TestCase):
    def test_windows_enables_screen_controls_before_rich_detection(self):
        kernel32 = Mock()
        original_mode = 0x0002

        def get_mode(handle, pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = original_mode
            return True

        kernel32.GetConsoleMode.side_effect = get_mode
        with (
            patch.object(terminal.sys, "platform", "win32"),
            patch.object(terminal.sys, "stdout", Mock(isatty=Mock(return_value=True))),
            patch.object(terminal.ctypes, "WinDLL", return_value=kernel32, create=True),
            patch.object(terminal, "Console") as console_type,
            patch.dict(os.environ, {"TERM": "dumb"}),
        ):
            def create_console(**kwargs):
                kernel32.SetConsoleMode.assert_called_once_with(kernel32.GetStdHandle.return_value, 7)
                self.assertEqual(os.environ["TERM"], "xterm-256color")
                return console_type.return_value

            console_type.side_effect = create_console
            with terminal.terminal_session():
                pass
            self.assertEqual(os.environ["TERM"], "dumb")
        console_type.assert_called_once_with(legacy_windows=False)
        self.assertEqual(kernel32.SetConsoleMode.call_args.args[1], original_mode)

    def test_screen_and_console_mode_are_restored_after_error(self):
        kernel32 = Mock()
        with (
            patch.object(terminal, "_enable_virtual_terminal", return_value=(kernel32, 42, 3)),
            patch.object(terminal, "Console") as console_type,
        ):
            with self.assertRaisesRegex(RuntimeError, "connection failed"):
                with terminal.terminal_session():
                    raise RuntimeError("connection failed")
        screen = console_type.return_value.screen
        screen.assert_called_once_with(hide_cursor=False)
        self.assertIs(screen.return_value.__exit__.call_args.args[0], RuntimeError)
        kernel32.SetConsoleMode.assert_called_once_with(42, 3)

    def test_redirected_output_does_not_enable_windows_controls(self):
        with (
            patch.object(terminal.sys, "platform", "win32"),
            patch.object(terminal.sys, "stdout", Mock(isatty=Mock(return_value=False))),
            patch.object(terminal.ctypes, "WinDLL", create=True) as load_dll,
        ):
            self.assertIsNone(terminal._enable_virtual_terminal())
        load_dll.assert_not_called()
