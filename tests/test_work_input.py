"""Count passive input once, and discard callbacks from a closed session."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pet.work_input import WorkInput


class WorkInputTests(unittest.TestCase):
    def test_counts_raw_windows_wheel_and_ignores_releases_and_closed_sessions(self):
        keyboard = Mock()
        mouse = Mock()
        backend = SimpleNamespace(keyboard=keyboard, mouse=mouse)
        source = WorkInput()
        with patch.dict("sys.modules", {"pynput": backend}), patch("pet.work_input.sys.platform", "win32"):
            source.start()
            self.addCleanup(source.stop)
            on_press = keyboard.Listener.call_args.kwargs["on_press"]
            handlers = mouse.Listener.call_args.kwargs
            on_press(object(), False)
            handlers["on_click"](50, 40, object(), True, False)
            handlers["on_click"](50, 40, object(), False, False)
            handlers["on_scroll"](50, 40, 0, 0, False)
            self.assertFalse(handlers["win32_event_filter"](0x020A, SimpleNamespace(mouseData=60 << 16)))
            self.assertEqual(source.take(), (3, ("scroll", 1)))

            on_press(object(), False)
            self.assertEqual(source.stop(), (1, ("typing", 0)))
            source.start()
            on_press(object(), False)
            self.assertEqual(source.take(), (0, None))
            keyboard.Listener.call_args.kwargs["on_press"](object(), False)
            self.assertEqual(source.take(), (1, ("typing", 0)))
