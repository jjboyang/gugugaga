"""A quiet seated tablet gesture using DaFeiYu's illustrated scroll pose."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


HUM_START = 4.45
HUM_LENGTH = 1.78

_SWIPE_LOOP = 11.4
_SWIPES = ((0.16, 14), (2.20, 16), (5.58, 12), (8.02, 14), (8.96, 16))
_CARD_COLORS = ("#bde7f2", "#d3d3fa", "#b8d7fd")


def _ease(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _swipe(elapsed):
    phase = elapsed % _SWIPE_LOOP
    scroll = finger = 0.0
    for start, distance in _SWIPES:
        age = phase - start
        contact = _ease((age - 0.10) / 0.34)
        scroll += distance * contact
        finger += 4 * _ease(age / 0.10) - 16 * contact + 12 * _ease((age - 0.48) / 0.32)
    return scroll, finger


def _hum_strength(elapsed):
    age = elapsed - HUM_START
    return _ease(age / 0.26) * (1 - _ease((age - 1.32) / (HUM_LENGTH - 1.32)))


def apply_pose(head, body, elapsed):
    _, finger = _swipe(elapsed)
    hum = _hum_strength(elapsed)
    sway = math.sin(math.tau * elapsed / 5.2)
    head.angle = head.angle * 0.35 + 1.25 * sway + 1.1 * hum * math.sin(math.tau * elapsed * 1.36)
    head.dy += 1.8 - 0.07 * finger
    body.angle += 0.27 * sway


def deform_hand(vertices, elapsed, grip_weight):
    _, finger = _swipe(elapsed)
    if not finger:
        return vertices
    moved = []
    for point in vertices:
        x, y = point.x(), point.y()
        lift = finger * grip_weight(x, y, 302, 418, 32, 34)
        moved.append(QPointF(x - 0.16 * lift, y + lift))
    return moved


def tablet_texture(artwork, elapsed):
    """Scroll the page inside the illuminated glass; keep the illustrated grip."""
    result = QPixmap(artwork)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    scroll, _ = _swipe(elapsed)
    glass = QPainterPath()
    glass.addRoundedRect(QRectF(210, 393, 63, 48), 5, 5)
    tint = QLinearGradient(210, 393, 273, 441)
    tint.setColorAt(0, QColor("#a2aedb"))
    tint.setColorAt(1, QColor("#818bc5"))
    painter.fillPath(glass, tint)
    painter.setClipPath(glass)
    for index in range(6):
        y = 397 + index * 24 - scroll
        painter.setBrush(QColor(229, 238, 255, 74))
        painter.drawRoundedRect(QRectF(214, y, 55, 19), 4, 4)
        painter.setBrush(QColor(_CARD_COLORS[index % len(_CARD_COLORS)]))
        painter.drawRoundedRect(QRectF(217, y + 3, 15, 13), 3, 3)
        painter.setBrush(QColor(235, 242, 255, 178))
        painter.drawRoundedRect(QRectF(236, y + 5, 26, 3), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(236, y + 11, 19, 2.5), 1.25, 1.25)
    painter.end()
    return result


def paint_hum(painter, elapsed):
    age = elapsed - HUM_START
    if not 0 < age < HUM_LENGTH:
        return
    for beat, x, y, size in ((0, 391, 228, 1.0), (0.49, 423, 204, 0.84), (1.02, 405, 172, 0.93)):
        phase = (age - beat) / 0.72
        if not 0 < phase < 1:
            continue
        painter.save()
        painter.setOpacity(0.84 * _ease(phase / 0.23) * (1 - _ease((phase - 0.38) / 0.62)))
        painter.translate(x + phase * 6, y - phase * 17)
        painter.scale(size, size)
        note = QPainterPath(QPointF(2, 0))
        note.lineTo(2, -17)
        note.cubicTo(3, -12, 11, -13, 9, -7)
        painter.setPen(QPen(QColor("#f3f7ff"), 5.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(note)
        painter.setPen(QPen(QColor("#728bc5"), 2.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(note)
        painter.setPen(QPen(QColor("#f3f7ff"), 1.5))
        painter.setBrush(QColor("#728bc5"))
        painter.drawEllipse(QRectF(-8, -3.5, 11, 7))
        painter.restore()
