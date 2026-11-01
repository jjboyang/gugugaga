"""Real mouse-event regressions for visible DaFeiYu drag feedback.

Use main()'s actual signal wiring: a phase-only test misses a pet that moves
with the pointer while its displayed picture is still the idle picture.
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import pet_app
from pet.ipc import PetIPC
from pet.rig_animator import RigAnimator
from pet.window import PetWindow


def image_error(first, second):
    """Difference in visible rendered pixels, rather than internal pose values."""
    if first.size() != second.size():
        raise AssertionError("Reference pictures must have the same size")
    difference = 0
    for y in range(first.height()):
        for x in range(first.width()):
            a, b = first.pixelColor(x, y), second.pixelColor(x, y)
            # Compare against the same light background so transparent RGB
            # residues do not dominate the character's actual appearance.
            for ca, cb in zip(a.getRgb()[:3], b.getRgb()[:3]):
                first_visible = ca * a.alpha() + 240 * (255 - a.alpha())
                second_visible = cb * b.alpha() + 240 * (255 - b.alpha())
                difference += abs(first_visible - second_visible)
    return difference


class DragFeedbackTests(unittest.TestCase):
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
        # main() performs all production connections. Only startup side effects
        # and the blocking application loop are replaced for this test.
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
        self.ipc = ipc
        self.start = self.window.mapToGlobal(self.window.rect().center())
        self.pressed = False
        self.frames = []
        self.rig.frame_changed.connect(self.frames.append)
        self.addCleanup(self.cleanup_pet)

    def cleanup_pet(self):
        if self.pressed:
            self.mouse(QEvent.MouseButtonRelease, self.start + QPoint(0, 13))
        self.rig.stop()
        for timer in self.engine.findChildren(QTimer):
            timer.stop()
        self.window.close()
        self.window.deleteLater()

    def mouse(self, kind, global_position):
        if kind == QEvent.MouseButtonPress:
            button, buttons = Qt.LeftButton, Qt.LeftButton
            self.pressed = True
        elif kind == QEvent.MouseButtonRelease:
            button, buttons = Qt.LeftButton, Qt.NoButton
            self.pressed = False
        else:
            button, buttons = Qt.NoButton, Qt.LeftButton
        local = self.window.mapFromGlobal(global_position)
        event = QMouseEvent(kind, QPointF(local), QPointF(global_position),
                            button, buttons, Qt.NoModifier)
        QApplication.sendEvent(self.window, event)

    def begin_vertical_drag(self):
        self.mouse(QEvent.MouseButtonPress, self.start)
        self.mouse(QEvent.MouseMove, self.start + QPoint(0, 13))
        self.assertTrue(self.window._dragging)
        self.assertEqual(self.engine.current_phase, "dragged")

    def assert_pickup_picture(self):
        displayed = self.window.label.pixmap().toImage()
        renderer = self.rig.renderer
        size = self.window._pet_size
        # Compare with the approved hanging drawing, including the fixed grip
        # hand. The old atlas gesture raises both arms and is no longer the
        # expected picture when the dedicated pickup asset is installed.
        source = getattr(renderer, "_pickup_complete", None)
        if source is None or source.isNull():
            source = renderer._frame(renderer.manifest["phases"]["dragged"][0])
        reference = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).toImage()
        idle = renderer.base_pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).toImage()
        self.assertLess(
            image_error(displayed, reference), image_error(displayed, idle),
            "Holding a drag must visibly show the hanging pickup gesture, even at zero velocity",
        )

    def test_first_committed_drag_repaints_before_another_timer_event(self):
        before = self.window.label.pixmap().toImage()
        count = len(self.frames)
        self.begin_vertical_drag()
        self.assertGreater(len(self.frames), count, "Starting a drag needs immediate visible feedback")
        self.assertNotEqual(self.window.label.pixmap().toImage(), before)

    def test_holding_still_keeps_a_distinct_pickup_gesture(self):
        self.begin_vertical_drag()
        # No more move events arrive while the user keeps holding the pet.
        QTest.qWait(450)
        self.assertEqual(self.engine.current_phase, "dragged")
        self.assert_pickup_picture()

    def test_slow_purely_vertical_drag_keeps_pickup_gesture_and_renders(self):
        self.begin_vertical_drag()
        for offset in range(14, 40):
            self.mouse(QEvent.MouseMove, self.start + QPoint(0, offset))
            QTest.qWait(16)
        self.assertGreater(len(self.frames), 5)
        self.assertEqual(self.engine.current_phase, "dragged")
        self.assert_pickup_picture()

    def test_release_restores_latest_ipc_state_after_real_mouse_drag(self):
        self.engine.set_state("reading")
        self.begin_vertical_drag()
        self.ipc.phase_changed.emit("writing")
        self.assertEqual(self.engine.current_phase, "dragged")
        self.mouse(QEvent.MouseButtonRelease, self.start + QPoint(0, 13))
        self.assertFalse(self.window._dragging)
        self.assertEqual(self.engine.current_phase, "writing")

    def test_short_click_still_taps_without_entering_dragged(self):
        taps, drags = [], []
        self.window.pet_tapped.connect(lambda: taps.append(True))
        self.window.drag_started.connect(lambda: drags.append(True))
        self.mouse(QEvent.MouseButtonPress, self.start)
        self.mouse(QEvent.MouseMove, self.start + QPoint(2, 2))
        self.mouse(QEvent.MouseButtonRelease, self.start + QPoint(2, 2))
        self.assertEqual(taps, [True])
        self.assertEqual(drags, [])
        self.assertEqual(self.engine.current_phase, "idle")


if __name__ == "__main__":
    unittest.main()
