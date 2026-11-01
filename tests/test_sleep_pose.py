"""Use the original sleep/drag drawings, rather than a smiling idle blink."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from pet.rig_animator import RigRenderer
from pet.rig_motion import NodePose, RigPose


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"


class OriginalStatePoseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = RigRenderer(ASSETS)

    def original_frame(self, phase):
        # Rebuild independently of the renderer's cached special textures.
        manifest = json.loads((ASSETS.parent / "atlas.json").read_text(encoding="utf-8"))
        frame = manifest["frames"][manifest["phases"][phase][0]]
        atlas = QPixmap(str(ASSETS.parent / manifest["image"]))
        expected = QPixmap(512, 512)
        expected.fill(Qt.transparent)
        painter = QPainter(expected)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.scale(2, 2)
        painter.translate(manifest["canvas_size"][0] / 2, manifest["baseline"])
        painter.scale(manifest["scale"], manifest["scale"])
        painter.drawPixmap(
            QPointF(-frame["anchor"][0], -frame["anchor"][1]),
            atlas.copy(QRect(*frame["rect"])),
        )
        painter.end()
        return expected.toImage()

    @staticmethod
    def pose(*, sleeping=0.0, dragged=0.0, eye_open=1.0, book=0.0):
        pose = RigPose(nodes={"book": NodePose(opacity=book)}, eye_open=eye_open)
        # Dynamic assignment also lets this regression run while the motion
        # module's explicit blend channels are being introduced independently.
        pose.sleep_blend = sleeping
        pose.drag_blend = dragged
        return pose

    def test_sleep_is_the_exact_original_sleep_drawing(self):
        pose = self.pose(sleeping=1)
        self.assertEqual(self.renderer.render(pose).toImage(), self.original_frame("sleep"))

    def test_sleep_is_not_the_idle_happy_closed_eye_blink(self):
        sleeping = self.renderer.render(self.pose(sleeping=1, eye_open=0)).toImage()
        blink = self.renderer.render(self.pose(eye_open=0)).toImage()
        self.assertNotEqual(sleeping, blink)
        self.assertNotEqual(sleeping.copy(150, 260, 210, 120), blink.copy(150, 260, 210, 120))

    def test_sleep_does_not_inherit_a_book_or_idle_eye_overlay(self):
        actual = self.renderer.render(self.pose(sleeping=1, eye_open=0, book=1)).toImage()
        self.assertEqual(actual, self.original_frame("sleep"))

    def test_drag_is_the_exact_original_suspended_drawing(self):
        actual = self.renderer.render(self.pose(dragged=1)).toImage()
        self.assertEqual(actual, self.original_frame("dragged"))
        self.assertNotEqual(actual, self.original_frame("idle"))

    def test_held_pose_has_priority_when_waking_from_sleep(self):
        actual = self.renderer.render(self.pose(sleeping=1, dragged=1, eye_open=0, book=1)).toImage()
        self.assertEqual(actual, self.original_frame("dragged"))

    def test_return_to_idle_restores_the_unchanged_original_art(self):
        self.renderer.render(self.pose(sleeping=1))
        self.renderer.render(self.pose(dragged=1))
        self.assertEqual(self.renderer.render(self.pose()).toImage(), self.original_frame("idle"))

    def test_partial_transition_uses_both_original_poses(self):
        normal = self.renderer._texture_for_pose(self.pose()).toImage()
        sleeping = self.renderer._texture_for_pose(self.pose(sleeping=1)).toImage()
        middle = self.renderer._texture_for_pose(self.pose(sleeping=0.5)).toImage()
        self.assertNotEqual(middle, normal)
        self.assertNotEqual(middle, sleeping)
        # A white opaque corner was never present in either source frame.
        self.assertEqual(middle.pixelColor(0, 0).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
