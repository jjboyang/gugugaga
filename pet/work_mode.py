"""User-controlled desktop input session and its live count bubble."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pet.work_input import WorkInput


class WorkMode(QObject):
    def __init__(self, window, rig, *, work_input=None):
        super().__init__(window)
        self.window = window
        self.rig = rig
        self.work_input = work_input if work_input is not None else WorkInput()
        self.operations = 0

        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        flags |= Qt.Window if sys.platform == "darwin" else Qt.Tool
        self.bubble = QWidget(window, flags)
        self.bubble.setAttribute(Qt.WA_TranslucentBackground)
        self.bubble.setAttribute(Qt.WA_ShowWithoutActivating)
        self.label = QLabel(self.bubble)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel { color: #283d67; background: #f6f9ff; border: 1px solid #a8bce3;
                border-radius: 12px; padding: 8px 12px; font-size: 13px; font-weight: bold; }
        """)
        layout = QVBoxLayout(self.bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self._input_timer = QTimer(self)
        self._input_timer.setInterval(25)
        self._input_timer.timeout.connect(self._poll_input)
        self._gesture_timer = QTimer(self)
        self._gesture_timer.setSingleShot(True)
        self._gesture_timer.timeout.connect(self.rig.set_work_action)
        window.installEventFilter(self)
        window.work_mode_requested.connect(self.toggle)

    @property
    def active(self):
        return self.window.work_mode_active

    def toggle(self):
        if self.active:
            self.stop()
            return
        self.operations = 0
        self.window.work_mode_active = True
        self.window.stop_waddle()
        self.rig.set_work_mode(True)
        self.work_input.start()
        self._input_timer.start()
        self._refresh_bubble()
        self.bubble.setVisible(self.window.isVisible())

    def stop(self):
        if not self.active:
            return
        self.window.work_mode_active = False
        self._input_timer.stop()
        self._gesture_timer.stop()
        count, _ = self.work_input.stop()
        self.operations += count
        self.rig.set_work_mode(False)
        self.bubble.hide()

    def _poll_input(self):
        if not self.active:
            return
        count, gesture = self.work_input.take()
        self.operations += count
        self._refresh_bubble()
        if gesture is not None:
            action, direction = gesture
            self.rig.set_work_action(action, direction)
            self._gesture_timer.start(550 if action == "typing" else 680)

    def _refresh_bubble(self):
        text = f"工作模式\n操作 {self.operations:,} 次"
        if self.work_input.error:
            text += "\n输入监听不可用"
        if self.label.text() != text:
            self.label.setText(text)
            self.bubble.adjustSize()
            self._position_bubble()
        if self.label.toolTip() != self.work_input.error:
            self.label.setToolTip(self.work_input.error)

    def _position_bubble(self):
        geometry = self.window.frameGeometry()
        screen = self.window.screen()
        x = geometry.right() + 5
        y = geometry.center().y() - self.bubble.height() // 2
        if screen:
            bounds = screen.availableGeometry()
            if x + self.bubble.width() - 1 > bounds.right():
                x = geometry.left() - self.bubble.width() - 4
            x = max(bounds.left(), min(x, bounds.right() - self.bubble.width() + 1))
            y = max(bounds.top(), min(y, bounds.bottom() - self.bubble.height() + 1))
        self.bubble.move(x, y)

    def eventFilter(self, watched, event):
        if watched is self.window and self.active:
            if event.type() in {QEvent.Move, QEvent.Resize, QEvent.Show}:
                self._position_bubble()
                self.bubble.setVisible(self.window.isVisible())
            elif event.type() == QEvent.Hide:
                self.bubble.hide()
            elif event.type() == QEvent.Close:
                self.stop()
        return super().eventFilter(watched, event)
