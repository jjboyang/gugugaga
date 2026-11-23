"""Exercise local attention gestures through real app wiring and Qt input."""
import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import pet_app
from pet.ipc import PetIPC
from pet.rig_animator import RigAnimator
from pet.window import PetWindow


class IdleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("DESKTOP_PET_IDLE_SLEEP_MS", None)
        self.pressed = False
        self.last_pose = None
        self.make_pet()

    def make_pet(self):
        made = {}

        def make_window(*args, **kwargs):
            made["window"] = PetWindow(*args, **kwargs)
            return made["window"]

        def make_rig(*args, **kwargs):
            made["rig"] = RigAnimator(*args, **kwargs)
            return made["rig"]

        ipc = PetIPC()
        with patch("pet.window._load_config", return_value={}), \
                patch.object(pet_app, "QApplication", return_value=self.app), \
                patch.object(pet_app, "PetWindow", side_effect=make_window), \
                patch.object(pet_app, "RigAnimator", side_effect=make_rig), \
                patch.object(pet_app, "PetIPC", return_value=ipc), \
                patch.object(ipc, "start"), patch.object(ipc, "stop"), \
                patch.object(self.app, "exec", return_value=0), \
                patch.object(pet_app.signal, "signal"):
            with self.assertRaises(SystemExit) as exited:
                pet_app.main()
            self.assertEqual(exited.exception.code, 0)
        self.window, self.rig, self.ipc = made["window"], made["rig"], ipc
        self.engine = self.rig.engine
        self.addCleanup(self.cleanup_pet, self.window, self.rig, self.engine)
        # Advance deterministic real seconds through production _paint(), not
        # a second implementation of the walking or screen-boundary logic.
        self.rig.timer.stop()
        screen = self.window.screen().availableGeometry()
        self.window.move(screen.center() - QPoint(self.window.width() // 2, self.window.height() // 2))
        step = self.rig.motion.step

        def capture(*args, **kwargs):
            self.last_pose = step(*args, **kwargs)
            return self.last_pose

        recorder = patch.object(self.rig.motion, "step", side_effect=capture)
        recorder.start()
        self.addCleanup(recorder.stop)

    @staticmethod
    def cleanup_pet(window, rig, engine):
        rig.stop()
        for timer in engine.findChildren(QTimer):
            timer.stop()
        window.close()
        window.deleteLater()
        QApplication.processEvents()

    def paint(self, seconds=0.1):
        self.rig._paint(seconds)

    def mouse(self, kind, position):
        if kind == QEvent.MouseButtonPress:
            button, buttons = Qt.LeftButton, Qt.LeftButton
            self.pressed = True
        elif kind == QEvent.MouseButtonRelease:
            button, buttons = Qt.LeftButton, Qt.NoButton
            self.pressed = False
        else:
            button, buttons = Qt.NoButton, Qt.LeftButton
        local = self.window.mapFromGlobal(position)
        event = QMouseEvent(kind, QPointF(local), QPointF(position), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(self.window, event)

    def start_walk(self, seconds=0.9):
        origin = self.window.pos()
        self.rig.idle_behavior.force_action("walk")
        self.paint(seconds)
        self.assertEqual(self.last_pose.idle_action, "walk")
        self.assertNotEqual(self.window.pos(), origin)
        return origin

    def test_exploration_invitation_animates_beside_its_own_bubble_and_stops_on_dismiss(self):
        origin = self.window.pos()
        self.engine.set_state("sleep")
        for action in ("wave", "knock"):
            with self.subTest(action=action):
                prompt = self.window.ask_to_share_exploration(lambda: None, 8000)
                self.rig.start_exploration_gesture(action, prompt)
                self.paint(0.75)
                self.assertEqual(self.last_pose.idle_action, action)
                self.assertEqual(self.window.pos(), origin)
                self.assertEqual(self.engine.current_phase, "sleep")
                prompt.close()
                self.paint(0.15)
                self.assertEqual(self.last_pose.idle_action, "")
                self.assertEqual(self.last_pose.phase, "sleep")

    def test_nearby_walk_visits_both_sides_and_returns_to_its_origin(self):
        origin = self.window.pos()
        cue = self.rig.idle_behavior.force_action("walk")
        positions = [QPoint(origin)]
        for _ in range(math.ceil(cue.duration / 0.05) + 1):
            self.paint(0.05)
            positions.append(self.window.pos())
        offsets = [point.x() - origin.x() for point in positions]
        self.assertLessEqual(max(map(abs, offsets)), 80)
        self.assertGreater(max(offsets), 60)
        self.assertLess(min(offsets), -60)
        self.assertTrue(all(point.y() == origin.y() for point in positions))
        self.assertEqual(self.window.pos(), origin)

    def test_walk_is_clamped_to_the_current_screen(self):
        geometry = self.window.screen().availableGeometry()
        self.window.move(geometry.left() + 2, geometry.top() + 20)
        origin = self.window.pos()
        cue = self.rig.idle_behavior.force_action("walk")
        for _ in range(math.ceil(cue.duration / 0.06) + 1):
            self.paint(0.06)
            self.assertTrue(geometry.contains(self.window.geometry()))
            self.assertLessEqual(abs(self.window.x() - origin.x()), 80)
        self.assertEqual(self.window.pos(), origin)

    def test_mouse_press_stops_walking_without_snapping_back(self):
        old_origin = self.start_walk()
        caught = self.window.pos()
        point = self.window.mapToGlobal(self.window.rect().center())
        self.mouse(QEvent.MouseButtonPress, point)
        self.assertEqual(self.window.pos(), caught)
        self.paint(0.7)
        self.assertEqual(self.window.pos(), caught)
        self.assertEqual(self.last_pose.idle_action, "")
        self.assertNotEqual(caught, old_origin)
        self.mouse(QEvent.MouseButtonRelease, point)
        self.paint(0.4)
        self.assertEqual(self.window.pos(), caught)

    def test_drag_after_an_interrupted_walk_uses_the_new_position(self):
        old_origin = self.start_walk()
        point = self.window.mapToGlobal(self.window.rect().center())
        self.mouse(QEvent.MouseButtonPress, point)
        moved = point + QPoint(35, 16)
        self.mouse(QEvent.MouseMove, moved)
        self.assertEqual(self.engine.current_phase, "dragged")
        dragged = self.window.pos()
        self.paint(0.2)
        self.assertEqual(self.window.pos(), dragged)
        self.mouse(QEvent.MouseButtonRelease, moved)
        self.paint(0.6)
        self.assertEqual(self.window.pos(), dragged)
        self.assertNotEqual(dragged, old_origin)
        self.assertEqual(self.last_pose.idle_action, "")

    def test_work_or_sleep_interrupts_a_walk_and_keeps_its_current_position(self):
        for phase in ("reading", "writing", "thinking", "executing", "angry", "sleep"):
            self.engine.set_state("idle")
            geometry = self.window.screen().availableGeometry()
            self.window.move(geometry.center() - QPoint(self.window.width() // 2, self.window.height() // 2))
            self.start_walk()
            stopped = self.window.pos()
            self.ipc.phase_changed.emit(phase)
            self.paint(0.3)
            with self.subTest(phase=phase):
                self.assertEqual(self.last_pose.phase, phase)
                self.assertEqual(self.last_pose.idle_action, "")
                self.assertEqual(self.window.pos(), stopped)
                self.paint(2.0)
                self.assertEqual(self.window.pos(), stopped)

    def test_visible_popup_or_hidden_pet_blocks_attention_until_a_new_quiet_period(self):
        self.start_walk()
        stopped = self.window.pos()
        popup = QWidget()
        popup.show()
        self.window._settings_popup = popup
        try:
            self.paint(0.2)
            self.assertEqual(self.last_pose.idle_action, "")
            self.assertEqual(self.window.pos(), stopped)
            popup.hide()
            self.paint(7.9)
            self.assertEqual(self.last_pose.idle_action, "")
            self.rig.idle_behavior.force_action("hop")
            self.window.hide()
            self.paint(0.2)
            self.assertEqual(self.last_pose.idle_action, "")
            self.window.show()
            self.paint(7.9)
            self.assertEqual(self.last_pose.idle_action, "")
        finally:
            self.window._settings_popup = None
            popup.close()

    def test_penguin_switch_discards_pending_attention_actions(self):
        self.start_walk()
        self.window.character_switch_requested.emit()
        self.assertFalse(self.rig.enabled)
        stopped = self.window.pos()
        self.rig.idle_behavior.force_action("walk")
        QTest.qWait(60)
        self.assertEqual(self.window.pos(), stopped)
        self.assertFalse(self.rig.timer.isActive())
        self.window.character_switch_requested.emit()
        self.rig.timer.stop()
        self.paint(7.9)
        self.assertEqual(self.last_pose.idle_action, "")
        self.assertEqual(self.window.pos(), stopped)

    def test_untracked_context_menu_also_blocks_random_attention(self):
        self.start_walk()
        stopped = self.window.pos()
        menu = QWidget(None, Qt.Popup)
        menu.show()
        try:
            self.app.processEvents()
            self.assertIsNotNone(QApplication.activePopupWidget())
            self.paint(0.1)
            self.assertEqual(self.last_pose.idle_action, "")
            self.paint(15)
            self.assertEqual(self.window.pos(), stopped)
            self.assertEqual(self.last_pose.idle_action, "")
        finally:
            menu.close()

    def test_call_menu_samples_cursor_once_and_finishes_seated_at_destination(self):
        at = self.window.rect().center()
        event = QContextMenuEvent(QContextMenuEvent.Mouse, at, self.window.mapToGlobal(at))
        QApplication.sendEvent(self.window, event)
        popup = QApplication.activePopupWidget()
        call = next(b for b in popup.findChildren(QPushButton) if b.text() == "过来一下")
        QTest.mouseClick(call, Qt.LeftButton)
        origin = self.window.pos()
        cursor = origin + QPoint(-100, -80)
        with patch("pet.rig_animator.QCursor.pos", return_value=cursor) as point:
            self.paint(0.5)
            self.assertEqual(self.window.pos(), origin)
            self.paint(0.8)
            target = self.rig.call.target
            point.return_value = origin + QPoint(150, 60)
            self.paint(0.9)
            self.assertEqual(self.last_pose.idle_action, "walk")
            self.assertLess(self.window.x(), origin.x())
            self.assertLess(self.window.y(), origin.y())
            self.paint(8)
            self.assertIsNone(self.rig.call)
            self.assertEqual(self.window.pos(), target)
            self.assertLess(abs(target.x() + self.window.width() / 2 - cursor.x()),
                            self.window.width() * 0.50)
            self.paint(0.1)
            self.assertEqual(self.last_pose.idle_action, "")
            self.assertEqual(self.window.pos(), target)

    def test_facial_taps_cover_peek_and_recover_without_belly_reply(self):
        size = self.window.width()
        QTest.mouseClick(self.window, Qt.LeftButton, pos=QPoint(size // 2, size // 2))
        self.paint(0.25)
        self.assertLess(self.last_pose.eye_open, 0.05)
        cheek = QPoint(round(size * 0.62), round(size * 0.66))
        QTest.mouseClick(self.window, Qt.LeftButton, pos=cheek)
        self.paint(0.2)
        self.assertLess(self.last_pose.nodes["head"].angle, -2)
        for _ in range(2):
            QTest.mouseClick(self.window, Qt.LeftButton, pos=cheek)
        self.paint(0.5)
        self.assertEqual(self.window._speech_popup.reply.text, "别吵别吵")
        self.assertEqual(self.last_pose.cover_hands, 1)
        self.assertEqual(self.last_pose.peek, 0)
        QTest.mouseClick(self.window, Qt.LeftButton, pos=cheek)
        self.paint(0.3)
        self.assertEqual(self.last_pose.cover_hands, 1)
        self.paint(0.8)
        self.assertEqual(self.last_pose.peek, 1)
        self.paint(1.0)
        self.assertEqual(self.last_pose.cover_hands, 0)
        self.assertEqual(self.rig.face.kind, "")
        self.assertEqual(self.engine.current_phase, "idle")

    def test_switching_character_or_dragging_cancels_pending_call(self):
        self.window.come_here_requested.emit()
        self.window.character_switch_requested.emit()
        self.assertIsNone(self.rig.call)
        self.window.character_switch_requested.emit()
        self.rig.timer.stop()
        self.window.come_here_requested.emit()
        start = self.window.frameGeometry().center()
        self.mouse(QEvent.MouseButtonPress, start)
        self.mouse(QEvent.MouseMove, start + QPoint(35, 0))
        self.assertIsNone(self.rig.call)
        position = self.window.pos()
        self.paint(4.0)
        self.assertEqual(self.window.pos(), position)
        self.mouse(QEvent.MouseButtonRelease, start + QPoint(35, 0))

    def test_food_follows_pointer_then_transfers_only_at_mouth(self):
        self.window.contextMenuEvent(None)
        popup = self.app.activePopupWidget()
        next(b for b in popup.findChildren(QPushButton) if b.text() == "递小鱼干").click()
        social = self.rig.social
        food = social.pointer_food
        mouth = self.window.mapToGlobal(QPoint(self.window.width() // 2, round(self.window.height() * 0.69)))
        with patch("pet.rig_animator.QCursor.pos", return_value=mouth - QPoint(100, 0)) as cursor:
            self.paint(0.8)
            self.assertTrue(food.isVisible())
            self.assertTrue(food.windowFlags() & Qt.WindowTransparentForInput)
            self.assertLess((food.geometry().center() - cursor.return_value).manhattanLength(), 3)
            cursor.return_value = mouth
            self.paint(0.2)
            self.assertEqual(social.kind, "offer_food")
            with patch("pet.social_gestures.random.random", return_value=0.05):
                self.paint(0.2)
            self.assertFalse(food.isVisible())
            self.assertEqual(social.kind, "eat")
            self.paint(2.4)
            self.assertEqual(self.window._speech_popup.reply.text, "嗝……还有吗？")
            self.paint(1.5)
            self.assertFalse(social.kind)

    def test_cancel_food_and_click_to_feed_do_not_trigger_cheek_or_belly(self):
        social = self.rig.social
        self.window.feed_requested.emit()
        self.window.feed_requested.emit()
        self.assertFalse(social.kind)
        self.window.feed_requested.emit()
        size = self.window.width()
        QTest.mouseClick(self.window, Qt.LeftButton, pos=QPoint(size // 2, round(size * 0.69)))
        self.assertEqual(social.kind, "eat")
        self.assertFalse(self.rig.face.kind)
        self.window.character_switch_requested.emit()
        self.assertFalse(self.window.snack_offered)
        self.window.feed_requested.emit()
        self.assertFalse(social.kind)

    def test_both_catchphrases_accept_the_other_line_once_then_laugh(self):
        from pet.speech_bubble import Reply
        size = self.window.width()
        for line, answer in (("deep deep", "seek seek"), ("seek seek", "deep deep")):
            with patch("pet.window.choose_reply", return_value=Reply(line, "bubbles")):
                for _ in range(3):
                    QTest.mouseClick(self.window, Qt.LeftButton, pos=QPoint(size // 2, size * 3 // 4))
            bubble = self.window._speech_popup
            self.assertEqual(bubble.answer_button.text(), answer)
            QTest.mouseClick(bubble.answer_button, Qt.LeftButton)
            self.assertFalse(bubble.isVisible())
            self.assertEqual(self.rig.social.kind, "laugh")
            self.paint(0.17)
            self.assertIsNone(self.window._speech_popup)
            self.paint(0.55)
            self.assertLess(self.last_pose.eye_open, 0.1)
            self.assertEqual(self.window._speech_popup.reply.text, "嘿嘿，对上啦")
            self.paint(2.0)
            self.assertFalse(self.rig.social.kind)

    def test_fish_has_time_for_idle_gestures_and_longer_anger_without_changing_penguin(self):
        self.assertGreaterEqual(self.engine._idle_to_sleep_ms, 100000)
        self.assertGreaterEqual(self.engine.angry_hold_ms, 3000)
        self.window.character_switch_requested.emit()
        self.assertEqual(self.engine._idle_to_sleep_ms, 20000)
        self.assertEqual(self.engine.angry_hold_ms, 450)

    def test_an_explicit_sleep_environment_setting_is_respected(self):
        # Leave deletion to its registered cleanup; a second app instance's
        # event processing must not turn that cleanup into a double deletion.
        self.rig.stop()
        self.window.hide()
        for timer in self.engine.findChildren(QTimer):
            timer.stop()
        os.environ["DESKTOP_PET_IDLE_SLEEP_MS"] = "45000"
        self.make_pet()
        self.assertEqual(self.engine._idle_to_sleep_ms, 45000)


if __name__ == "__main__":
    unittest.main()
