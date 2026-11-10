"""Authored Pomodoro poses stay attached, transparent and DPI-correct."""
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

    def render(self, mode, elapsed, scale=1.0):
        pose = RigPose()
        self.renderer.apply_pose(pose, mode, elapsed)
        image = self.rig.render(
            pose, scale=scale, texture=self.renderer.texture(mode, elapsed),
            vertex_deformer=lambda points: self.renderer.deform_vertices(points, mode, elapsed),
        )
        return self.renderer.paint(image, mode, elapsed, artwork_rendered=True)

    def test_work_bell_and_coffee_advance_and_frozen_elapsed_is_repeatable(self):
        for mode, times in (("focus", (1, 1.2)), ("focus_done", (0.1, 0.4)), ("break", (1, 3.6))):
            with self.subTest(mode=mode):
                first = self.render(mode, times[0]).toImage()
                second = self.render(mode, times[1]).toImage()
                self.assertNotEqual(first, second)
                self.assertEqual(first, self.render(mode, times[0]).toImage())

    def test_break_alternates_coffee_and_authored_relaxed_stretch(self):
        coffee = self.renderer.paint(self.original, "break", 3.5).toImage()
        stretch = self.renderer.paint(self.original, "break", 12).toImage()
        self.assertNotEqual(coffee, stretch)
        self.assertFalse(self.renderer._stretch().isNull())
        self.assertNotEqual(self.renderer._stretch().toImage(), self.original.toImage())

    def test_old_asset_pack_falls_back_to_original_laptop_pose(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            for filename in ("atlas.json", "atlas.png"):
                shutil.copy(self.renderer.asset_dir / filename, Path(directory) / filename)
            older_pack = PomodoroRenderer(directory)
            self.assertEqual(older_pack.texture("focus", 1).toImage(), self.rig._frame(5).toImage())

    def test_grip_and_prop_share_deformation_but_distant_head_is_fixed(self):
        from PySide6.QtCore import QPointF
        points = [QPointF(258, 400), QPointF(250, 395), QPointF(256, 200)]
        moved = self.renderer.deform_vertices(points, "break", 4)
        self.assertAlmostEqual(moved[0].y() - points[0].y(), moved[1].y() - points[1].y())
        self.assertLess(moved[0].y(), points[0].y() - 10)
        self.assertEqual(moved[2], points[2])
        self.assertEqual(points[0], QPointF(258, 400))

    def test_stretch_transition_is_continuous_at_both_loop_edges(self):
        for boundary in (10.6, 11.4, 14.8, 16):
            a = self.renderer.texture("break", boundary - 0.00001).toImage()
            b = self.renderer.texture("break", boundary + 0.00001).toImage()
            # Qt's 8-bit opacity can round a near-endpoint blend by one level.
            differences = [abs(x - y) for x, y in zip(bytes(a.bits()), bytes(b.bits()))]
            self.assertLessEqual(max(differences), 2)

    def test_actual_skinned_output_preserves_high_dpi(self):
        for mode in ("focus", "focus_done", "break", "activity"):
            image = self.render(mode, 3.4, scale=1.5)
            self.assertEqual(image.width(), 768)
            self.assertEqual(image.devicePixelRatio(), 1.5)
            self.assertGreater(image.toImage().pixelColor(384, 450).alpha(), 200)
            self.assertEqual(image.toImage().pixelColor(0, 0).alpha(), 0)

    def test_blink_reuses_authored_eyes_and_leaves_grips_and_headband_intact(self):
        for mode in ("focus", "focus_done", "break"):
            awake = self.renderer.texture(mode, 1, eye_open=1).toImage()
            closed = self.renderer.texture(mode, 1, eye_open=0).toImage()
            self.assertNotEqual(awake, closed)
            self.assertEqual(awake.copy(0, 0, 512, 260), closed.copy(0, 0, 512, 260))
            self.assertEqual(awake.copy(0, 370, 512, 142), closed.copy(0, 370, 512, 142))

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
