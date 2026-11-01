"""Behavioral checks for continuous motion independent of the desktop renderer."""
from dataclasses import asdict
import math
import unittest

from pet.rig_motion import RigMotion


PHASES = (
    "idle", "question", "reading", "thinking", "writing", "executing",
    "done", "sleep", "angry", "dragged", "waddle",
)


def advance(motion, seconds, phase="idle", fps=60, **kwargs):
    pose = None
    for _ in range(round(seconds * fps)):
        pose = motion.step(1 / fps, phase, **kwargs)
    return pose


class RigMotionTests(unittest.TestCase):
    def assert_bounded(self, pose):
        for name, node in pose.nodes.items():
            for value in asdict(node).values():
                self.assertTrue(math.isfinite(value), (name, node))
            self.assertLessEqual(abs(node.dx), 10)
            self.assertLessEqual(abs(node.dy), 10)
            self.assertLessEqual(abs(node.angle), 5 if name == "head" else 16)
            self.assertGreater(node.sx, 0)
            self.assertGreater(node.sy, 0)
            self.assertGreaterEqual(node.opacity, 0)
            self.assertLessEqual(node.opacity, 1)
        for name in ("eye_open", "angry", "mouth_open", "mouth_surprised"):
            self.assertGreaterEqual(getattr(pose, name), 0)
            self.assertLessEqual(getattr(pose, name), 1)
        self.assertLessEqual(abs(pose.gaze_x), 1)
        self.assertLessEqual(abs(pose.gaze_y), 1)

    def test_all_phases_stay_finite_under_repeated_taps_and_drag(self):
        for reduced in (False, True):
            motion = RigMotion(reduced_motion=reduced)
            for phase in PHASES:
                for frame in range(120):
                    if frame % 3 == 0:
                        motion.tap()
                    pose = motion.step(1 / 60, phase, drag_angle=1000, pointer=(99, -99))
                    self.assert_bounded(pose)

    def test_phase_change_preserves_existing_pose_before_time_passes(self):
        motion = RigMotion()
        pose = advance(motion, 0.7, "reading")
        self.assertEqual(pose, motion.step(0, "dragged", drag_angle=26))
        self.assertEqual(pose, motion.step(0, "angry"))

    def test_drag_release_retains_inertia_then_settles(self):
        motion = RigMotion()
        held = advance(motion, 1, "dragged", drag_angle=26)
        release = motion.step(1 / 60, "idle")
        self.assertGreater(held.nodes["root"].angle, 5)
        self.assertGreater(release.nodes["root"].angle, 5)
        self.assertLess(abs(release.nodes["root"].angle - held.nodes["root"].angle), 1)
        rested = advance(motion, 2, "idle")
        self.assertLess(abs(rested.nodes["root"].angle), 0.05)

    def test_sleep_closes_eyes_and_reading_raises_a_book(self):
        motion = RigMotion()
        sleeping = advance(motion, 1, "sleep")
        self.assertLess(sleeping.eye_open, 0.05)
        self.assertLess(sleeping.nodes["book"].opacity, 0.05)
        reading = advance(motion, 1, "reading")
        self.assertGreater(reading.eye_open, 0.8)
        self.assertGreater(reading.nodes["book"].opacity, 0.95)
        awake = advance(motion, 1, "idle")
        self.assertLess(awake.nodes["book"].opacity, 0.05)

    def test_tap_has_a_visible_but_bounded_response(self):
        tapped, control = RigMotion(), RigMotion()
        advance(tapped, 1)
        advance(control, 1)
        tapped.tap()
        after_tap = tapped.step(1 / 60, "idle")
        ordinary = control.step(1 / 60, "idle")
        self.assertGreater(abs(after_tap.nodes["root"].dy - ordinary.nodes["root"].dy), 0.1)
        recovered = advance(tapped, 2)
        baseline = advance(control, 2)
        self.assertAlmostEqual(recovered.nodes["root"].dy, baseline.nodes["root"].dy, delta=0.01)

    def test_refresh_rate_does_not_change_motion_speed(self):
        samples = []
        for fps in (30, 60, 120):
            motion = RigMotion()
            samples.append(advance(motion, 1.8, "reading", fps=fps))
        for sample in samples[1:]:
            self.assertAlmostEqual(sample.nodes["head"].angle, samples[0].nodes["head"].angle, delta=0.12)
            self.assertAlmostEqual(sample.nodes["body"].dy, samples[0].nodes["body"].dy, delta=0.08)
            self.assertAlmostEqual(sample.nodes["book"].opacity, samples[0].nodes["book"].opacity, delta=0.01)

    def test_repeating_a_phase_does_not_restart_its_animation(self):
        motion = RigMotion()
        values = [motion.step(1 / 60, "executing").nodes["arm_left"].angle for _ in range(180)]
        # A continuously advancing action must traverse its cycle, rather than
        # restarting its first instant every time the state is sampled.
        self.assertGreater(max(values[60:]) - min(values[60:]), 2)

    def test_long_pause_and_invalid_numeric_input_are_safe(self):
        motion = RigMotion()
        for delay in (0.4, 10, 100000, float("inf"), float("nan"), -1):
            self.assert_bounded(motion.step(delay, "sleep", drag_angle=float("nan"), pointer=(float("inf"), -3)))

    def test_blinks_close_and_reopen_at_multiple_refresh_rates(self):
        for fps in (30, 60, 120):
            motion = RigMotion(seed=3)
            openness = [motion.step(1 / fps, "idle").eye_open for _ in range(8 * fps)]
            self.assertLess(min(openness), 0.2)
            self.assertGreater(max(openness[-fps:]), 0.95)

    def test_reset_is_deterministic_and_can_start_asleep(self):
        motion = RigMotion(seed=19)
        first = [motion.step(1 / 60, "idle") for _ in range(240)]
        motion.reset()
        second = [motion.step(1 / 60, "idle") for _ in range(240)]
        self.assertEqual(first, second)
        motion.reset("sleep")
        self.assertEqual(motion.step(0, "sleep").eye_open, 0)


if __name__ == "__main__":
    unittest.main()
