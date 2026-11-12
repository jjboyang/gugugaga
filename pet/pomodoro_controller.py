"""Qt lifecycle and a small desktop countdown for the Pomodoro model."""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from pet.pomodoro import PomodoroTimer
from pet.pomodoro_panel import PomodoroPanel
from pet.work_input import WorkInput


class PomodoroController(QObject):
    """Keep counting when the panel is closed, without taking keyboard focus."""

    def __init__(self, window, rig, *, model=None, work_input=None, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.rig = rig
        self._owns_visuals = False
        self.work_input = work_input if work_input is not None else WorkInput()
        self.model = model if model is not None else PomodoroTimer(
            Path(os.environ.get(
                "DESKTOP_PET_POMODORO_PATH",
                str(Path.home() / ".desktop-pet" / "pomodoro.json"),
            ))
        )
        self.panel = PomodoroPanel(self.model, window)
        self.panel.action_starting.connect(self._before_action)
        self.panel.action_taken.connect(self._on_action)
        badge_flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        # Qt.Tool becomes an auto-hiding NSPanel on macOS, just as for the pet.
        badge_flags |= Qt.Window if sys.platform == "darwin" else Qt.Tool
        self.badge = QWidget(window, badge_flags)
        self.badge.setAttribute(Qt.WA_TranslucentBackground)
        self.badge.setAttribute(Qt.WA_ShowWithoutActivating)
        self.badge.setFocusPolicy(Qt.NoFocus)
        self.badge.setStyleSheet("""
            QPushButton { color: #283d67; background: #f6f9ff; border: 1px solid #a8bce3;
                border-radius: 12px; padding: 8px 12px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #e9f0ff; }
        """)
        layout = QVBoxLayout(self.badge)
        layout.setContentsMargins(0, 0, 0, 0)
        self.badge_button = QPushButton(self.badge)
        self.badge_button.setFocusPolicy(Qt.NoFocus)
        self.badge_button.setCursor(Qt.PointingHandCursor)
        self.badge_button.clicked.connect(self.open_panel)
        layout.addWidget(self.badge_button)
        window.installEventFilter(self)
        window.pomodoro_requested.connect(self.open_panel)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self._input_timer = QTimer(self)
        self._input_timer.setInterval(25)
        self._input_timer.timeout.connect(self._poll_input)
        self._gesture_timer = QTimer(self)
        self._gesture_timer.setSingleShot(True)
        self._gesture_timer.timeout.connect(self.rig.set_focus_action)
        self.timer.start()
        self.refresh()

    def open_panel(self):
        self.panel.refresh()
        if not self.panel.isVisible():
            self.panel.adjustSize()
            screen = self.window.screen()
            if screen:
                bounds = screen.availableGeometry()
                x = self.window.x() - self.panel.width() - 12
                y = self.window.y() + self.window.height() - self.panel.height()
                self.panel.move(
                    max(bounds.left(), min(x, bounds.right() - self.panel.width() + 1)),
                    max(bounds.top(), min(y, bounds.bottom() - self.panel.height() + 1)),
                )
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def _on_action(self, events):
        self._handle_events(events or [])
        self.refresh()

    def _before_action(self, name):
        if name in {"pause", "reset"}:
            self._stop_input()

    def _poll_input(self):
        count, gesture = self.work_input.take()
        if count:
            self.model.record_focus_operations(count)
            self._refresh_badge()
        if gesture is not None:
            action, direction = gesture
            self.rig.set_focus_action(action, direction)
            self._gesture_timer.start(550 if action == "typing" else 680)

    def _stop_input(self):
        if self._input_timer.isActive():
            self._input_timer.stop()
            count, _ = self.work_input.stop()
            self.model.record_focus_operations(count)
        self._gesture_timer.stop()
        self.rig.set_focus_action()

    def _tick(self):
        if self._input_timer.isActive():
            self._poll_input()
        self._handle_events(self.model.tick())
        self.refresh()

    def _handle_events(self, events):
        if any(event in {"focus_done", "break_done", "activity_due"} for event in events):
            QApplication.beep()
            QApplication.alert(self.window, 5000)

    def refresh(self):
        phase = self.model.phase
        due = self.model.focus_since_activity >= 120 * 60
        if phase == "focus" and not self.model.paused:
            if not self._input_timer.isActive():
                self.work_input.start()
                self._input_timer.start()
        elif self._input_timer.isActive():
            self._stop_input()
        # A completed focus session always gets its bell animation, including
        # when the activity reminder is already waiting for acknowledgement.
        mode = "activity" if due and phase != "focus_done" else phase
        if mode != "idle" and not self._owns_visuals:
            self.window.stop_waddle()
        self._owns_visuals = mode != "idle"
        self.rig.set_pomodoro(mode, paused=self.model.paused)
        self._refresh_badge()
        if self.panel.isVisible():
            self.panel.refresh()

    def _refresh_badge(self):
        phase = self.model.phase
        due = self.model.focus_since_activity >= 120 * 60
        seconds = max(0, math.ceil(self.model.remaining_seconds))
        countdown = f"{seconds // 60:02d}:{seconds % 60:02d}"
        if due:
            text = "已专注 2 小时 · 起来活动一下"
            if phase in {"focus", "break"}:
                label = "专注" if phase == "focus" else "休息"
                text = f"{label} {countdown}" + (" · 已暂停" if self.model.paused else "") + "\n" + text
        elif phase in {"focus", "break"}:
            label = "专注" if phase == "focus" else "休息"
            text = f"{label} {countdown}" + (" · 已暂停" if self.model.paused else "")
        elif phase == "focus_done":
            text = "叮！专注完成 · 休息一下 →"
        else:
            text = "休息结束 · 开始下一轮 →"
        tooltip = "点击打开番茄时钟和专注统计"
        if phase in {"focus", "focus_done"}:
            text += f"\n操作 {self.model.focus_operations:,} 次"
            if phase == "focus" and not self.model.paused and self.work_input.error:
                text += " · 监听不可用"
                tooltip = self.work_input.error
        if self.badge_button.text() != text:
            self.badge_button.setText(text)
            self.badge.adjustSize()
            self._position_badge()
        self.badge_button.setToolTip(tooltip)
        self.badge.setVisible((phase != "idle" or due) and self.window.isVisible())

    def _position_badge(self):
        geometry = self.window.frameGeometry()
        screen = self.window.screen()
        x = geometry.center().x() - self.badge.width() // 2
        y = geometry.top() - self.badge.height() - 4
        if screen:
            bounds = screen.availableGeometry()
            x = max(bounds.left(), min(x, bounds.right() - self.badge.width() + 1))
            if y < bounds.top():
                y = geometry.bottom() + 4
            y = max(bounds.top(), min(y, bounds.bottom() - self.badge.height() + 1))
        self.badge.move(QPoint(x, y))

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() in {QEvent.Move, QEvent.Resize, QEvent.Show}:
                self._position_badge()
                self.badge.setVisible(
                    (self.model.phase != "idle" or self.model.focus_since_activity >= 7200)
                    and self.window.isVisible()
                )
            elif event.type() in {QEvent.Hide, QEvent.Close}:
                self.badge.hide()
        return super().eventFilter(watched, event)

    def shutdown(self):
        self.timer.stop()
        self._stop_input()
        self.model.shutdown()
        self.panel.close()
        self.badge.hide()
