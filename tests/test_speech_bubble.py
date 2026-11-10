"""Character replies, real tap delivery, popup lifetime and screen boundaries."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.speech_bubble import DAFEIYU_REPLIES, PENGUIN_REPLY, SpeechBubble, choose_reply
from pet.window import PetWindow


class SpeechBubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch("pet.window._load_config", return_value={}):
            self.window = PetWindow()
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def tap_belly(self, count=3):
        for _ in range(count):
            QTest.mouseClick(self.window, Qt.LeftButton,
                             pos=QPoint(self.window.width() // 2, self.window.height() * 3 // 4))

    def test_random_choice_contains_all_four_lines_without_consecutive_repeats(self):
        for previous in DAFEIYU_REPLIES:
            with patch("pet.speech_bubble.random.choice", side_effect=lambda choices: choices[0]) as choose:
                reply = choose_reply("dafeiyu", previous.text)
            candidates = choose.call_args.args[0]
            self.assertEqual({r.text for r in candidates},
                             {r.text for r in DAFEIYU_REPLIES} - {previous.text})
            self.assertNotEqual(reply.text, previous.text)
        self.assertEqual(choose_reply("penguin"), PENGUIN_REPLY)

    def test_three_belly_clicks_speak_but_head_clicks_and_slow_clicks_do_not(self):
        with patch("pet.window.time.monotonic", side_effect=[10.0, 11.6, 13.2, 13.3, 13.4]):
            self.tap_belly(3)
            self.assertIsNone(self.window._speech_popup)
            QTest.mouseClick(self.window, Qt.LeftButton, pos=QPoint(70, 30))
            self.tap_belly(2)
        self.assertIn(self.window._speech_popup.reply, DAFEIYU_REPLIES)

    def test_repeated_taps_deliver_every_click_and_replace_the_reply(self):
        clicks = []
        self.window.pet_tapped.connect(lambda: clicks.append(True))
        self.tap_belly()
        first = self.window._speech_popup
        self.assertTrue(first.isVisible())
        self.assertNotEqual(first.windowType(), Qt.Popup)
        self.assertTrue(first.windowFlags() & Qt.WindowTransparentForInput)
        self.assertTrue(first.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(first.testAttribute(Qt.WA_ShowWithoutActivating))
        self.tap_belly()
        second = self.window._speech_popup
        self.assertEqual(len(clicks), 6)
        self.assertIsNot(first, second)
        self.assertFalse(first._hold_timer.isActive())
        self.assertNotEqual(second.reply.text, first.reply.text)

    def test_new_reply_gets_its_own_full_lifetime_then_dismisses(self):
        with patch.object(SpeechBubble, "HOLD_MS", 180):
            self.tap_belly()
            QTest.qWait(120)
            self.tap_belly()
            second = self.window._speech_popup
            QTest.qWait(100)
            self.assertIs(self.window._speech_popup, second)
            self.assertTrue(second.isVisible())
            QTest.qWait(320)
        self.assertIsNone(self.window._speech_popup)

    def test_character_switch_clears_partial_taps_and_uses_penguin_line(self):
        self.tap_belly(2)
        self.window.set_character("penguin")
        self.tap_belly(1)
        self.assertIsNone(self.window._speech_popup)
        self.tap_belly(2)
        self.assertEqual(self.window._speech_popup.reply, PENGUIN_REPLY)
        self.window.set_character("dafeiyu")
        self.assertIsNone(self.window._speech_popup)
        self.tap_belly()
        self.assertIn(self.window._speech_popup.reply, DAFEIYU_REPLIES)

    def test_bubble_follows_pet_and_closes_with_its_owner(self):
        self.window.move(250, 350)
        self.tap_belly()
        popup = self.window._speech_popup
        initial = popup.pos()
        self.window.move(self.window.pos() + QPoint(-40, -20))
        self.app.processEvents()
        self.assertEqual(popup.pos(), initial + QPoint(-40, -20))
        self.window.close()
        self.assertIsNone(self.window._speech_popup)
        self.assertFalse(popup.isVisible())

    def test_all_screen_edges_and_negative_monitor_coordinates(self):
        popup = SpeechBubble(DAFEIYU_REPLIES[1], parent=self.window)
        self.addCleanup(popup.close)
        available = QRect(-1920, -200, 1920, 1080)
        for x in (-1920, -1000, -140):
            for y in (-200, 200, 740):
                with self.subTest(x=x, y=y):
                    pet = QRect(x, y, 140, 140)
                    popup.place(pet, available)
                    self.assertTrue(available.contains(popup.geometry()))
                    self.assertEqual(popup.tail_on_top, y == -200)
                    self.assertTrue(30 <= popup.tail_x <= popup.width() - 30)


if __name__ == "__main__":
    unittest.main()
