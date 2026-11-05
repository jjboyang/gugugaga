"""Pomodoro props animate without changing original art or canvas geometry."""
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from pet.pomodoro_renderer import PomodoroRenderer
from pet.rig_animator import RigRenderer
from pet.rig_motion import RigPose


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"


class PomodoroRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.rig = RigRenderer(ASSETS)

    def setUp(self):
        self.renderer = PomodoroRenderer()
        self.original = QPixmap(self.rig.base_pixmap)

    def test_idle_and_unknown_modes_preserve_source_exactly(self):
        before = self.original.toImage()
        for mode in ("idle", "external-hook-phase"):
            result = self.renderer.paint(self.original, mode, 10)
            self.assertEqual(result.toImage(), before)
        self.assertEqual(self.original.toImage(), before)

    def test_every_mode_keeps_dimensions_dpi_and_clear_border(self):
        source = self.original.scaled(768, 768)
        source.setDevicePixelRatio(1.5)
        before = source.toImage()
        for mode in ("focus", "focus_done", "break", "break_done", "activity"):
            with self.subTest(mode=mode):
                result = self.renderer.paint(source, mode, 3.2)
                self.assertEqual(result.size(), source.size())
                self.assertEqual(result.devicePixelRatio(), 1.5)
                image = result.toImage()
                self.assertNotEqual(image, before)
                for index in range(image.width()):
                    for x, y in ((index, 0), (index, image.height() - 1), (0, index), (image.width() - 1, index)):
                        self.assertEqual(image.pixelColor(x, y).alpha(), 0)
        self.assertEqual(source.toImage(), before)

    def test_work_bell_and_coffee_advance_but_pause_holds_still(self):
        for mode, times in (("focus", (1, 1.2)), ("focus_done", (0.1, 0.4)), ("break", (1, 3.6))):
            with self.subTest(mode=mode):
                first = self.renderer.paint(self.original, mode, times[0]).toImage()
                second = self.renderer.paint(self.original, mode, times[1]).toImage()
                self.assertNotEqual(first, second)
                paused_first = self.renderer.paint(self.original, mode, 1, paused=True).toImage()
                paused_later = self.renderer.paint(self.original, mode, 100, paused=True).toImage()
                self.assertEqual(paused_first, paused_later)

    def test_break_alternates_sipping_and_original_arms_up_stretch(self):
        coffee = self.renderer.paint(self.original, "break", 3.5).toImage()
        stretch = self.renderer.paint(self.original, "break", 12).toImage()
        self.assertNotEqual(coffee, stretch)
        self.assertFalse(self.renderer._stretch().isNull())
        self.assertNotEqual(self.renderer._stretch().toImage(), self.original.toImage())

    def test_pose_moves_hands_in_alternation_without_mutating_idle_pose(self):
        idle = RigPose()
        self.renderer.apply_pose(idle, "idle", 1)
        self.assertEqual(idle, RigPose())
        first, second = RigPose(), RigPose()
        self.renderer.apply_pose(first, "focus", 0.1)
        self.renderer.apply_pose(second, "focus", 0.3)
        self.assertNotEqual(first.nodes["arm_left"].dy, second.nodes["arm_left"].dy)
        self.assertAlmostEqual(first.nodes["arm_left"].dy, -first.nodes["arm_right"].dy)
        self.assertEqual(first.nodes["book"].opacity, 0)

    def test_empty_input_is_safe(self):
        self.assertTrue(self.renderer.paint(QPixmap(), "focus", 0).isNull())


if __name__ == "__main__":
    unittest.main()
