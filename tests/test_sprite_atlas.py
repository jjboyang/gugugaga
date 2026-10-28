"""Regressions for single-character crops and fixed animation anchors."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from pet.animation import AnimationEngine, STATE_CONFIG


class SpriteAtlasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = QPixmap(24, 12)
        source.fill(Qt.transparent)
        painter = QPainter(source)
        # Two adjacent cells deliberately place their subjects differently.
        painter.fillRect(1, 3, 5, 7, QColor("red"))
        painter.fillRect(15, 1, 5, 7, QColor("blue"))
        painter.end()
        self.assertTrue(source.save(str(self.root / "atlas.png")))
        self.manifest = {
            "image": "atlas.png",
            "canvas_size": [24, 24],
            "baseline": 20,
            "scale": 1,
            "frames": [
                {"rect": [0, 0, 12, 12], "anchor": [3.5, 10]},
                {"rect": [12, 0, 12, 12], "anchor": [5.5, 8]},
            ],
            "phases": {phase: [0] for phase in STATE_CONFIG},
        }
        self.manifest["phases"]["idle"] = [0, 1]

    def load(self):
        (self.root / "atlas.json").write_text(json.dumps(self.manifest))
        return AnimationEngine(sprites_dir=str(self.root))

    @staticmethod
    def opaque_pixels(pixmap):
        image = pixmap.toImage()
        return {
            (x, y): image.pixelColor(x, y).name()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 127
        }

    def test_adjacent_subjects_never_share_a_frame(self):
        engine = self.load()
        red, blue = map(self.opaque_pixels, engine.frames["idle"])
        self.assertTrue(red)
        self.assertTrue(blue)
        self.assertEqual(set(red.values()), {"#ff0000"})
        self.assertEqual(set(blue.values()), {"#0000ff"})

    def test_anchors_remove_source_position_changes(self):
        engine = self.load()
        first, second = map(self.opaque_pixels, engine.frames["idle"])
        self.assertEqual(set(first), set(second))
        self.assertEqual(max(y for x, y in first), 19)
        self.assertEqual(engine.frames["idle"][0].toImage().pixelColor(0, 0).alpha(), 0)

    def test_out_of_bounds_crop_is_rejected(self):
        self.manifest["frames"][0]["rect"] = [20, 0, 12, 12]
        with self.assertRaisesRegex(ValueError, "outside"):
            self.load()

    def test_invalid_phase_index_is_rejected(self):
        self.manifest["phases"]["sleep"] = [2]
        with self.assertRaisesRegex(ValueError, "sleep"):
            self.load()

    def test_penguin_directory_frames_still_load(self):
        engine = AnimationEngine()
        self.assertEqual(set(engine.frames), set(STATE_CONFIG))
        self.assertGreater(len(engine.frames["idle"]), 1)
        self.assertTrue(all(not frame.isNull() for frames in engine.frames.values() for frame in frames))

    def test_dafeiyu_frames_have_a_clear_canvas_border(self):
        root = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu"
        engine = AnimationEngine(sprites_dir=str(root))
        self.assertEqual(set(engine.frames), set(STATE_CONFIG))
        for phase, frames in engine.frames.items():
            for pixmap in frames:
                with self.subTest(phase=phase):
                    self.assertEqual((pixmap.width(), pixmap.height()), (256, 256))
                    image = pixmap.toImage()
                    for offset in range(256):
                        for x, y in [(offset, 0), (offset, 255), (0, offset), (255, offset)]:
                            self.assertEqual(image.pixelColor(x, y).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
