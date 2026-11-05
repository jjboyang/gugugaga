"""Check controls and live display against a controllable shared timer."""
import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.pomodoro_panel import PomodoroPanel


class FakeTimer:
    def __init__(self):
        self.phase = "idle"
        self.paused = False
        self.remaining_seconds = 1500
        self.elapsed_seconds = 0
        self.focus_since_activity = 0
        self.storage_error = None
        self.focus_seconds = 0
        self.actions = []

    def stats(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        return dict(
            today_focus_seconds=self.focus_seconds,
            today_pomodoros=2, streak_days=3, week_focus_seconds=7500,
            week_days=[dict(date=(monday + timedelta(days=i)).isoformat(),
                            focus_seconds=1500 if i == 0 else 0, pomodoros=1 if i == 0 else 0)
                       for i in range(7)],
        )

    def start_focus(self):
        self.actions.append("start_focus")
        self.phase, self.paused = "focus", False
        return ["started"]

    def start_break(self):
        self.actions.append("start_break")
        self.phase, self.paused = "break", False
        self.remaining_seconds, self.elapsed_seconds = 300, 0
        return []

    def pause(self):
        self.actions.append("pause")
        self.paused = True
        return []

    def resume(self):
        self.actions.append("resume")
        self.paused = False
        return []

    def reset(self):
        self.actions.append("reset")
        self.phase, self.paused = "idle", False
        return []

    def mark_activity(self):
        self.actions.append("mark_activity")
        self.focus_since_activity = 0
        return []


class PomodoroPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.timer = FakeTimer()
        self.panel = PomodoroPanel(self.timer)
        self.addCleanup(self.panel.deleteLater)

    def test_controls_drive_shared_model_and_report_events(self):
        events = []
        self.panel.action_taken.connect(events.append)
        self.panel.primary_button.click()
        self.assertEqual(self.timer.phase, "focus")
        self.assertEqual(events, [["started"]])
        self.panel.primary_button.click()
        self.assertTrue(self.timer.paused)
        self.assertEqual(self.panel.primary_button.text(), "继续计时")
        self.panel.primary_button.click()
        self.assertFalse(self.timer.paused)
        self.assertEqual(self.timer.actions, ["start_focus", "pause", "resume"])

    def test_completed_focus_offers_break_and_close_keeps_it_running(self):
        self.timer.phase = "focus_done"
        self.timer.remaining_seconds = 0
        self.timer.elapsed_seconds = 1500
        self.panel.refresh()
        self.assertEqual(self.panel.countdown_label.text(), "00:00")
        self.panel.primary_button.click()
        self.assertEqual(self.timer.phase, "break")
        self.assertEqual(self.panel.countdown_label.text(), "05:00")
        self.panel.close()
        self.assertEqual(self.timer.phase, "break")
        self.assertFalse(self.timer.paused)

    def test_refresh_updates_countdown_partial_time_and_activity_reminder(self):
        self.timer.phase = "focus"
        self.timer.remaining_seconds = 902.2
        self.timer.elapsed_seconds = 597.8
        self.timer.focus_seconds = 597.8
        self.timer.focus_since_activity = 7200
        self.panel.refresh()
        self.assertEqual(self.panel.countdown_label.text(), "15:03")
        self.assertEqual(self.panel.stat_values["today_focus_seconds"].text(), "9 分钟")
        self.assertEqual(self.panel.stat_values["today_pomodoros"].text(), "2 个")
        self.assertEqual(self.panel.stat_values["streak_days"].text(), "3 天")
        self.assertEqual(self.panel.stat_values["week_focus_seconds"].text(), "2 小时 05 分钟")
        self.assertFalse(self.panel.activity_banner.isHidden())
        self.panel.activity_button.click()
        self.assertTrue(self.panel.activity_banner.isHidden())

    def test_storage_failure_is_visible_and_chart_renders(self):
        self.timer.storage_error = "Permission denied"
        self.panel.refresh()
        self.assertFalse(self.panel.storage_label.isHidden())
        self.assertIn("暂未保存", self.panel.storage_label.text())
        self.panel.show()
        self.app.processEvents()
        self.assertFalse(self.panel.grab().isNull())
        self.panel.close()


if __name__ == "__main__":
    unittest.main()
