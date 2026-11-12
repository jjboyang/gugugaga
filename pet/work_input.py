"""Passive desktop input counts for the current focus session."""
from __future__ import annotations

import os
import sys
from threading import Lock, Thread
from time import sleep


class WorkInput:
    def __init__(self):
        self._lock = Lock()
        self._session = None
        self._listeners = []
        self._pending = 0
        self._gesture = None
        self.error = ""

    def start(self):
        session = object()
        self._session = session
        self.error = ""

        def record(gesture=None):
            with self._lock:
                if self._session is not session:
                    return
                self._pending += 1
                if gesture is not None:
                    self._gesture = gesture

        def scroll(_x, _y, dx, dy, *_):
            delta = dy or dx
            if delta:
                record(("scroll", 1 if delta > 0 else -1))

        def click(_x, _y, _button, pressed, *_):
            if pressed:
                record()

        def windows_mouse_filter(message, data):
            # Use the raw delta for high-resolution wheels. Returning False
            # skips pynput's duplicate callback without swallowing OS input.
            if message in (0x020A, 0x020E):  # WM_MOUSEWHEEL / WM_MOUSEHWHEEL
                delta = (data.mouseData >> 16) & 0xFFFF
                if delta:
                    record(("scroll", -1 if delta & 0x8000 else 1))
                return False
            return True

        try:
            if sys.platform.startswith("linux"):
                if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
                    self.error = "全局输入统计需要 X11 桌面会话。"
                    return
            if sys.platform == "darwin":
                from Quartz import CGPreflightListenEventAccess

                if not CGPreflightListenEventAccess():
                    self.error = "请在系统设置 → 隐私与安全性 → 输入监控中授权启动桌宠的应用，随后重启桌宠。"
                    return
            from pynput import keyboard, mouse

            options = {"win32_event_filter": windows_mouse_filter} if sys.platform == "win32" else {}
            listeners = (
                keyboard.Listener(on_press=lambda *_: record(("typing", 0)), suppress=False),
                mouse.Listener(on_click=click, on_scroll=scroll, suppress=False, **options),
            )
            for listener in listeners:
                listener.start()
                self._listeners.append(listener)
        except (ImportError, OSError, RuntimeError):
            self.error = "无法启动全局输入监听，请检查桌面会话及桌宠依赖。"
            self.stop()

    def take(self):
        """Drain a count and the latest animation cue, with no key or pointer data."""
        if any(not listener.is_alive() for listener in self._listeners):
            self.error = "全局输入监听已停止，暂停并继续专注可重试。"
            return self.stop()
        with self._lock:
            pending = self._pending, self._gesture
            self._pending, self._gesture = 0, None
        return pending

    def stop(self):
        with self._lock:
            self._session = None
            pending = self._pending, self._gesture
            self._pending, self._gesture = 0, None
        if self._listeners:
            # Some backends wait for their OS message loop during shutdown.
            listeners, self._listeners = self._listeners, []
            Thread(target=self._stop_listeners, args=(listeners,), daemon=True).start()
        return pending

    @staticmethod
    def _stop_listeners(listeners):
        for listener in listeners:
            # A pause can race with the listener thread entering run().
            while listener.is_alive() and not listener.running:
                sleep(0.005)
            if listener.is_alive():
                listener.stop()
