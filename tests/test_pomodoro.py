"""Real focus, lifecycle recovery, and local calendar accounting regressions."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pet.pomodoro import PomodoroTimer


class Clock:
    def __init__(self, wall=datetime(2026, 11, 5, 9)):
        self.wall = wall
        self.mono = 100.0

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


class PomodoroTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nested" / "pomodoro.json"
        self.clock = Clock()
        self.timer = self.new_timer()

    def new_timer(self):
        return PomodoroTimer(self.path, now=self.clock.now, monotonic=self.clock.monotonic)

    def advance(self, seconds):
        self.clock.advance(seconds)
        return self.timer.tick()

    def complete_focus(self):
        self.timer.start_focus()
        return self.advance(1500)

    def test_idle_does_not_create_files_and_full_phases_emit_once(self):
        self.advance(30)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.timer.phase, "idle")
        self.assertEqual(self.complete_focus(), ["focus_done"])
        self.assertEqual(self.timer.phase, "focus_done")
        self.assertEqual(self.timer.remaining_seconds, 0)
        self.assertEqual(self.advance(3600), [])
        self.assertEqual(self.timer.stats()["today_pomodoros"], 1)
        self.timer.start_break()
        self.assertEqual(self.advance(300), ["break_done"])
        self.assertEqual(self.timer.phase, "break_done")
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 1500)
        self.assertEqual(self.advance(600), [])

    def test_pause_resume_and_double_start_do_not_lose_or_duplicate_focus(self):
        self.timer.start_focus()
        self.advance(120)
        self.timer.start_focus()
        self.assertEqual(self.timer.remaining_seconds, 1380)
        self.clock.advance(10)
        self.timer.pause()
        self.assertTrue(self.timer.paused)
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 130)
        self.advance(600)
        self.assertEqual(self.timer.remaining_seconds, 1370)
        self.timer.resume()
        self.advance(1370)
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 1500)
        self.assertEqual(self.timer.stats()["today_pomodoros"], 1)

    def test_reset_keeps_partial_work_without_a_completed_tomato(self):
        self.timer.start_focus()
        self.clock.advance(63.5)
        self.timer.reset()
        self.assertEqual(self.timer.phase, "idle")
        self.assertEqual(self.timer.remaining_seconds, 1500)
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 63.5)
        self.assertEqual(self.timer.stats()["today_pomodoros"], 0)
        restored = self.new_timer()
        self.assertEqual(restored.stats()["today_focus_seconds"], 63.5)

    def test_clock_adjustment_does_not_change_countdown(self):
        self.timer.start_focus()
        self.clock.wall += timedelta(hours=1)
        self.clock.mono += 12
        self.timer.tick()
        self.assertEqual(self.timer.remaining_seconds, 1488)
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 12)
        self.clock.wall -= timedelta(hours=2)
        self.clock.mono += 3
        self.timer.tick()
        self.assertEqual(self.timer.remaining_seconds, 1485)

    def test_delayed_tick_finishes_only_current_session_and_caps_work(self):
        self.timer.start_focus()
        self.assertEqual(self.advance(12 * 3600), ["focus_done"])
        self.assertEqual(self.timer.stats()["today_focus_seconds"], 1500)
        self.assertEqual(self.timer.stats()["today_pomodoros"], 1)
        self.assertEqual(self.timer.phase, "focus_done")

    def test_midnight_splits_partial_focus_and_completion_belongs_to_finish_day(self):
        self.clock.wall = datetime(2026, 11, 8, 23, 50)  # Sunday
        self.timer.start_focus()
        self.advance(1500)
        stats = self.timer.stats()
        self.assertEqual(stats["today_focus_seconds"], 900)
        self.assertEqual(stats["today_pomodoros"], 1)
        self.assertEqual(stats["week_focus_seconds"], 900)
        self.assertEqual(stats["week_days"][0]["date"], "2026-11-09")
        self.assertEqual(stats["week_days"][-1]["date"], "2026-11-15")
        self.clock.wall = datetime(2026, 11, 8, 23, 59)
        previous = self.timer.stats()
        self.assertEqual(previous["today_focus_seconds"], 600)
        self.assertEqual(previous["today_pomodoros"], 0)
        self.assertEqual(previous["week_focus_seconds"], 600)

    def test_streak_allows_today_pending_but_requires_completed_tomatoes(self):
        self.clock.wall = datetime(2026, 11, 7, 9)
        self.complete_focus()
        self.clock.wall = datetime(2026, 11, 8, 9)
        self.complete_focus()
        self.clock.wall = datetime(2026, 11, 9, 9)
        self.timer.start_focus()
        self.advance(5)
        self.assertEqual(self.timer.stats()["streak_days"], 2)
        self.advance(1495)
        self.assertEqual(self.timer.stats()["streak_days"], 3)
        self.clock.wall = datetime(2026, 11, 11, 9)
        self.assertEqual(self.timer.stats()["streak_days"], 0)

    def test_activity_reminder_counts_only_focus_once_until_acknowledged(self):
        for _ in range(4):
            self.assertEqual(self.complete_focus(), ["focus_done"])
            self.timer.start_break()
            self.advance(300)
        self.assertEqual(self.timer.focus_since_activity, 6000)
        self.timer.start_focus()
        self.advance(1199)
        self.timer.pause()
        self.advance(900)
        self.timer.resume()
        self.assertEqual(self.advance(1), ["activity_due"])
        self.assertEqual(self.advance(1), [])
        self.advance(299)
        self.complete_focus()
        self.assertTrue(self.timer.activity_reminded)
        self.timer.mark_activity()
        self.assertEqual(self.timer.focus_since_activity, 0)
        self.assertFalse(self.timer.activity_reminded)
        self.complete_focus()
        self.assertEqual(self.timer.focus_since_activity, 1500)

    def test_shutdown_pauses_and_recovery_excludes_offline_time(self):
        self.timer.start_focus()
        self.clock.advance(123)
        self.timer.shutdown()
        self.clock.advance(20 * 3600)
        restored = self.new_timer()
        self.assertEqual(restored.phase, "focus")
        self.assertTrue(restored.paused)
        self.assertEqual(restored.remaining_seconds, 1377)
        self.assertEqual(restored.stats()["week_focus_seconds"], 123)
        restored.tick()
        self.assertEqual(restored.remaining_seconds, 1377)
        restored.resume()
        self.clock.advance(10)
        restored.tick()
        self.assertEqual(restored.remaining_seconds, 1367)

    def test_crash_recovers_only_checkpoint_and_pauses_running_breaks(self):
        self.timer.start_focus()
        self.advance(5)
        self.clock.advance(2)  # unobserved, unsaved time
        restored = self.new_timer()
        self.assertTrue(restored.paused)
        self.assertEqual(restored.remaining_seconds, 1495)
        self.assertEqual(restored.stats()["today_focus_seconds"], 5)
        restored.start_break()
        self.clock.advance(50)
        restored.tick()
        recovered_break = self.new_timer()
        self.assertEqual(recovered_break.phase, "break")
        self.assertTrue(recovered_break.paused)
        self.assertEqual(recovered_break.remaining_seconds, 250)

    def test_corrupt_and_wrong_shape_records_are_reported_and_preserved(self):
        self.path.parent.mkdir()
        samples = ["{broken", "[]", "null", '{"version": 1, "phase": []}',
                   '{"version": 99}']
        self.timer.start_focus()
        valid = json.loads(self.path.read_text())
        valid["days"] = []
        samples.append(json.dumps(valid))
        valid["days"] = {"2026-11-05": {"focus_seconds": float("nan"), "pomodoros": 0}}
        samples.append(json.dumps(valid))
        for payload in samples:
            with self.subTest(payload=payload):
                self.path.write_text(payload)
                restored = self.new_timer()
                self.assertIsNotNone(restored.storage_error)
                restored.start_focus()
                self.clock.advance(10)
                restored.tick()
                self.assertEqual(restored.stats()["today_focus_seconds"], 10)
                self.assertEqual(self.path.read_text(), payload)

    def test_failed_atomic_replace_preserves_old_record_and_live_memory(self):
        self.timer.start_focus()
        before = self.path.read_text()
        with patch("pet.pomodoro.os.replace", side_effect=OSError("disk unavailable")):
            self.advance(5)
            self.assertIsNotNone(self.timer.storage_error)
            self.assertEqual(self.timer.stats()["today_focus_seconds"], 5)
            self.assertEqual(self.path.read_text(), before)
            self.assertFalse(list(self.path.parent.glob("*.tmp")))
        self.assertTrue(self.timer.save())
        self.assertIsNone(self.timer.storage_error)
        self.assertEqual(self.new_timer().stats()["today_focus_seconds"], 5)


if __name__ == "__main__":
    unittest.main()
