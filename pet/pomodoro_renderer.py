"""Small animated Pomodoro props over DaFeiYu's unchanged original artwork.

All positions use the existing 512px rig canvas.  The only alternate character
drawing is the original atlas's arms-up celebration, reused for stretching.
No timer, logical state, desktop movement, or image generation lives here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)

from pet.rig_motion import NodePose


_INK = QColor("#243753")
_CREAM = QColor("#fff5dd")
_CORAL = QColor("#ee7868")


class PomodoroRenderer:
    """Add reversible time-driven props, preserving size, alpha and DPI.

    Call ``apply_pose`` on a fresh RigPose before its normal rig render, then
    pass that pixmap to ``paint``.  ``elapsed`` is seconds since the mode began.
    A paused mode holds its props and hands still.  Skip both calls while the
    user is dragging, so the existing picked-up animation keeps priority.
    """

    MODES = frozenset(("idle", "focus", "focus_done", "break", "break_done", "activity"))

    def __init__(self, asset_dir=None):
        self.asset_dir = Path(asset_dir) if asset_dir else Path(__file__).parent / "characters" / "dafeiyu"
        self._stretch_pixmap = None

    @staticmethod
    def _time(elapsed, paused):
        value = float(elapsed)
        return 0.0 if paused or not math.isfinite(value) else max(0.0, value)

    @staticmethod
    def _stretching(mode, t):
        return mode in ("break_done", "activity") or (mode == "break" and t % 16 >= 11)

    def apply_pose(self, pose, mode, elapsed, *, paused=False):
        """Adjust only the supplied fresh pose; return it for convenient use."""
        if mode not in self.MODES or mode == "idle":
            return pose
        t = self._time(elapsed, paused)
        pose.sleep_blend = pose.drag_blend = pose.suspension = 0.0
        pose.angry = pose.anger_action = 0.0
        pose.knock_blend = pose.knock_impact = pose.walk_blend = pose.hop_blend = 0.0
        pose.idle_action = ""
        pose.nodes["book"] = NodePose(opacity=0)
        left = pose.nodes.setdefault("arm_left", NodePose())
        right = pose.nodes.setdefault("arm_right", NodePose())
        head = pose.nodes.setdefault("head", NodePose())
        if mode == "focus":
            tap = 0.0 if paused else math.sin(t * 15)
            left.dy += 3.5 * tap
            right.dy -= 3.5 * tap
            left.angle -= 5
            right.angle += 5
            head.dy += 1.8
            pose.gaze_x, pose.gaze_y = 0.0, 0.65
        elif mode == "focus_done":
            ring = 0.0 if paused else math.sin(t * 9)
            right.dx += 21
            right.dy -= 11 + 5 * ring
            right.angle -= 15 + 10 * ring
        elif mode == "break" and not self._stretching(mode, t):
            sip = self._sip(t)
            right.dy -= 35 * sip
            right.dx -= 6 * sip
            right.angle -= 13 * sip
            head.angle -= 3 * sip
        return pose

    def _stretch(self):
        if self._stretch_pixmap is None:
            manifest = json.loads((self.asset_dir / "atlas.json").read_text("utf-8"))
            frame = manifest["frames"][manifest["phases"]["done"][0]]
            atlas = QPixmap(str(self.asset_dir / manifest["image"]))
            if atlas.isNull():
                return None
            pixmap = QPixmap(512, 512)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            width, height = manifest["canvas_size"]
            painter.scale(512 / width, 512 / height)
            painter.translate(width / 2, manifest["baseline"])
            painter.scale(manifest["scale"], manifest["scale"])
            painter.drawPixmap(QPointF(-frame["anchor"][0], -frame["anchor"][1]), atlas.copy(QRect(*frame["rect"])))
            painter.end()
            self._stretch_pixmap = pixmap
        return self._stretch_pixmap

    def paint(self, pixmap, mode, elapsed, *, paused=False):
        """Return a new pixmap; the caller's original image is never mutated."""
        if pixmap.isNull() or mode not in self.MODES or mode == "idle":
            return QPixmap(pixmap)
        t = self._time(elapsed, paused)
        stretch = self._stretching(mode, t)
        result = QPixmap(pixmap.size())
        result.setDevicePixelRatio(pixmap.devicePixelRatio())
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        dpr = result.devicePixelRatio()
        painter.scale(result.width() / dpr / 512, result.height() / dpr / 512)
        original = self._stretch() if stretch else None
        if original is not None:
            # This is the character's original arms-up pose, not a replacement
            # face/body. A slow rise/fall makes the stretch visibly breathe.
            lift = 0 if paused else (1 - math.cos(t * 2)) * 2
            painter.save()
            painter.translate(256, 475)
            painter.scale(1.0, 1 + lift / 220)
            painter.translate(-256, -475)
            painter.drawPixmap(QRectF(0, 0, 512, 512), original, QRectF(original.rect()))
            painter.restore()
        else:
            painter.drawPixmap(QRectF(0, 0, 512, 512), pixmap, QRectF(pixmap.rect()))
        if mode == "focus":
            self._hat(painter, t, paused)
            self._keyboard(painter, t, paused)
        elif mode == "focus_done":
            self._bell(painter, t, paused)
        elif mode == "break" and not stretch:
            self._coffee(painter, t, paused)
        elif stretch:
            self._stretch_marks(painter, t, paused)
        painter.end()
        return result

    @staticmethod
    def _sip(t):
        # Gently lift, hold near the mouth, and lower once per 8 seconds.
        phase = t % 8
        if phase < 2:
            return 0.0
        if phase < 3.4:
            return (1 - math.cos(math.pi * (phase - 2) / 1.4)) / 2
        if phase < 4.4:
            return 1.0
        if phase < 5.8:
            return (1 + math.cos(math.pi * (phase - 4.4) / 1.4)) / 2
        return 0.0

    @staticmethod
    def _hat(p, t, paused):
        # One quick settling movement reads as putting the work cap on.
        settle = 0 if paused else max(0, 1 - t / 0.8) ** 2 * 28
        p.save()
        p.translate(0, -settle)
        p.setPen(QPen(_INK, 4))
        p.setBrush(QColor("#719ab9"))
        crown = QPainterPath(QPointF(177, 189))
        crown.cubicTo(178, 117, 329, 112, 335, 189)
        crown.closeSubpath()
        p.drawPath(crown)
        p.setBrush(QColor("#d8e8ef"))
        p.drawRoundedRect(QRectF(165, 182, 182, 22), 9, 9)
        p.setBrush(_CORAL)
        p.setPen(QPen(_INK, 2))
        p.drawEllipse(QRectF(246, 153, 23, 22))
        p.setPen(QPen(QColor("#4d795d"), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(257, 155), QPointF(260, 148))
        p.restore()

    @staticmethod
    def _keyboard(p, t, paused):
        p.save()
        p.setPen(QPen(_INK, 3))
        p.setBrush(QColor("#a8becd"))
        p.drawRoundedRect(QRectF(169, 411, 174, 43), 8, 8)
        p.setBrush(QColor("#dfeaf0"))
        active = -1 if paused else int(t * 8) % 24
        for row in range(3):
            for col in range(8):
                p.setBrush(_CORAL if row * 8 + col == active else QColor("#eaf3f8"))
                p.setPen(QPen(QColor("#7093aa"), 1))
                p.drawRoundedRect(QRectF(179 + col * 19, 418 + row * 9, 15, 6), 2, 2)
        # Contact flicks stay below the original hands.
        if not paused:
            p.setPen(QPen(_CREAM, 3, Qt.SolidLine, Qt.RoundCap))
            x = 220 if math.sin(t * 15) > 0 else 287
            p.drawLine(QPointF(x - 3, 403), QPointF(x - 6, 397))
            p.drawLine(QPointF(x + 4, 403), QPointF(x + 7, 397))
        p.restore()

    @staticmethod
    def _bell(p, t, paused):
        swing = 0 if paused else math.sin(t * 9)
        p.save()
        p.translate(365, 380)
        p.rotate(swing * 11)
        p.setPen(QPen(_INK, 3))
        p.setBrush(QColor("#edb650"))
        bell = QPainterPath(QPointF(-25, 23))
        bell.cubicTo(-17, 15, -20, -15, 0, -17)
        bell.cubicTo(20, -15, 17, 15, 25, 23)
        bell.closeSubpath()
        p.drawPath(bell)
        p.setBrush(QColor("#fff0ae"))
        p.drawRoundedRect(QRectF(-28, 20, 56, 8), 4, 4)
        p.drawEllipse(QRectF(-5, -24, 10, 10))
        p.setBrush(_INK)
        p.drawEllipse(QRectF(-4 + swing * 5, 27, 8, 8))
        p.restore()
        # The right hand swings a little mallet toward the bell.
        p.save()
        p.setPen(QPen(QColor("#a66a46"), 6, Qt.SolidLine, Qt.RoundCap))
        strike_y = 378 - swing * 9
        p.drawLine(QPointF(304, 393), QPointF(338, strike_y))
        p.setPen(QPen(_INK, 2))
        p.setBrush(QColor("#eacb91"))
        p.drawRoundedRect(QRectF(331, strike_y - 10, 13, 19), 4, 4)
        if not paused:
            p.setPen(QPen(QColor("#e8b64f"), 3, Qt.SolidLine, Qt.RoundCap))
            for side in (-1, 1):
                x = 365 + side * 37
                pulse = 2 + abs(swing) * 5
                p.drawLine(QPointF(x, 365), QPointF(x + side * pulse, 359))
                p.drawLine(QPointF(x, 378), QPointF(x + side * pulse, 378))
        p.restore()

    @classmethod
    def _coffee(cls, p, t, paused):
        sip = cls._sip(t)
        p.save()
        p.translate(282 - sip * 14, 389 - sip * 34)
        p.rotate(-sip * 12)
        p.setPen(QPen(_INK, 3))
        p.setBrush(_CREAM)
        p.drawEllipse(QRectF(22, -2, 18, 22))
        p.drawRoundedRect(QRectF(-17, -9, 44, 35), 7, 7)
        p.setBrush(QColor("#815641"))
        p.drawEllipse(QRectF(-14, -13, 38, 10))
        p.setPen(QPen(_CORAL, 3))
        p.drawArc(QRectF(-5, 1, 16, 12), 180 * 16, 180 * 16)
        # Visible moving steam; each wisp fades as it rises.
        for index in range(3):
            phase = ((t * 0.35 + index / 3) % 1) if not paused else index / 3
            p.setPen(QPen(QColor(255, 244, 220, int(170 * (1 - phase))), 3, Qt.SolidLine, Qt.RoundCap))
            x, y = -8 + index * 12, -20 - phase * 29
            steam = QPainterPath(QPointF(x, y))
            steam.cubicTo(x - 6, y - 4, x + 6, y - 10, x, y - 15)
            p.drawPath(steam)
        p.restore()

    @staticmethod
    def _stretch_marks(p, t, paused):
        pulse = 0.5 if paused else (1 + math.sin(t * 2)) / 2
        p.save()
        p.setPen(QPen(QColor("#c4dfd0"), 4, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            x = 256 + side * (138 + pulse * 4)
            p.drawLine(QPointF(x, 320), QPointF(x + side * 10, 310))
            p.drawLine(QPointF(x + side * 4, 339), QPointF(x + side * 16, 339))
        p.restore()
