"""A four-tap reaction must change the face, not only move the idle artwork."""
from dataclasses import replace
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import pet_app
from pet.ipc import PetIPC
from pet.rig_animator import RigAnimator, RigRenderer
from pet.rig_motion import RigPose
from pet.window import PetWindow


ASSETS = Path(__file__).resolve().parents[1] / "pet" / "characters" / "dafeiyu" / "rig"
EYES = QRect(170, 290, 175, 62)
MOUTH = QRect(238, 341, 42, 33)
LOWER_BODY = QRect(140, 390, 240, 115)


def differing_pixels(first, second, rect):
    return sum(
        first.pixelColor(x, y) != second.pixelColor(x, y)
        for y in range(rect.top(), rect.bottom() + 1)
        for x in range(rect.left(), rect.right() + 1)
    )


class AngryRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.renderer = RigRenderer(ASSETS)

    def test_anger_changes_both_eyes_and_mouth_without_replacing_sitting_body(self):
        idle = self.renderer.render(RigPose()).toImage()
        angry = self.renderer.render(RigPose(angry=1)).toImage()
        self.assertGreater(differing_pixels(idle, angry, EYES), 40,
                           "Angry brows and eyes must actually reach the picture")
        self.assertGreater(differing_pixels(idle, angry, MOUTH), 5,
                           "The idle smile must become the original angry mouth")
        self.assertEqual(idle.copy(LOWER_BODY), angry.copy(LOWER_BODY),
                         "Changing the face must not swap the sitting body for a standing pose")

    def test_anger_does_not_replace_sleep_or_suspended_art(self):
        for special in ({"sleep_blend": 1}, {"drag_blend": 1, "suspension": 1}):
            with self.subTest(special=special):
                expected = self.renderer.render(RigPose(**special)).toImage()
                actual = self.renderer.render(RigPose(angry=1, **special)).toImage()
                self.assertEqual(actual, expected)

    def test_angry_eyes_do_not_turn_into_the_idle_happy_blink(self):
        angry = self.renderer.render(RigPose(angry=1, eye_open=1)).toImage()
        blinking = self.renderer.render(RigPose(angry=1, eye_open=0)).toImage()
        self.assertEqual(angry.copy(EYES), blinking.copy(EYES),
                         "The idle smiling eyelids must not cover the angry brows/eyes")

    def test_releasing_expression_restores_exact_idle_face(self):
        original = self.renderer.render(RigPose()).toImage()
        self.renderer.render(RigPose(angry=1))
        self.assertEqual(self.renderer.render(RigPose()).toImage(), original)


class FourTapAngerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        made = {}

        def create_window(*args, **kwargs):
            made["window"] = PetWindow(*args, **kwargs)
            return made["window"]

        def create_rig(*args, **kwargs):
            made["rig"] = RigAnimator(*args, **kwargs)
            return made["rig"]

        ipc = PetIPC()
        with patch("pet.window._load_config", return_value={}), \
                patch.object(pet_app, "QApplication", return_value=self.app), \
                patch.object(pet_app, "PetWindow", side_effect=create_window), \
                patch.object(pet_app, "RigAnimator", side_effect=create_rig), \
                patch.object(pet_app, "PetIPC", return_value=ipc), \
                patch.object(ipc, "start"), patch.object(ipc, "stop"), \
                patch.object(self.app, "exec", return_value=0), \
                patch.object(pet_app.signal, "signal"):
            with self.assertRaises(SystemExit) as exited:
                pet_app.main()
            self.assertEqual(exited.exception.code, 0)
        self.window = made["window"]
        self.rig = made["rig"]
        self.engine = self.rig.engine
        self.addCleanup(self.cleanup_pet)

    def cleanup_pet(self):
        self.rig.stop()
        for timer in self.engine.findChildren(QTimer):
            timer.stop()
        self.window.close()
        self.window.deleteLater()

    def tap_head(self):
        # Above the belly region, so rapid clicks test anger rather than the
        # independent triple-belly-tap speech bubble.
        local = QPoint(self.window.width() // 2, self.window.height() * 2 // 5)
        point = self.window.mapToGlobal(local)
        for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                              (QEvent.MouseButtonRelease, Qt.NoButton)):
            event = QMouseEvent(kind, QPointF(local), QPointF(point),
                                Qt.LeftButton, buttons, Qt.NoModifier)
            QApplication.sendEvent(self.window, event)

    def four_taps(self):
        for index in range(4):
            self.tap_head()
            if index < 3:
                self.assertEqual(self.engine.current_phase, "idle")
            QTest.qWait(15)
        self.assertEqual(self.engine.current_phase, "angry")

    def test_four_real_clicks_render_angry_face_then_automatically_recover(self):
        poses = []
        original_step = self.rig.motion.step

        def capture_pose(*args, **kwargs):
            pose = original_step(*args, **kwargs)
            poses.append(pose)
            return pose

        with patch.object(self.rig.motion, "step", side_effect=capture_pose):
            self.four_taps()
            QTest.qWait(210)
            self.assertEqual(self.engine.current_phase, "angry")
            self.assertTrue(poses)
            pose = poses[-1]
            self.assertGreater(pose.angry, 0.7)
            # Use exactly the same bone transforms on both pictures. This
            # catches a missing face even if the head itself shakes visibly.
            actual = self.window._last_original_pixmap.toImage()
            faceless = self.rig.renderer.render(replace(pose, angry=0, anger_action=0)).toImage()
            self.assertGreater(differing_pixels(actual, faceless, EYES), 40)
            self.assertGreater(differing_pixels(actual, faceless, MOUTH), 5)
            QTest.qWait(500)
            self.assertEqual(self.engine.current_phase, "angry",
                             "The single-frame fish reaction must remain visible long enough to read")
            QTest.qWait(self.engine.angry_hold_ms + 600)
            self.assertEqual(self.engine.current_phase, "idle")
            self.assertLess(poses[-1].angry, 0.1)
        self.assertFalse(self.engine._waddle_timer.isActive())

    def test_anger_can_be_interrupted_by_picking_up_then_restore_latest_ipc(self):
        self.four_taps()
        self.window._dragging = True
        self.window.drag_started.emit()
        self.assertEqual(self.engine.current_phase, "dragged")
        self.assertEqual(self.rig.motion.step(0, "dragged").drag_blend, 1)
        self.engine.set_state("writing")
        self.assertEqual(self.engine.current_phase, "dragged")
        self.window._dragging = False
        self.window.drag_ended.emit()
        self.assertEqual(self.engine.current_phase, "writing")
        QTest.qWait(40)
        self.assertEqual(self.engine.current_phase, "writing")

    def test_penguin_keeps_original_sprite_rendering_and_recovers_from_anger(self):
        self.window.character_switch_requested.emit()
        self.assertFalse(self.rig.enabled)
        self.four_taps()
        expected = self.engine.frames["angry"][0].scaled(
            self.window._pet_size, self.window._pet_size,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ).toImage()
        self.assertEqual(self.window.label.pixmap().toImage(), expected)
        for _ in range(50):
            if self.engine.current_phase == "idle":
                break
            QTest.qWait(60)
        self.assertEqual(self.engine.current_phase, "idle")
        self.assertFalse(self.rig.enabled)


if __name__ == "__main__":
    unittest.main()
