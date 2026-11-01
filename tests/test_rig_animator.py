"""Offscreen rendering and lifecycle checks using real Qt and project assets."""
import copy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from pet.animation import AnimationEngine, STATE_CONFIG
from pet.rig_animator import RigAnimator, RigRenderer
from pet.rig_motion import RigMotion
from pet.window import PetWindow


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "pet" / "characters" / "dafeiyu" / "rig"


def run_events(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def alpha_sum(image):
    return sum(image.pixelColor(x, y).alpha() for y in range(image.height()) for x in range(image.width()))


class RigRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = RigRenderer(ASSETS)

    def assert_clear_border(self, image):
        width, height = image.width(), image.height()
        for x in range(width):
            self.assertEqual(image.pixelColor(x, 0).alpha(), 0, (x, 0))
            self.assertEqual(image.pixelColor(x, height - 1).alpha(), 0, (x, height - 1))
        for y in range(height):
            self.assertEqual(image.pixelColor(0, y).alpha(), 0, (0, y))
            self.assertEqual(image.pixelColor(width - 1, y).alpha(), 0, (width - 1, y))

    def test_real_assets_render_every_state_without_clipping(self):
        motion = RigMotion()
        for phase in STATE_CONFIG:
            for _ in range(90):
                pose = motion.step(1 / 60, phase, drag_angle=26)
            with self.subTest(phase=phase):
                pixmap = self.renderer.render(pose)
                self.assertFalse(pixmap.isNull())
                self.assertEqual((pixmap.width(), pixmap.height()), (512, 512))
                image = pixmap.toImage()
                self.assertGreater(alpha_sum(image), 100000)
                self.assert_clear_border(image)

    def test_device_pixel_ratio_preserves_logical_canvas(self):
        pose = RigMotion().step(1 / 60, "idle")
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                pixmap = self.renderer.render(pose, scale=scale)
                self.assertEqual(pixmap.devicePixelRatio(), scale)
                self.assertEqual(pixmap.width() / pixmap.devicePixelRatio(), 512)
                self.assertEqual(pixmap.height() / pixmap.devicePixelRatio(), 512)
                self.assert_clear_border(pixmap.toImage())

    def test_both_drag_extremes_keep_the_original_wide_hair_inside_canvas(self):
        for angle in (-26, 26):
            motion = RigMotion()
            for _ in range(120):
                pose = motion.step(1 / 60, "dragged", drag_angle=angle)
            with self.subTest(angle=angle):
                self.assert_clear_border(self.renderer.render(pose).toImage())

    def test_turning_off_root_hides_descendant_layers(self):
        pose = RigMotion().step(0, "idle")
        pose.nodes["root"] = replace(pose.nodes["root"], opacity=0)
        image = self.renderer.render(pose).toImage()
        self.assertEqual(alpha_sum(image), 0)

    def test_rest_pose_uses_the_unchanged_original_artwork_pixels(self):
        source = ASSETS.parent
        manifest = json.loads((source / "atlas.json").read_text(encoding="utf-8"))
        original = source / manifest["image"]
        self.assertEqual(
            hashlib.sha256(original.read_bytes()).hexdigest(),
            "48a37d4f3ea6387afa14f4c4eecabd6c7f012af136957afbefb94b3c3c2da12e",
            "The approved character art must not be silently replaced or repainted",
        )
        atlas = QPixmap(str(original))
        frame = manifest["frames"][manifest["phases"]["idle"][0]]
        expected = QPixmap(512, 512)
        expected.fill(Qt.transparent)
        painter = QPainter(expected)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.scale(2, 2)
        painter.translate(manifest["canvas_size"][0] / 2, manifest["baseline"])
        painter.scale(manifest["scale"], manifest["scale"])
        painter.drawPixmap(QPointF(-frame["anchor"][0], -frame["anchor"][1]), atlas.copy(QRect(*frame["rect"])))
        painter.end()
        actual = self.renderer.render(RigMotion().step(0, "idle"))
        self.assertEqual(actual.toImage(), expected.toImage())

    def test_mesh_uses_normalized_weights_and_shared_triangle_vertices(self):
        vertices = self.renderer.vertices
        weights = self.renderer.weights
        triangles = self.renderer.triangles
        self.assertGreater(len(vertices), 100)
        self.assertEqual(len(vertices), len(weights))
        influenced_bones = set()
        for point, influences in zip(vertices, weights):
            self.assertTrue(math.isfinite(point.x()) and math.isfinite(point.y()))
            self.assertTrue(all(math.isfinite(w) and w >= 0 for w in influences.values()))
            self.assertAlmostEqual(sum(influences.values()), 1)
            influenced_bones.update(bone for bone, weight in influences.items() if weight > 0.2)
        self.assertGreater(len(influenced_bones), 3)
        edges = {}
        used = set()
        for triangle in triangles:
            self.assertEqual(len(set(triangle)), 3)
            used.update(triangle)
            for index in triangle:
                self.assertGreaterEqual(index, 0)
                self.assertLess(index, len(vertices))
            for first, second in zip(triangle, triangle[1:] + triangle[:1]):
                key = tuple(sorted((first, second)))
                edges[key] = edges.get(key, 0) + 1
        self.assertEqual(len(used), len(vertices))
        self.assertTrue(all(count in (1, 2) for count in edges.values()))
        self.assertGreater(sum(count == 2 for count in edges.values()), len(edges) / 2)

    def test_animated_mesh_triangles_do_not_fold_over(self):
        motion = RigMotion()
        for phase in STATE_CONFIG:
            for sample in range(10):
                pose = motion.step(0.12, phase, drag_angle=26 if sample % 2 else -26)
                vertices = self.renderer.deformed_vertices(pose)
                self.assertEqual(len(vertices), len(self.renderer.vertices))
                for triangle in self.renderer.triangles:
                    a, b, c = (vertices[index] for index in triangle)
                    area = (b.x() - a.x()) * (c.y() - a.y()) - (b.y() - a.y()) * (c.x() - a.x())
                    self.assertGreater(area, 0, (phase, sample, triangle))

    def test_changing_one_bone_changes_the_render_without_changing_other_bones(self):
        pose = RigMotion().step(0, "idle")
        changed = copy.deepcopy(pose)
        changed.nodes["arm_left"].angle = 12
        image = self.renderer.render(pose).toImage()
        moved = self.renderer.render(changed).toImage()
        self.assertNotEqual(image, moved)
        self.assertEqual(pose.nodes["head"], changed.nodes["head"])
        self.assertEqual(pose.nodes["arm_right"], changed.nodes["arm_right"])
        self.assertEqual(image.copy(0, 0, 512, 100), moved.copy(0, 0, 512, 100))

    def test_child_features_follow_head_but_legs_keep_their_own_joint(self):
        pose = RigMotion().step(0, "idle")
        original = self.renderer.transforms(pose)
        pose.nodes["head"].dx = 10
        moved = self.renderer.transforms(pose)
        for child in ("eyes", "mouth", "headdress", "hair_left", "hair_right"):
            first = original[child][0].map(QPointF())
            second = moved[child][0].map(QPointF())
            self.assertAlmostEqual(second.x() - first.x(), 10)
            self.assertAlmostEqual(second.y(), first.y())
        self.assertEqual(original["leg_left"], moved["leg_left"])
        self.assertEqual(original["arm_right"], moved["arm_right"])

    def assert_invalid_manifest(self, mutate, message):
        manifest = copy.deepcopy(self.renderer.manifest)
        mutate(manifest)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            assets = directory / "rig"
            assets.mkdir()
            shutil.copyfile(ASSETS.parent / self.renderer.manifest["image"], directory / self.renderer.manifest["image"])
            (directory / "atlas.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                RigRenderer(assets)

    def test_out_of_bounds_crop_is_rejected_before_rendering(self):
        self.assert_invalid_manifest(
            lambda manifest: manifest["frames"][0].__setitem__("rect", [100000, 0, 50, 50]), "outside"
        )

    def test_missing_image_is_reported_clearly(self):
        self.assert_invalid_manifest(lambda manifest: manifest.__setitem__("image", "missing.png"), "image|atlas")

    def test_invalid_render_scale_is_rejected(self):
        pose = RigMotion().step(0, "idle")
        for scale in (0, -1, float("nan"), float("inf"), 5):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "scale"):
                self.renderer.render(pose, scale=scale)


class RigAnimatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.environment = patch.dict(os.environ, {"DESKTOP_PET_SLEEP_WADDLE_MS": "0"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.engine = AnimationEngine()
        self.engine.set_state("idle")
        with patch("pet.window._load_config", return_value={}):
            self.window = PetWindow()
        self.animator = RigAnimator(self.engine, self.window, ASSETS)
        self.frames = []
        self.animator.frame_changed.connect(self.frames.append)
        self.addCleanup(self.animator.stop)
        self.addCleanup(self.window.close)

    def test_enable_emits_immediately_and_disable_stops_rendering(self):
        self.assertFalse(self.animator.enabled)
        self.assertFalse(self.animator.timer.isActive())
        self.animator.set_enabled(True)
        self.assertTrue(self.animator.enabled)
        self.assertTrue(self.animator.timer.isActive())
        self.assertEqual(len(self.frames), 1)
        run_events(70)
        self.assertGreater(len(self.frames), 1)
        self.animator.set_enabled(False)
        previous = len(self.frames)
        self.assertFalse(self.animator.timer.isActive())
        run_events(45)
        self.assertEqual(len(self.frames), previous)

    def test_repeated_switching_and_stop_leave_no_active_render_timer(self):
        for _ in range(6):
            self.animator.set_enabled(True)
            self.animator.set_enabled(False)
        self.assertEqual(len(self.frames), 6)
        self.animator.set_enabled(True)
        self.animator.stop()
        self.assertFalse(self.animator.enabled)
        self.assertFalse(self.animator.timer.isActive())

    def test_sleep_tap_and_dragged_ipc_preserve_engine_semantics(self):
        self.engine.set_state("sleep")
        self.assertFalse(self.engine._waddle_timer.isActive())
        self.engine.notify_pet_tap()
        self.animator.notify_tap()
        self.assertEqual(self.engine.current_phase, "idle")
        self.engine.begin_drag()
        self.assertEqual(self.engine.current_phase, "dragged")
        self.engine.set_state("writing")
        self.assertEqual(self.engine.current_phase, "dragged")
        self.engine.end_drag()
        self.assertEqual(self.engine.current_phase, "writing")

    def test_rendering_and_sleep_never_change_window_position(self):
        start = self.window.pos()
        self.animator.set_enabled(True)
        for phase in ("sleep", "reading", "angry", "idle"):
            self.engine.set_state(phase)
            run_events(35)
            self.assertEqual(self.window.pos(), start)
        self.assertFalse(self.engine._waddle_timer.isActive())

    def test_high_dpi_frame_keeps_requested_window_size_before_and_after_resize(self):
        pose = RigMotion().step(0, "idle")
        pixmap = self.animator.renderer.render(pose, scale=2)
        self.window.set_pixmap(pixmap)
        displayed = self.window.label.pixmap()
        self.assertEqual(displayed.deviceIndependentSize().width(), self.window._pet_size)
        self.assertEqual(displayed.deviceIndependentSize().height(), self.window._pet_size)
        with patch("pet.window._save_config"):
            self.window._on_size_changed(220)
        displayed = self.window.label.pixmap()
        self.assertEqual(displayed.deviceIndependentSize().width(), 220)
        self.assertEqual(displayed.deviceIndependentSize().height(), 220)


if __name__ == "__main__":
    unittest.main()
