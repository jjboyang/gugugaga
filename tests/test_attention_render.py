"""Attention actions must change visible artwork and move the knocking hand."""
from dataclasses import replace
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.rig_animator import RigRenderer
from pet.idle_behavior import IdleBehavior
from pet.rig_motion import RigMotion, RigPose


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"


class AttentionRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = RigRenderer(ASSETS)

    def test_gesture_artwork_is_visible_without_replacing_normal_idle(self):
        renderer = self.renderer
        self.assertEqual(renderer.render(RigPose()).toImage(), renderer.base_pixmap.toImage())
        for action in ("walk", "knock", "hop"):
            pose = RigPose(idle_action=action, action_elapsed=1)
            setattr(pose, action + "_blend", 1)
            with self.subTest(action=action):
                self.assertNotEqual(renderer.render(pose).toImage(), renderer.base_pixmap.toImage())

    def test_knock_contact_moves_the_fist_but_not_the_head_or_legs(self):
        resting = RigPose(idle_action="knock", knock_blend=1)
        tapping = replace(resting, knock_impact=1)
        first = self.renderer.deformed_vertices(resting)
        second = self.renderer.deformed_vertices(tapping)
        shifted = [(i, a, b) for i, (a, b) in enumerate(zip(first, second)) if a != b]
        self.assertTrue(shifted)
        self.assertLess(min(b.y() - a.y() for _, a, b in shifted), -3)
        for i, a, b in shifted:
            source = self.renderer.vertices[i]
            self.assertLess(abs(source.x() - 312), 30)
            self.assertLess(abs(source.y() - 309), 34)
        for triangle in self.renderer.triangles:
            a, b, c = (second[i] for i in triangle)
            area = (b.x() - a.x()) * (c.y() - a.y()) - (b.y() - a.y()) * (c.x() - a.x())
            self.assertGreater(area, 0)

    def test_work_and_sleep_override_stale_attention_channels(self):
        normal = self.renderer.render(RigPose()).toImage()
        working = RigPose(phase="reading", idle_action="knock", knock_blend=1, knock_impact=1)
        self.assertEqual(self.renderer.render(working).toImage(), normal)
        sleeping = replace(working, phase="sleep", sleep_blend=1)
        self.assertEqual(self.renderer.render(sleeping).toImage(), self.renderer._sleeping.toImage())

    def test_full_anger_action_uses_the_original_standing_gesture(self):
        pose = RigPose(phase="angry", angry=1, anger_action=1)
        expected = self.renderer._frame(self.renderer.manifest["phases"]["angry"][0])
        self.assertEqual(self.renderer.render(pose).toImage(), expected.toImage())

    def test_all_attention_actions_keep_a_clear_canvas_border(self):
        for action in ("walk", "knock", "hop"):
            motion = RigMotion()
            for frame in range(145):
                pose = motion.step(1 / 30, "idle", idle_action=action,
                                   action_elapsed=frame / 30, action_duration=4.8)
                if frame % 8:
                    continue
                image = self.renderer.render(pose).toImage()
                with self.subTest(action=action, frame=frame):
                    for value in range(512):
                        for x, y in ((value, 0), (value, 511), (0, value), (511, value)):
                            self.assertEqual(image.pixelColor(x, y).alpha(), 0)

    def test_walk_turn_keeps_head_width_and_pins_both_shoes(self):
        renderer = self.renderer
        behavior = IdleBehavior(seed=6)
        behavior.force_action("walk")
        motion = RigMotion(seed=6)

        def vertex_index(x, y):
            return next(index for index, point in enumerate(renderer.vertices) if (point.x(), point.y()) == (x, y))

        left_shoe, right_shoe = vertex_index(224, 480), vertex_index(288, 480)
        left_head, right_head = vertex_index(96, 256), vertex_index(416, 256)
        heads = []
        for _ in range(600):
            cue = behavior.step(1 / 120, "idle")
            if not cue.walk_turn:
                if heads:
                    break
                continue
            pose = motion.step(1 / 120, "idle", idle_action="walk", action_elapsed=cue.elapsed,
                               action_duration=cue.duration, walk_cue=cue)
            vertices = renderer.deformed_vertices(pose)
            self.assertAlmostEqual(vertices[left_shoe].y(), 480, delta=0.01)
            self.assertAlmostEqual(vertices[right_shoe].y(), 480, delta=0.01)
            self.assertAlmostEqual(vertices[left_shoe].x(), 224, delta=0.01)
            self.assertAlmostEqual(vertices[right_shoe].x(), 288, delta=0.01)
            self.assertAlmostEqual(vertices[right_head].x() - vertices[left_head].x(), 320, delta=5)
            heads.append(pose.walk_heading)
        self.assertGreater(len(heads), 30)
        self.assertLess(heads[0] * heads[-1], 0)
        self.assertLess(max(abs(a - b) for a, b in zip(heads, heads[1:])), 0.08)

    def test_rising_preserves_the_original_head_and_standing_lower_body(self):
        renderer = self.renderer
        base = renderer.base_pixmap.toImage()
        standing = renderer.attention.angry_frame.toImage()
        for weight in (0.0, 0.5, 1.0):
            pose = RigPose(idle_action="walk", walk_blend=weight)
            texture = renderer._awake_texture(pose).toImage()
            rise = round(renderer._WALK_RISE * weight)
            # Includes the hair tuft, headdress, eyes, mouth and chin.
            self.assertEqual(texture.copy(0, 0, 512, 374 - rise), base.copy(0, rise, 512, 374 - rise))
        self.assertEqual(texture.copy(0, 360, 512, 152), standing.copy(0, 360, 512, 152))


if __name__ == "__main__":
    unittest.main()
