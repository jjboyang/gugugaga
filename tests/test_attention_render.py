"""Attention actions must change visible artwork and move the knocking hand."""
from dataclasses import replace
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.rig_animator import RigRenderer
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


if __name__ == "__main__":
    unittest.main()
