"""Small, non-activating character dialogue with a painted speech tail."""
from __future__ import annotations

from dataclasses import dataclass
import random
import sys

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QWidget


@dataclass(frozen=True)
class Reply:
    text: str
    mood: str


DAFEIYU_REPLIES = (
    Reply("鲸鲸", "whale"),
    Reply("deep deep", "bubbles"),
    Reply("seek seek", "sparkle"),
    Reply("别吵别吵", "hush"),
)
PENGUIN_REPLY = Reply("咕咕嘎嘎", "penguin")


def choose_reply(character, previous_text=None):
    """Keep the penguin's easter egg and avoid consecutive fish repeats."""
    if character != "dafeiyu":
        return PENGUIN_REPLY
    return random.choice([reply for reply in DAFEIYU_REPLIES if reply.text != previous_text])


class SpeechBubble(QWidget):
    dismissed = Signal()
    answered = Signal()
    HOLD_MS = 2400

    def __init__(self, reply, character="dafeiyu", pet_size=140, parent=None, *, answer="", hold_ms=None,
                 answer_accessible_name="", answer_on_pet_tap=False):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.WindowDoesNotAcceptFocus)
        if not answer:
            flags |= Qt.WindowTransparentForInput
        flags |= Qt.Window if sys.platform == "darwin" else Qt.Tool
        super().__init__(parent, flags)
        self.hold_ms = hold_ms if hold_ms is not None else self.HOLD_MS * (2 if answer else 1)
        self.reply = reply
        self.character = character
        self.tail_on_top = False
        self.tail_x = 0.0
        self._progress = 0.0
        self._closing = False
        self.answer_on_pet_tap = answer_on_pet_tap
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not bool(answer))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.NoFocus)

        self._font = QFont()
        self._font.setFamilies(["PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"])
        self._font.setPixelSize(max(14, min(22, round(pet_size * 0.115))))
        self._font.setWeight(QFont.DemiBold)
        metrics = QFontMetrics(self._font)
        self.setFixedSize(metrics.horizontalAdvance(reply.text) + 82,
                          max(44, metrics.height() + 20) + 24)
        self.answer_button = None
        if answer:
            button = QPushButton(answer, self)
            button.setAccessibleName(answer_accessible_name or "接梗：" + answer)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setFont(self._font)
            button.setStyleSheet("""
                QPushButton {color:#245783; background:#e4f1ff; border:1px solid #afcde6;
                             border-radius:10px; padding:1px 8px;}
                QPushButton:hover {background:#d1e8ff;}
            """)
            button.adjustSize()
            button.clicked.connect(self.accept_answer)
            self.setFixedWidth(self.width() + button.width() + 4)
            self.answer_button = button
        self.tail_x = self.width() / 2

        self._animation = QVariantAnimation(self)
        self._animation.valueChanged.connect(self._set_progress)
        self._animation.finished.connect(self._animation_finished)
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self.fade_out)

    def showEvent(self, event):
        super().showEvent(event)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()
        self._hold_timer.start(self.hold_ms)

    def accept_answer(self):
        if self._closing or not self.isVisible() or not self.answer_button or not self.answer_button.isEnabled():
            return False
        self.answer_button.setEnabled(False)
        self.close()
        self.answered.emit()
        return True

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    def fade_out(self):
        self._closing = True
        self._hold_timer.stop()
        self._animation.stop()
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.InCubic)
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(0.0)
        self._animation.start()

    def _animation_finished(self):
        if self._closing:
            self.close()

    def closeEvent(self, event):
        self._hold_timer.stop()
        self._animation.stop()
        self.dismissed.emit()
        super().closeEvent(event)

    def place(self, pet_geometry, available, avoid=None):
        """Stay inside the current monitor, pointing back toward the pet."""
        gap_anchor = pet_geometry.top() + round(pet_geometry.height() * 0.18)
        x = pet_geometry.center().x() - self.width() // 2
        y = gap_anchor - self.height()
        self.tail_on_top = y < available.top() + 4
        if self.tail_on_top:
            y = pet_geometry.bottom() + 2
        x = max(available.left() + 4, min(x, available.right() - self.width() - 3))
        y = max(available.top() + 4, min(y, available.bottom() - self.height() - 3))
        if avoid is not None and QRect(x, y, self.width(), self.height()).intersects(avoid):
            above = min(y, avoid.top() - self.height() - 2)
            if above >= available.top() + 4:
                y, self.tail_on_top = above, False
            else:
                y = min(available.bottom() - self.height() - 3, max(avoid.bottom(), pet_geometry.bottom()) + 3)
                self.tail_on_top = True
        self.tail_x = max(30.0, min(self.width() - 30.0, pet_geometry.center().x() - x))
        self.move(x, y)
        if self.answer_button:
            body_center = (16 if self.tail_on_top else 6) + (self.height() - 24) // 2
            button = self.answer_button
            button.move(self.width() - 17 - button.width(), body_center - button.height() // 2)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        progress = self._progress
        painter.setOpacity(progress)
        anchor_y = 4 if self.tail_on_top else self.height() - 8
        painter.translate(self.tail_x, anchor_y)
        scale = 0.94 + 0.06 * progress
        painter.scale(scale, scale)
        painter.translate(-self.tail_x, -anchor_y)

        fish = self.character == "dafeiyu"
        accent = QColor("#457ab2" if fish else "#9b7847")
        ink = QColor("#284d7a" if fish else "#675039")
        body = QRectF(8, 16 if self.tail_on_top else 6, self.width() - 16, self.height() - 24)
        shape = QPainterPath()
        shape.addRoundedRect(body, 17, 17)
        tail = QPainterPath()
        edge = body.top() if self.tail_on_top else body.bottom()
        direction = -1 if self.tail_on_top else 1
        tail.moveTo(self.tail_x - 8, edge - direction * 2)
        tail.quadTo(self.tail_x - 4, edge + direction * 6, self.tail_x + 2, edge + direction * 8)
        tail.quadTo(self.tail_x + 1, edge + direction * 3, self.tail_x + 8, edge - direction * 2)
        tail.closeSubpath()
        shape = shape.united(tail)

        # A quiet painted shadow works on translucent windows on every platform.
        painter.setPen(Qt.NoPen)
        for offset, alpha in ((3, 7), (2, 9), (1, 12)):
            painter.save()
            painter.translate(0, offset)
            painter.setBrush(QColor(29, 55, 85, alpha))
            painter.drawPath(shape)
            painter.restore()
        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        fill.setColorAt(0, QColor("#ffffff"))
        fill.setColorAt(1, QColor("#eef6ff" if fish else "#fff7e9"))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor("#a9c8e8" if fish else "#dfcba9"), 1.2))
        painter.drawPath(shape)

        self._paint_content(painter, body, accent, ink)
        painter.end()

    def _paint_content(self, painter, body, accent, ink):
        # The character's blue/white trim becomes a tiny illustrated mood badge.
        fish = self.character == "dafeiyu"
        badge = QPointF(body.left() + 24, body.center().y())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e0edfc" if fish else "#f5e7ce"))
        painter.drawEllipse(badge, 15, 15)
        painter.save()
        painter.translate(badge)
        self._paint_mood(painter, accent, ink)
        painter.restore()

        painter.setFont(self._font)
        painter.setPen(ink)
        painter.drawText(QRectF(body.left() + 48, body.top(), body.width() - 58, body.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, self.reply.text)

    def _paint_mood(self, p, accent, ink):
        p.setPen(QPen(accent, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        mood = self.reply.mood
        if mood == "whale":
            whale = QPainterPath()
            whale.moveTo(-10, 1)
            whale.cubicTo(-10, -9, 5, -9, 7, -1)
            whale.quadTo(10, -2, 11, -6)
            whale.quadTo(13, 6, 4, 7)
            whale.quadTo(-9, 10, -10, 1)
            p.setBrush(accent)
            p.drawPath(whale)
            p.setPen(QPen(QColor("#ffffff"), 1.7, Qt.SolidLine, Qt.RoundCap))
            p.drawPoint(QPointF(-4, 0))
            p.drawLine(QPointF(-3, -10), QPointF(-3, -12))
            p.drawLine(QPointF(-6, -11), QPointF(-5, -12))
        elif mood == "bubbles":
            for x, y, radius in ((-5, 5, 4.5), (5, -4, 3.5), (-5, -10, 2)):
                p.drawEllipse(QPointF(x, y), radius, radius)
            p.setPen(QPen(QColor("#ffffff"), 1.6, Qt.SolidLine, Qt.RoundCap))
            p.drawPoint(QPointF(-6, 3))
            p.drawPoint(QPointF(4, -5))
        elif mood == "sparkle":
            star = QPainterPath()
            star.moveTo(-2, -11)
            for x, y in ((1, -3), (8, 0), (1, 3), (-2, 11), (-5, 3), (-12, 0), (-5, -3)):
                star.lineTo(x, y)
            star.closeSubpath()
            p.setBrush(accent)
            p.drawPath(star)
            p.drawLine(QPointF(8, -10), QPointF(8, -5))
            p.drawLine(QPointF(5.5, -7.5), QPointF(10.5, -7.5))
        elif mood == "hush":
            # Pouty eyes and soft blush rather than an unrelated emoji font.
            p.drawLine(QPointF(-9, -5), QPointF(-3, -3))
            p.drawLine(QPointF(3, -3), QPointF(9, -5))
            p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(-6, -1), QPointF(-6, 2))
            p.drawLine(QPointF(6, -1), QPointF(6, 2))
            p.drawLine(QPointF(-2, 7), QPointF(2, 7))
            p.setPen(QPen(QColor("#e9a8b4"), 2.3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(-11, 4), QPointF(-8, 4))
            p.drawLine(QPointF(8, 4), QPointF(11, 4))
        else:
            p.setBrush(ink)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(-5, -2), 1.7, 2.2)
            p.drawEllipse(QPointF(5, -2), 1.7, 2.2)
            p.setBrush(accent)
            beak = QPainterPath()
            beak.moveTo(-3, 3)
            beak.lineTo(3, 3)
            beak.lineTo(0, 6)
            beak.closeSubpath()
            p.drawPath(beak)


class DiscoveryBubble(SpeechBubble):
    """A picture and optional caption, or a wrapped discovery beside the pet."""

    TEXT_FLAGS = Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap | Qt.TextWrapAnywhere
    INSET = 12

    def __init__(self, text, image, pet_size, parent):
        hold_ms = max(11_000 if not image.isNull() else 8_000, min(28_000, 4_000 + len(text) * 80))
        super().__init__(Reply(text, "whale"), pet_size=pet_size, parent=parent, hold_ms=hold_ms)
        self.image = image
        self._font.setPixelSize(min(16, self._font.pixelSize()))
        self._font.setWeight(QFont.Medium)
        self._available_size = QSize()
        self._image_size = QSize()
        self.setAccessibleName(text or "大肥鱼分享的图片")

    def place(self, pet_geometry, available, avoid=None):
        bounds = available.size()
        if self._available_size != bounds:
            self._available_size = bounds
            self._fit_content(bounds)
        super().place(pet_geometry, available, avoid)

    def _fit_content(self, bounds):
        metrics = QFontMetrics(self._font)
        text = self.reply.text
        line_width = max((metrics.horizontalAdvance(line) for line in text.splitlines()), default=0)
        preferred_width = max(150, line_width + 40)
        if not self.image.isNull():
            preferred_width = max(preferred_width, 284)
        max_width = 420 if len(text) > 240 else 344
        width = min(preferred_width, max_width, bounds.width() - 8)
        content_width = max(1, width - 16 - 2 * self.INSET)
        text_height = metrics.boundingRect(QRect(0, 0, content_width, 0), self.TEXT_FLAGS, text).height() if text else 0
        content_height = max(1, bounds.height() - 8 - 24 - 2 * self.INSET)
        self._image_size = QSize(0, 0)
        if not self.image.isNull():
            image_height = min(176, max(1, content_height - text_height - (8 if text else 0)))
            self._image_size = self.image.size().scaled(content_width, image_height, Qt.KeepAspectRatio)
        spacing = 8 if text and not self._image_size.isEmpty() else 0
        height = min(content_height, text_height + self._image_size.height() + spacing)
        self.setFixedSize(width, height + 24 + 2 * self.INSET)

    def _paint_content(self, painter, body, accent, ink):
        content = body.adjusted(self.INSET, self.INSET, -self.INSET, -self.INSET)
        painter.setClipRect(content)
        if not self._image_size.isEmpty():
            image_rect = QRectF(content.center().x() - self._image_size.width() / 2, content.top(),
                                self._image_size.width(), self._image_size.height())
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(image_rect, 9, 9)
            painter.setClipPath(clip)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(image_rect, self.image)
            painter.restore()
            content.setTop(image_rect.bottom() + 8)
        if self.reply.text:
            painter.setFont(self._font)
            painter.setPen(ink)
            painter.drawText(content, self.TEXT_FLAGS, self.reply.text)
