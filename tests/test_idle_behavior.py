"""Behavioral regressions for random idle attention gestures."""
from dataclasses import asdict
import math
import unittest

from pet.idle_behavior import IdleBehavior, IdleCue


def until_action(behavior, *, fps=50, limit=20.0):
    for frame in range(round(limit * fps)):
        cue = behavior.step(1 / fps, "idle")
        if cue.action:
            return (frame + 1) / fps, cue
    raise AssertionError("An idle action never started")


class IdleBehaviorTests(unittest.TestCase):
    def test_first_action_requires_eight_to_twelve_quiet_seconds(self):
        for seed in range(10):
            behavior = IdleBehavior(seed=seed)
            delay, cue = until_action(behavior)
            self.assertGreaterEqual(delay, 8.0)
            self.assertLessEqual(delay, 12.02)
            self.assertIn(cue.action, behavior.ACTIONS)
            self.assertGreaterEqual(cue.duration, 4.0)
            self.assertLessEqual(cue.duration, 6.0)
            self.assertEqual(cue.progress, 0.0)
            self.assertFalse(cue.finished)

    def test_finished_action_is_reported_once_and_next_wait_is_longer(self):
        behavior = IdleBehavior(seed=12)
        first = behavior.force_action("hop")
        finished = behavior.step(first.duration, "idle")
        self.assertTrue(finished.finished)
        self.assertEqual(finished.action, "hop")
        self.assertEqual(finished.progress, 1.0)
        self.assertEqual(finished.offset_x, 0.0)
        self.assertEqual(behavior.step(0, "idle"), IdleCue())
        delay, following = until_action(behavior)
        self.assertGreaterEqual(delay, 10.0)
        self.assertLessEqual(delay, 18.02)
        self.assertNotEqual(following.action, "hop")

    def test_random_actions_never_repeat_consecutively(self):
        behavior = IdleBehavior(seed=7)
        actions = []
        for _ in range(30):
            _, cue = until_action(behavior)
            actions.append(cue.action)
            self.assertTrue(behavior.step(cue.duration, "idle").finished)
        self.assertEqual(set(actions), set(behavior.ACTIONS))
        self.assertTrue(all(first != second for first, second in zip(actions, actions[1:])))

    def test_activity_cancels_a_walk_and_restarts_the_quiet_interval(self):
        behavior = IdleBehavior(seed=2)
        behavior.force_action("walk")
        self.assertNotEqual(behavior.step(1, "idle").offset_x, 0)
        behavior.notify_activity()
        self.assertEqual(behavior.step(0, "idle"), IdleCue())
        self.assertEqual(behavior.step(7.9, "idle"), IdleCue())
        _, cue = until_action(behavior)
        self.assertIn(cue.action, behavior.ACTIONS)

    def test_work_sleep_anger_and_drag_cancel_without_issuing_actions(self):
        for phase in ("reading", "writing", "thinking", "executing", "question", "done", "angry", "dragged", "sleep", "waddle"):
            behavior = IdleBehavior(seed=4)
            behavior.force_action("walk")
            behavior.step(1, "idle")
            with self.subTest(phase=phase):
                self.assertEqual(behavior.step(0, phase), IdleCue())
                for _ in range(100):
                    self.assertEqual(behavior.step(1, phase), IdleCue())
                self.assertEqual(behavior.step(7.9, "idle"), IdleCue())

    def test_popup_mouse_hold_and_hidden_blocking_restart_idle_wait(self):
        behavior = IdleBehavior(seed=5)
        behavior.force_action("knock")
        self.assertEqual(behavior.step(0, "idle", blocked=True), IdleCue())
        for _ in range(120):
            self.assertEqual(behavior.step(1 / 30, "idle", blocked=True), IdleCue())
        self.assertEqual(behavior.step(7.9, "idle"), IdleCue())

    def test_disabled_behavior_does_not_run_even_for_forced_previews(self):
        behavior = IdleBehavior(seed=8)
        behavior.force_action("walk")
        behavior.enabled = False
        self.assertEqual(behavior.step(1, "idle"), IdleCue())
        self.assertEqual(behavior.force_action("hop"), IdleCue())
        behavior.enabled = True
        self.assertEqual(behavior.step(7.9, "idle"), IdleCue())

    def test_walk_stays_near_start_and_returns_smoothly_to_both_sides(self):
        behavior = IdleBehavior(seed=6)
        start = behavior.force_action("walk")
        offsets = [start.offset_x]
        finished = None
        for _ in range(math.ceil(start.duration * 120)):
            finished = behavior.step(1 / 120, "idle")
            offsets.append(finished.offset_x)
            if finished.finished:
                break
        self.assertTrue(finished.finished)
        self.assertEqual(offsets[0], 0)
        self.assertEqual(offsets[-1], 0)
        self.assertLessEqual(max(map(abs, offsets)), 80)
        self.assertGreater(max(offsets), 79.9)
        self.assertLess(min(offsets), -79.9)
        self.assertLess(max(abs(b - a) for a, b in zip(offsets, offsets[1:])), 3)
        self.assertLess(abs(offsets[1]), 0.01)
        self.assertLess(abs(offsets[-2]), 0.02)

    def test_in_place_mode_has_no_window_offset(self):
        behavior = IdleBehavior(seed=1, walk_mode="none")
        start = behavior.force_action("walk")
        self.assertEqual(start.offset_x, 0)
        for _ in range(200):
            cue = behavior.step(1 / 50, "idle")
            self.assertEqual(cue.offset_x, 0)

    def test_walk_progress_and_displacement_do_not_depend_on_refresh_rate(self):
        samples = []
        for fps in (30, 60, 120):
            behavior = IdleBehavior(seed=21)
            behavior.force_action("walk")
            for _ in range(round(1.5 * fps)):
                cue = behavior.step(1 / fps, "idle")
            samples.append(cue)
        for sample in samples[1:]:
            self.assertAlmostEqual(sample.elapsed, samples[0].elapsed)
            self.assertAlmostEqual(sample.progress, samples[0].progress)
            self.assertAlmostEqual(sample.offset_x, samples[0].offset_x)

    def test_a_long_application_pause_does_not_replay_old_gestures(self):
        behavior = IdleBehavior(seed=13)
        behavior.force_action("walk")
        behavior.step(1, "idle")
        self.assertEqual(behavior.step(600, "idle"), IdleCue())
        self.assertEqual(behavior.step(7.9, "idle"), IdleCue())
        _, next_cue = until_action(behavior)
        self.assertFalse(next_cue.finished)
        self.assertEqual(next_cue.elapsed, 0)

    def test_invalid_elapsed_time_does_not_corrupt_current_animation(self):
        behavior = IdleBehavior(seed=3)
        behavior.force_action("hop")
        before = behavior.step(0.4, "idle")
        for elapsed in (-1, float("nan"), float("inf")):
            cue = behavior.step(elapsed, "idle")
            self.assertEqual(cue, before)
            self.assertTrue(all(math.isfinite(value) for key, value in asdict(cue).items() if key not in ("action", "finished")))

    def test_cancel_and_invalid_forced_actions_are_explicit(self):
        behavior = IdleBehavior(seed=3)
        behavior.force_action("walk")
        behavior.step(1, "idle")
        self.assertEqual(behavior.cancel(), IdleCue())
        self.assertEqual(behavior.step(0, "idle"), IdleCue())
        with self.assertRaisesRegex(ValueError, "Unknown idle action"):
            behavior.force_action("jump_to_desktop_center")
        with self.assertRaisesRegex(ValueError, "walk_mode"):
            IdleBehavior(walk_mode="unbounded")


if __name__ == "__main__":
    unittest.main()
