"""The held body swings below a fixed hand, using the approved pickup asset."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from pet.rig_animator import RigRenderer
from pet.rig_motion import NodePose, RigPose


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"


class PickupRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = RigRenderer(ASSETS)

    @staticmethod
    def pickup_pose(angle=0.0):
        return RigPose(nodes={"root": NodePose(angle=angle)}, drag_blend=1.0, suspension=1.0)

    def test_dedicated_pickup_asset_is_loaded_and_neutral_pose_matches_it(self):
        config = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(config["pickup_image"], "pickup.png")
        self.assertTrue(config["pickup_hand_polygons"])
        source = QPixmap(str(ASSETS / config["pickup_image"]))
        self.assertFalse(source.isNull(), "The configured hanging pose must ship with the project")
        expected = source.scaled(512, 512, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        actual = self.renderer.render(self.pickup_pose())
        self.assertEqual(actual.toImage(), expected.toImage())
        self.assertNotEqual(actual.toImage(), self.renderer.base_pixmap.toImage())

    def test_hand_pixels_stay_fixed_while_the_body_changes_angle(self):
        hand = self.renderer._grip_hand.toImage()
        neutral = self.renderer.render(self.pickup_pose()).toImage()
        opaque_hand_pixels = [
            (x, y) for y in range(hand.height()) for x in range(hand.width())
            if hand.pixelColor(x, y).alpha() >= 245
        ]
        self.assertGreater(len(opaque_hand_pixels), 20, "The visible grip hand must be a separate layer")
        for angle in (-8, 8):
            with self.subTest(angle=angle):
                moved = self.renderer.render(self.pickup_pose(angle)).toImage()
                self.assertNotEqual(moved.copy(0, 90, 512, 400), neutral.copy(0, 90, 512, 400))
                for x, y in opaque_hand_pixels:
                    # The generated source's solid finger pixels have alpha
                    # 245..254, not 255. A fixed translucent finger can reveal
                    # that small fraction of the moving body beneath it.
                    allowance = 255 - hand.pixelColor(x, y).alpha() + 2
                    for a, b in zip(moved.pixelColor(x, y).getRgb(), neutral.pixelColor(x, y).getRgb()):
                        self.assertLessEqual(abs(a - b), allowance, (angle, x, y))

    def test_hidden_root_hides_both_suspended_body_and_grip_hand(self):
        pose = self.pickup_pose(5)
        pose.nodes["root"].opacity = 0
        image = self.renderer.render(pose).toImage()
        self.assertTrue(all(image.pixelColor(x, y).alpha() == 0
                            for y in range(image.height()) for x in range(image.width())))

    def test_pickup_scales_for_high_dpi_and_keeps_clear_edges(self):
        for scale in (1, 1.5, 2):
            for angle in (-8, 0, 8):
                with self.subTest(scale=scale, angle=angle):
                    pixmap = self.renderer.render(self.pickup_pose(angle), scale=scale)
                    self.assertEqual(pixmap.deviceIndependentSize().width(), 512)
                    self.assertEqual(pixmap.deviceIndependentSize().height(), 512)
                    image = pixmap.toImage()
                    width, height = image.width(), image.height()
                    for x in range(width):
                        self.assertEqual(image.pixelColor(x, 0).alpha(), 0)
                        self.assertEqual(image.pixelColor(x, height - 1).alpha(), 0)
                    for y in range(height):
                        self.assertEqual(image.pixelColor(0, y).alpha(), 0)
                        self.assertEqual(image.pixelColor(width - 1, y).alpha(), 0)

    def test_missing_optional_pickup_asset_falls_back_to_original_drag_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            assets = directory / "rig"
            assets.mkdir()
            source_manifest = self.renderer.manifest
            shutil.copyfile(ASSETS.parent / "atlas.json", directory / "atlas.json")
            shutil.copyfile(ASSETS.parent / source_manifest["image"], directory / source_manifest["image"])
            shutil.copyfile(ASSETS / "manifest.json", assets / "manifest.json")
            fallback = RigRenderer(assets)
            index = source_manifest["phases"]["dragged"][0]
            expected = fallback._frame(index)
            self.assertEqual(fallback.render(self.pickup_pose()).toImage(), expected.toImage())
            hand = fallback._grip_hand.toImage()
            self.assertTrue(all(hand.pixelColor(x, y).alpha() == 0
                                for y in range(hand.height()) for x in range(hand.width())))


if __name__ == "__main__":
    unittest.main()
