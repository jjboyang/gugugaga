"""Exercise shared timer, desktop badge, rig ownership and Qt window lifecycle."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.animation import AnimationEngine
from pet.pomodoro import PomodoroTimer
from pet.pomodoro_controller import PomodoroController
from pet.rig_animator import RigAnimator
from pet.window import PetWindow


ASSETS = Path(__file__).resolve().parents[1] / "pet/characters/dafeiyu/rig"


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 11, 5, 9)
        self.seconds = 0.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.seconds += seconds


class PomodoroIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = Clock()
        self.path = Path(self.directory.name) / "focus.json"
        self.model = PomodoroTimer(
            self.path, now=self.clock.now, monotonic=self.clock.monotonic,
        )
        with patch("pet.window._load_config", return_value={}):
            self.window = PetWindow()
        self.engine = AnimationEngine()
        self.engine.set_state("idle")
        self.rig = RigAnimator(self.engine, self.window, ASSETS)
        self.rig.frame_changed.connect(self.window.set_pixmap)
        self.controller = PomodoroController(self.window, self.rig, model=self.model)
        self.controller.timer.stop()
        self.window.drag_started.connect(self.engine.begin_drag)
        self.window.drag_started.connect(self.rig.notify_drag_started)
        self.window.drag_ended.connect(self.engine.end_drag)
        self.window.drag_ended.connect(self.rig.notify_drag_ended)
        self.window.show()
        self.window.move(250, 300)
        self.rig.set_enabled(True)
        self.rig.timer.stop()
        self.addCleanup(self.cleanup_pet)
        self.beep = patch.object(QApplication, "beep")
        self.beep_mock = self.beep.start()
        self.addCleanup(self.beep.stop)
        self.alert = patch.object(QApplication, "alert")
        self.alert.start()
        self.addCleanup(self.alert.stop)

    def cleanup_pet(self):
        self.controller.shutdown()
        self.rig.stop()
        for timer in self.engine.findChildren(QTimer):
            timer.stop()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def start_focus(self):
        self.window.pomodoro_requested.emit()
        self.controller.panel.primary_button.click()
        self.assertEqual(self.model.phase, "focus")

    def advance(self, seconds):
        self.clock.advance(seconds)
        self.controller._tick()

    def test_closed_panel_keeps_counting_and_badge_tracks_pet(self):
        self.start_focus()
        self.controller.panel.close()
        self.assertFalse(self.controller.panel.isVisible())
        self.controller.timer.start()
        self.clock.advance(61)
        QTest.qWait(320)
        self.controller.timer.stop()
        self.assertEqual(self.model.remaining_seconds, 1439)
        self.assertTrue(self.controller.badge.isVisible())
        self.assertIn("23:59", self.controller.badge_button.text())
        previous = self.controller.badge.pos()
        self.window.move(self.window.pos() + QPoint(30, -20))
        self.app.processEvents()
        self.assertEqual(self.controller.badge.pos(), previous + QPoint(30, -20))
        with patch("pet.window._save_config"):
            self.window._on_size_changed(220)
        self.app.processEvents()
        self.assertLessEqual(abs(
            self.controller.badge.geometry().center().x()
            - self.window.frameGeometry().center().x()
        ), 1)
        self.assertLess(self.controller.badge.geometry().bottom(), self.window.y())

    def test_focus_blocks_sleep_and_walking_but_drag_and_latest_ipc_survive(self):
        self.window.start_waddle()
        self.assertTrue(self.window._waddle_move_timer.isActive())
        self.start_focus()
        self.assertFalse(self.window._waddle_move_timer.isActive())
        origin = self.window.pos()
        self.engine.set_state("sleep")
        self.rig.idle_behavior.force_action("walk")
        with patch.object(self.rig.renderer, "render", wraps=self.rig.renderer.render) as render:
            self.rig._paint(1.0)
            pose = render.call_args.args[0]
            self.assertEqual(pose.phase, "idle")
            self.assertEqual(pose.sleep_blend, 0)
            self.assertEqual(pose.idle_action, "")
        self.assertEqual(self.window.pos(), origin)

        self.window.drag_started.emit()
        self.assertEqual(self.engine.current_phase, "dragged")
        self.engine.set_state("reading")
        with patch.object(self.rig.pomodoro_renderer, "paint", wraps=self.rig.pomodoro_renderer.paint) as overlay:
            self.rig._paint(0.1)
            overlay.assert_not_called()
        self.window.drag_ended.emit()
        self.rig.timer.stop()
        self.assertEqual(self.engine.current_phase, "reading")
        self.assertEqual(self.rig.pomodoro_mode, "focus")
        self.controller.panel.reset_button.click()
        self.assertEqual(self.rig.pomodoro_mode, "idle")
        with patch.object(self.rig.renderer, "render", wraps=self.rig.renderer.render) as render:
            self.rig._paint(0.1)
            self.assertEqual(render.call_args.args[0].phase, "reading")
        self.assertFalse(self.controller.badge.isVisible())

    def test_focus_and_break_complete_once_and_wait_for_user(self):
        self.start_focus()
        self.advance(1500)
        self.assertEqual(self.model.phase, "focus_done")
        self.assertEqual(self.model.stats()["today_pomodoros"], 1)
        self.assertEqual(self.rig.pomodoro_mode, "focus_done")
        self.assertEqual(self.beep_mock.call_count, 1)
        self.advance(3600)
        self.assertEqual(self.model.phase, "focus_done")
        self.assertEqual(self.model.stats()["today_focus_seconds"], 1500)
        self.assertEqual(self.model.stats()["today_pomodoros"], 1)
        self.assertEqual(self.beep_mock.call_count, 1)
        self.controller.panel.primary_button.click()
        self.assertEqual(self.model.phase, "break")
        self.assertIn("05:00", self.controller.badge_button.text())
        self.advance(300)
        self.assertEqual(self.model.phase, "break_done")
        self.assertEqual(self.model.stats()["today_focus_seconds"], 1500)
        self.assertEqual(self.beep_mock.call_count, 2)
        self.advance(300)
        self.assertEqual(self.beep_mock.call_count, 2)

    def test_pause_holds_current_art_and_animation_time_then_resumes(self):
        self.start_focus()
        self.rig._paint(1.25)
        previous_time = self.rig._pomodoro_elapsed
        captured = []
        self.rig.frame_changed.connect(lambda image: captured.append(image.toImage()))
        self.rig._paint(0)
        last = captured[-1]
        self.rig.set_pomodoro("focus", paused=True)
        self.rig._paint(10)
        self.assertEqual(captured[-1], last)
        self.assertEqual(self.rig._pomodoro_elapsed, previous_time)
        # Dragging still has priority even when the Pomodoro art is paused.
        self.window.drag_started.emit()
        self.assertNotEqual(captured[-1], last)
        self.window.drag_ended.emit()
        self.rig.timer.stop()
        self.rig._paint(1)
        self.assertEqual(captured[-1], last)
        self.rig.set_pomodoro("focus", paused=False)
        self.rig._paint(0.2)
        self.assertAlmostEqual(self.rig._pomodoro_elapsed, previous_time + 0.2)
        self.assertNotEqual(captured[-1], last)

    def test_two_hour_reminder_persists_until_user_acknowledges_activity(self):
        self.start_focus()
        for _ in range(4):
            self.advance(1500)
            self.controller.panel.primary_button.click()
            self.advance(300)
            self.controller.panel.primary_button.click()
        self.advance(1200)
        self.assertEqual(self.model.focus_since_activity, 7200)
        self.assertEqual(self.rig.pomodoro_mode, "activity")
        self.assertFalse(self.controller.panel.activity_banner.isHidden())
        self.assertIn("起来活动", self.controller.badge_button.text())
        self.assertIn("05:00", self.controller.badge_button.text())
        beeps = self.beep_mock.call_count
        self.advance(1)
        self.assertEqual(self.beep_mock.call_count, beeps)
        self.controller.panel.activity_button.click()
        self.assertEqual(self.model.focus_since_activity, 0)
        self.assertEqual(self.rig.pomodoro_mode, "focus")
        self.assertTrue(self.controller.panel.activity_banner.isHidden())
        self.assertIn("04:59", self.controller.badge_button.text())

    def test_focus_bell_keeps_priority_when_activity_reminder_is_pending(self):
        self.start_focus()
        for _ in range(4):
            self.advance(1500)
            self.controller.panel.primary_button.click()
            self.advance(300)
            self.controller.panel.primary_button.click()
        self.advance(1200)
        self.assertEqual(self.rig.pomodoro_mode, "activity")
        self.advance(300)
        self.assertEqual(self.rig.pomodoro_mode, "focus_done")
        self.assertIn("起来活动", self.controller.badge_button.text())
        self.assertFalse(self.controller.panel.activity_banner.isHidden())

    def test_shutdown_checkpoints_and_restores_paused_without_offline_credit(self):
        self.start_focus()
        self.advance(90)
        self.controller.shutdown()
        self.assertFalse(self.controller.timer.isActive())
        self.assertTrue(self.model.paused)
        self.assertFalse(self.controller.badge.isVisible())
        self.clock.advance(86400)
        restored = PomodoroTimer(self.path, now=self.clock.now, monotonic=self.clock.monotonic)
        self.assertEqual(restored.phase, "focus")
        self.assertTrue(restored.paused)
        self.assertEqual(restored.remaining_seconds, 1410)
        restored.tick()
        self.assertEqual(restored.remaining_seconds, 1410)
        self.assertEqual(restored.stats()["today_focus_seconds"], 0)
        self.assertEqual(restored.stats()["week_focus_seconds"], 90)


if __name__ == "__main__":
    unittest.main()
