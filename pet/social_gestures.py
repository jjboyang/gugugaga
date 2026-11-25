"""Feeding, exchanging catchphrases and brief greetings on the seated rig."""
import math
import random
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from pet import photo_share_motion
from pet.companion import smooth


def fish_snack():
    """A small toasted fish with a notched tail and an illustrated crust."""
    pixmap = QPixmap(104, 52)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(2, 1)
    crust = QLinearGradient(0, 8, 2, 47)
    for at, color in ((0, "#ffe5ac"), (0.45, "#e7aa68"), (1, "#b96e46")):
        crust.setColorAt(at, QColor(color))
    p.setBrush(crust)
    p.setPen(QPen(QColor("#704939"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    shape = QPainterPath(QPointF(24, 22))
    shape.cubicTo(40, 8, 63, 6, 79, 13)
    shape.cubicTo(88, 15, 96, 20, 99, 25)
    shape.cubicTo(91, 37, 74, 41, 56, 40)
    shape.cubicTo(43, 40, 32, 36, 24, 30)
    shape.quadTo(12, 40, 3, 42)
    shape.quadTo(4, 33, 10, 26)
    shape.quadTo(3, 18, 3, 11)
    shape.quadTo(16, 14, 24, 22)
    shape.closeSubpath()
    p.drawPath(shape)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor("#a26543"), 2, Qt.SolidLine, Qt.RoundCap))
    for x in (37, 48, 59):
        mark = QPainterPath(QPointF(x, 19))
        mark.quadTo(x + 6, 23, x, 27)
        p.drawPath(mark)
    p.setBrush(QColor("#604033"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(84, 21), 2.8, 2.8)
    p.setBrush(QColor("#fff1cc"))
    p.drawEllipse(QPointF(85, 20), 0.9, 0.9)
    p.end()
    return pixmap


class SocialGestures:
    def __init__(self, rig):
        self.rig = rig
        self.window = rig.window
        self.snack = fish_snack()
        flags = Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        flags |= Qt.Window if sys.platform == "darwin" else Qt.Tool
        self.pointer_food = QLabel(self.window, flags)
        self.pointer_food.setAttribute(Qt.WA_TranslucentBackground)
        self.pointer_food.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pointer_food.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.pointer_food.setStyleSheet("background: transparent")
        self.prompt = None
        self.photo = None
        self._reveal_photo = None
        self.kind = ""
        self.age = 0.0
        self.hover = 0.0
        self.hiccup = False
        self.catch_point = QPointF()
        self.window.feed_requested.connect(self.offer_snack)
        self.window.snack_given.connect(self.take_snack)
        self.window.joke_answered.connect(self.answer_joke)
        self.window.toast_clicked.connect(self.clink)

    def clear(self):
        self.pointer_food.hide()
        self.window.cup_offered = False
        self.window.snack_offered = False
        if self.prompt is not None and self.prompt is self.window._speech_popup:
            self.window._dismiss_speech_bubble()
        self.prompt = None
        self.photo = None
        self._reveal_photo = None
        self.kind = ""
        self.age = self.hover = 0.0

    def _start(self, kind):
        if not self.rig.enabled or not self.window.isVisible() or self.window._dragging:
            return False
        self.rig.cancel_interaction()
        self.rig.engine.notify_user_activity()
        self.rig.notify_user_activity()
        self.kind = kind
        return True

    def offer_snack(self):
        if self.kind == "offer_food":
            self.clear()
            return
        if self._start("offer_food"):
            self.window.snack_offered = True
            width = max(23, round(self.window.width() * 0.20))
            icon = self.snack.scaledToWidth(width, Qt.SmoothTransformation)
            self.pointer_food.setPixmap(icon)
            self.pointer_food.setFixedSize(icon.size())
            self.pointer_food.move(QCursor.pos() - self.pointer_food.rect().center())
            self.pointer_food.show()
            self.prompt = self.window.say("递到嘴边嘛", "whale")

    def take_snack(self, local):
        if self.kind == "offer_food":
            self.clear()
            self.kind = "eat"
            self.catch_point = QPointF(local.x() * 512 / self.window.width(),
                                       local.y() * 512 / self.window.height())
            self.hiccup = random.random() < 0.20

    def answer_joke(self):
        self._start("laugh")

    def show_exploration_photo(self, image, on_reveal):
        if not self.rig.can_show_exploration() or not self._start("exploration_photo"):
            return False
        self.photo = image
        self._reveal_photo = on_reveal
        return True

    def greet_after_work(self):
        if (self.rig.work_mode and not self.kind and not self.rig.call and not self.rig.face.kind
                and self.rig.pomodoro_mode != "focus_done" and not self.window._speech_popup
                and not self.window._left_down and QApplication.activePopupWidget() is None
                and self._start("stretch")):
            self.prompt = self.window.say("歇口气，鲸鲸～", "whale")
            return True
        return False

    def invite_toast(self):
        if self.rig.pomodoro_mode == "focus_done":
            self._start("bell")

    def clink(self):
        if self.kind == "cup" and self._start("clink"):
            self.prompt = self.window.say("叮！辛苦啦", "sparkle")

    def advance(self, dt, cursor):
        before = self.age
        self.age += dt
        t = self.age
        if self.kind == "offer_food":
            self.pointer_food.move(cursor - self.pointer_food.rect().center())
            local = self.window.mapFromGlobal(cursor)
            self.hover = self.hover + dt if self.window.at_mouth(local) else 0.0
            if self.hover >= 0.36:
                self.take_snack(local)
            elif t >= 15:
                self.clear()
        elif self.kind == "eat":
            if before < 2.35 <= t:
                self.prompt = self.window.say("嗝……还有吗？" if self.hiccup else "香香的～", "whale")
            if t >= 3.7:
                self.clear()
        elif self.kind == "laugh":
            if before < 0.34 <= t:
                self.prompt = self.window.say("嘿嘿，对上啦", "sparkle")
            if t >= 2.1:
                self.clear()
        elif self.kind == "bell" and t >= 1.1:
            self.kind, self.age = "cup", 0.0
            self.window.cup_offered = True
            self.prompt = self.window.say("点我的杯子，碰一个～", "sparkle", hold_ms=7900)
        elif self.kind == "cup" and t >= 8:
            self.clear()
        elif self.kind in {"clink", "stretch"} and t >= 2.6:
            self.clear()
        elif self.kind == "exploration_photo":
            if before < photo_share_motion.REVEAL_SECONDS:
                if self.rig._idle_blocked():
                    self.clear()
                    return
                if t >= photo_share_motion.REVEAL_SECONDS:
                    self._reveal_photo()
            if t >= photo_share_motion.DURATION_SECONDS:
                self.clear()

    def apply_pose(self, pose):
        t = self.age
        head = pose.nodes["head"]
        if self.kind == "offer_food":
            sniff = smooth(self.hover / 0.23)
            head.dy += 5 * sniff
            head.angle += 2.0 * sniff
        elif self.kind == "eat":
            bite = max(0, math.sin((t - 0.4) * 9.4)) if 0.4 < t < 2.3 else 0.0
            head.dy += 3.2 * bite
            pose.eye_open = min(pose.eye_open, 1 - 0.95 * bite)
            lift = 6 * smooth(t / 0.42) * (1 - smooth((t - 1.95) / 0.38))
            for side in ("left", "right"):
                pose.nodes["arm_" + side].dy -= lift
            if self.hiccup:
                hop = math.exp(-((t - 2.30) / 0.095) ** 2)
                pose.nodes["root"].dy -= 9 * hop
                reach = smooth((t - 2.45) / 0.32) * (1 - smooth((t - 3.23) / 0.45))
                pose.nodes["arm_right"].dy -= 12 * reach
                head.angle += 3.5 * reach
        elif self.kind == "laugh":
            grin = smooth((t - 0.32) / 0.14) * (1 - smooth((t - 1.48) / 0.45))
            pose.eye_open = min(pose.eye_open, 1 - grin)
            head.angle += 3 * grin
            pose.nodes["body"].dy -= abs(math.sin((t - 0.32) * 7.4)) * 5 * grin
        elif self.kind == "exploration_photo":
            photo_share_motion.apply_pose(pose, t)

    def eating_texture(self, awake):
        t = self.age
        if t > 2.13:
            return awake
        # Pull the snack into the original folded hands, then nibble it away.
        take = smooth(t / 0.32)
        tip_up = smooth((t - 0.41) / 0.43)
        center = self.catch_point * (1 - take) + QPointF(256 - 13 * tip_up, 391 - 7 * tip_up) * take
        eaten = sum(smooth((t - start) / 0.14) for start in (0.86, 1.42, 1.98)) / 3
        result = QPixmap(awake)
        p = QPainter(result)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(center)
        p.rotate(-11 - 12 * tip_up)
        rect = QRectF(-47, -23.5, 94, 47)
        p.setClipRect(QRectF(rect.x() + 21 * eaten, rect.y(), rect.width() * (1 - eaten), rect.height()))
        p.drawPixmap(rect, self.snack, QRectF(self.snack.rect()))
        if take > 0.95:
            # The lower edges tuck behind the original fingertips.
            p.resetTransform()
            fingertips = QPainterPath()
            fingertips.addEllipse(QRectF(218, 395, 27, 19))
            fingertips.addEllipse(QRectF(266, 396, 25, 18))
            p.setClipPath(fingertips)
            p.drawPixmap(0, 0, awake)
        p.end()
        return result

    def lift_snack(self, vertices):
        t = self.age
        lift = 12 * smooth((t - 0.41) / 0.43) * (1 - smooth((t - 1.98) / 0.40))
        if lift <= 0:
            return vertices
        moved = []
        for point in vertices:
            x, y = point.x(), point.y()
            radius = ((x - 256) / 75) ** 2 + ((y - 398) / 56) ** 2
            weight = (1 - smooth((radius - 0.26) / 0.74)) * (1 - smooth((y - 407) / 23))
            moved.append(QPointF(x, y - lift * weight))
        return moved
