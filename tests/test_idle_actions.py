"""Continuous attention gestures must read as distinct complete motions."""
from dataclasses import asdict
import math
import unittest

from pet.rig_motion import RigMotion


def action_frames(action, *, duration=4.8, fps=120, reduced=False):
    motion = RigMotion(reduced_motion=reduced)
    frames = []
    for index in range(round(duration * fps) + 1):
        frames.append(motion.step(
            0.0 if index == 0 else 1 / fps, "idle", idle_action=action,
            action_elapsed=index / fps, action_duration=duration,
        ))
    return motion, frames


def runs_above(values, threshold):
    runs = []
    for index, value in enumerate(values):
        if value > threshold:
            if not runs or index > runs[-1][-1] + 1:
                runs.append([index])
            else:
                runs[-1].append(index)
    return runs


class IdleActionMotionTests(unittest.TestCase):
    def test_walking_alternates_weight_and_lifts_both_feet(self):
        _, poses = action_frames("walk")
        left = [-pose.nodes["leg_left"].dy for pose in poses]
        right = [-pose.nodes["leg_right"].dy for pose in poses]
        self.assertGreater(max(left), 3)
        self.assertGreater(max(right), 3)
        # Both feet move over time, rather than translating the entire actor
        # with a static pair of legs or always lifting them in unison.
        dominance = [a - b for a, b in zip(left, right)]
        self.assertGreater(max(dominance), 2)
        self.assertLess(min(dominance), -2)
        self.assertGreater(len(runs_above(dominance, 1.5)), 4)
        self.assertGreater(max(pose.walk_blend for pose in poses), 0.98)

    def test_knocking_has_three_separate_forward_contacts(self):
        _, poses = action_frames("knock")
        pulses = [pose.knock_impact for pose in poses]
        groups = runs_above(pulses, 0.40)
        self.assertEqual(len(groups), 3)
        self.assertTrue(all(len(group) > 3 for group in groups))
        hand = [pose.nodes["arm_right"].dy for pose in poses]
        self.assertLess(min(hand), -3)
        self.assertGreater(max(hand) - min(hand), 3)
        self.assertGreater(max(pose.knock_blend for pose in poses), 0.98)

    def test_three_hops_crouch_leave_ground_and_land(self):
        _, poses = action_frames("hop")
        heights = [-pose.nodes["root"].dy for pose in poses]
        flights = runs_above(heights, 8)
        self.assertEqual(len(flights), 3)
        self.assertTrue(all(max(heights[index] for index in flight) > 14 for flight in flights))
        body_scale = [pose.nodes["body"].sy for pose in poses]
        self.assertLess(min(body_scale), 0.985)
        self.assertGreater(max(body_scale), 1.005)
        self.assertGreater(max(pose.hop_blend for pose in poses), 0.98)

    def test_work_sleep_and_drag_immediately_suppress_idle_gestures(self):
        for phase in ("reading", "writing", "thinking", "executing", "question", "done", "angry", "dragged", "sleep"):
            motion = RigMotion()
            for index in range(90):
                motion.step(1 / 60, "idle", idle_action="knock", action_elapsed=index / 60, action_duration=5)
            with self.subTest(phase=phase):
                pose = motion.step(0, phase, idle_action="knock", action_elapsed=1.5, action_duration=5)
                self.assertEqual(pose.phase, phase)
                self.assertEqual(pose.idle_action, "")
                self.assertEqual((pose.walk_blend, pose.knock_blend, pose.hop_blend, pose.knock_impact), (0, 0, 0, 0))

    def test_click_cancellation_clears_attention_layers_at_once(self):
        motion = RigMotion()
        for index in range(100):
            motion.step(1 / 60, "idle", idle_action="hop", action_elapsed=index / 60, action_duration=5)
        motion.cancel_idle_actions()
        pose = motion.step(0, "idle")
        self.assertEqual((pose.walk_blend, pose.knock_blend, pose.hop_blend, pose.knock_impact), (0, 0, 0, 0))

    def test_anger_has_alternating_foot_stamps_and_visible_head_motion(self):
        motion = RigMotion()
        poses = [motion.step(1 / 120, "angry") for _ in range(420)]
        left = [pose.nodes["leg_left"].dy for pose in poses]
        right = [pose.nodes["leg_right"].dy for pose in poses]
        self.assertLess(min(left), -2)
        self.assertLess(min(right), -2)
        self.assertGreater(max(a - b for a, b in zip(left, right)), 2)
        self.assertLess(min(a - b for a, b in zip(left, right)), -2)
        head = [pose.nodes["head"].angle for pose in poses]
        self.assertGreater(max(head) - min(head), 1)
        self.assertGreater(poses[-1].anger_action, 0.99)

    def test_new_gestures_stay_finite_and_do_not_accumulate_motion(self):
        for action in ("walk", "knock", "hop"):
            motion, poses = action_frames(action)
            for pose in poses:
                for name, node in pose.nodes.items():
                    self.assertTrue(all(math.isfinite(value) for value in asdict(node).values()))
                    self.assertGreater(node.sx, 0)
                    self.assertGreater(node.sy, 0)
                    self.assertLessEqual(abs(node.dx), 10)
                    self.assertGreaterEqual(node.dy, -24 if name == "root" else -10)
                    self.assertLessEqual(node.dy, 10)
            for _ in range(180):
                rested = motion.step(1 / 60, "idle")
            self.assertLess(abs(rested.nodes["root"].dy), 1)
            self.assertLess(max(rested.walk_blend, rested.knock_blend, rested.hop_blend), 0.01)

    def test_hop_timing_is_consistent_across_refresh_rates(self):
        samples = []
        for fps in (30, 60, 120):
            motion = RigMotion()
            for index in range(round(1.3 * fps) + 1):
                pose = motion.step(1 / fps, "idle", idle_action="hop", action_elapsed=index / fps, action_duration=4.8)
            samples.append(pose)
        for sample in samples[1:]:
            self.assertAlmostEqual(sample.nodes["root"].dy, samples[0].nodes["root"].dy, delta=0.8)
            self.assertAlmostEqual(sample.nodes["body"].sy, samples[0].nodes["body"].sy, delta=0.01)


if __name__ == "__main__":
    unittest.main()
