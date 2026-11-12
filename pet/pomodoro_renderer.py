"""Illustrated Pomodoro poses, skinned with the character's existing mesh.

Hands and props are painted together in the source art. Small local mesh
movements keep the cup/bell attached to the grip; only steam and sound accents
are drawn procedurally. All coordinates use the existing 512px rig canvas.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from pet.rig_motion import NodePose


def _smooth(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class PomodoroRenderer:
    """Select complete art before skinning and add restrained accents after it.

    ``texture`` and ``deform_vertices`` feed the regular character renderer.
    ``paint`` then adds only the subtle accents. It can also draw a static art
    preview when ``artwork_rendered`` is false. No timer or desktop state lives
    here, and dragging bypasses this renderer completely.
    """

    MODES = frozenset(("idle", "focus", "focus_wait", "focus_scroll", "focus_done", "break", "break_done", "activity"))

    def __init__(self, asset_dir=None):
        self.asset_dir = Path(asset_dir) if asset_dir else Path(__file__).parent / "characters" / "dafeiyu"
        self._textures = {}
        self._blink_layers = {}
        self._manifest = None
        self._atlas = None

    @staticmethod
    def _time(elapsed, paused=False):
        value = float(elapsed)
        return 0.0 if not math.isfinite(value) else max(0.0, value)

    @staticmethod
    def _stretch_weight(mode, t):
        if mode in ("break_done", "activity"):
            return 1.0
        if mode != "break":
            return 0.0
        phase = t % 16
        # Settle into and out of a stretch rather than changing drawings in a
        # single frame. No celebratory stars or abrupt big arm movement.
        return _smooth((phase - 10.6) / 0.8) * (1 - _smooth((phase - 14.8) / 1.2))

    @classmethod
    def _stretching(cls, mode, t):
        return cls._stretch_weight(mode, t) >= 0.5

    def _frame(self, phase):
        if self._manifest is None:
            self._manifest = json.loads((self.asset_dir / "atlas.json").read_text("utf-8"))
            self._atlas = QPixmap(str(self.asset_dir / self._manifest["image"]))
            if self._atlas.isNull():
                raise ValueError("Cannot load DaFeiYu's original Pomodoro artwork")
        manifest = self._manifest
        frame = manifest["frames"][manifest["phases"][phase][0]]
        pixmap = QPixmap(512, 512)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        width, height = manifest["canvas_size"]
        painter.scale(512 / width, 512 / height)
        painter.translate(width / 2, manifest["baseline"])
        painter.scale(manifest["scale"], manifest["scale"])
        painter.drawPixmap(QPointF(-frame["anchor"][0], -frame["anchor"][1]), self._atlas.copy(QRect(*frame["rect"])))
        painter.end()
        return pixmap

    def _artwork(self, name):
        if name not in self._textures:
            # Complete illustrated hands/props share the character texture.
            # Older asset packs can still run using their original atlas poses.
            path = self.asset_dir / "pomodoro" / f"{name}.png"
            image = QPixmap(str(path)) if path.is_file() else QPixmap()
            if image.isNull():
                image = self._frame({
                    "focus": "writing", "scroll": "writing", "coffee": "idle", "bell": "done", "stretch": "done",
                }[name])
            elif image.size().width() != 512 or image.size().height() != 512:
                raise ValueError(f"Pomodoro artwork must use a 512px square canvas: {path}")
            self._textures[name] = image
        return self._textures[name]

    def _stretch(self):
        return self._artwork("stretch")

    def _with_blink(self, image, name, eye_open):
        """Reuse the new stretch drawing's own closed eyes, never draw new ones."""
        opacity = 1 - max(0.0, min(1.0, eye_open))
        if opacity < 0.001:
            return image
        if name not in self._blink_layers:
            # New poses share the same head proportions. Small per-pose offsets
            # align the eyelids; the feathered skin patches leave bangs intact.
            dx, dy = {"focus": (0, 0), "scroll": (0, 3), "coffee": (0, 0), "bell": (0, -2)}[name]
            layer = QPixmap(512, 512)
            layer.fill(Qt.transparent)
            p = QPainter(layer)
            p.drawPixmap(dx, dy, self._stretch())
            p.end()
            mask = QPixmap(512, 512)
            mask.fill(Qt.transparent)
            p = QPainter(mask)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            for x, y in ((211 + dx, 325 + dy), (301 + dx, 316 + dy)):
                p.save()
                p.translate(x, y)
                p.scale(1, 0.72)
                gradient = QRadialGradient(0, 0, 37)
                gradient.setColorAt(0, Qt.white)
                gradient.setColorAt(0.75, Qt.white)
                gradient.setColorAt(1, Qt.transparent)
                p.setBrush(gradient)
                p.drawEllipse(QPointF(0, 0), 37, 37)
                p.restore()
            p.end()
            p = QPainter(layer)
            p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            p.drawPixmap(0, 0, mask)
            p.end()
            self._blink_layers[name] = layer
        result = QPixmap(image)
        p = QPainter(result)
        p.setOpacity(opacity)
        p.drawPixmap(0, 0, self._blink_layers[name])
        p.end()
        return result

    def texture(self, mode, elapsed, *, paused=False, eye_open=1.0):
        """Return the illustrated bind texture, or None for normal rig art."""
        if mode not in self.MODES or mode == "idle":
            return None
        t = self._time(elapsed)
        if mode in {"focus", "focus_wait", "focus_scroll"}:
            name = "scroll" if mode == "focus_scroll" else "focus"
            return self._with_blink(self._artwork(name), name, eye_open)
        if mode == "focus_done":
            return self._with_blink(self._artwork("bell"), "bell", eye_open)
        weight = self._stretch_weight(mode, t)
        if weight >= 1:
            return self._stretch()
        coffee = self._with_blink(self._artwork("coffee"), "coffee", eye_open)
        if weight <= 0:
            return coffee
        # Premultiplied additive blending avoids dark fringes or a doubled
        # opaque face while the two similarly aligned drawings crossfade.
        result = QPixmap(512, 512)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        for art, opacity in ((coffee, 1 - weight), (self._stretch(), weight)):
            painter.setOpacity(opacity)
            painter.drawPixmap(0, 0, art)
        painter.end()
        return result

    @staticmethod
    def _sip(t):
        # A small, unhurried hand lift with a rest between each movement.
        phase = t % 10
        return _smooth((phase - 2) / 1.8) * (1 - _smooth((phase - 5.2) / 1.8))

    @staticmethod
    def _ring(t):
        # Two gentle wrist movements, then a long pause. Continuous frantic
        # shaking is distracting while waiting for the next timer action.
        phase = t % 6
        envelope = _smooth(phase / 0.2) * (1 - _smooth((phase - 1.5) / 0.6))
        return math.sin(phase * 11) * envelope

    def apply_pose(self, pose, mode, elapsed, *, paused=False):
        if mode not in self.MODES or mode == "idle":
            return pose
        t = self._time(elapsed)
        pose.sleep_blend = pose.drag_blend = pose.suspension = 0.0
        pose.angry = pose.anger_action = 0.0
        pose.knock_blend = pose.knock_impact = pose.walk_blend = pose.hop_blend = 0.0
        pose.idle_action = ""
        pose.nodes["book"] = NodePose(opacity=0)
        left = pose.nodes.setdefault("arm_left", NodePose())
        right = pose.nodes.setdefault("arm_right", NodePose())
        head = pose.nodes.setdefault("head", NodePose())
        if mode in {"focus", "focus_scroll"}:
            if mode == "focus" and not paused:
                tap = math.sin(t * 20)
                left.dy += 1.4 * tap
                right.dy -= 1.4 * tap
            head.dy += 1.0
            head.angle *= 0.45
            pose.gaze_x, pose.gaze_y = 0.0, 0.45
        elif mode == "focus_done":
            head.angle *= 0.6
        elif mode == "break":
            sip = self._sip(t) * (1 - self._stretch_weight(mode, t))
            head.angle -= 1.1 * sip
            head.dy += 0.6 * sip
        return pose

    def deform_vertices(self, vertices, mode, elapsed, *, paused=False, scroll_direction=1):
        """Move each grip and its prop as one connected, smoothly weighted area.

        Apply after regular skinning, so the grip follows breathing first.
        The taper goes to zero outside each local area, avoiding cutout seams.
        """
        t = self._time(elapsed)
        if mode == "focus":
            tap = math.sin(t * 20) * 8
            return [QPointF(p.x(), p.y() + tap * (
                self._grip_weight(p.x(), p.y(), 174, 416, 24, 23)
                - self._grip_weight(p.x(), p.y(), 309, 415, 24, 23)
            )) for p in vertices]
        if mode == "focus_scroll":
            phase = t % 0.68
            swipe = _smooth(phase / 0.26) * (1 - _smooth((phase - 0.30) / 0.35))
            distance = -scroll_direction * 23 * swipe
            return [QPointF(p.x(), p.y() + distance * self._grip_weight(
                p.x(), p.y(), 299, 420, 32, 36,
            )) for p in vertices]
        if mode == "focus_done":
            angle = math.radians(self._ring(t) * 7)
            cx, cy, rx, ry = 326.0, 381.0, 38.0, 65.0
        elif mode == "break":
            lift = self._sip(t) * (1 - self._stretch_weight(mode, t)) * 13
            cx, cy, rx, ry = 258.0, 400.0, 61.0, 40.0
        else:
            return vertices
        result = []
        for point in vertices:
            x, y = point.x(), point.y()
            weight = self._grip_weight(x, y, cx, cy, rx, ry)
            if mode == "focus_done":
                dx, dy = x - cx, y - cy
                rotated_x = cx + dx * math.cos(angle) - dy * math.sin(angle)
                rotated_y = cy + dx * math.sin(angle) + dy * math.cos(angle)
                result.append(QPointF(x + (rotated_x - x) * weight, y + (rotated_y - y) * weight))
            else:
                result.append(QPointF(x, y - lift * weight))
        return result

    @staticmethod
    def _grip_weight(x, y, cx, cy, rx, ry):
        radius = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
        return 1 - _smooth((radius - 0.25) / 0.75)

    def paint(self, pixmap, mode, elapsed, *, paused=False, artwork_rendered=False):
        """Add soft accents while preserving the input's canvas, DPI and alpha."""
        if pixmap.isNull() or mode not in self.MODES or mode == "idle":
            return QPixmap(pixmap)
        t = self._time(elapsed)
        result = QPixmap(pixmap.size())
        result.setDevicePixelRatio(pixmap.devicePixelRatio())
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        dpr = result.devicePixelRatio()
        painter.scale(result.width() / dpr / 512, result.height() / dpr / 512)
        source = pixmap if artwork_rendered else self.texture(mode, t, paused=paused)
        painter.drawPixmap(QRectF(0, 0, 512, 512), source, QRectF(0, 0, source.width(), source.height()))
        if mode == "break":
            weight = 1 - self._stretch_weight(mode, t)
            if weight > 0:
                self._steam(painter, t, weight)
        elif mode == "focus_done":
            self._chime(painter, t)
        painter.end()
        return result

    def _steam(self, p, t, opacity):
        # Fine desaturated blue-white wisps read on light and dark desktops.
        # Keep them below the mouth and away from the character's eyes.
        lift = self._sip(t) * opacity * 13
        p.save()
        p.setOpacity(opacity)
        for index in range(2):
            phase = (t * 0.32 + index * 0.5) % 1
            alpha = int(95 * math.sin(math.pi * phase))
            x = 249 + index * 15
            y = 383 - lift - phase * 14
            steam = QPainterPath(QPointF(x, y))
            steam.cubicTo(x - 3, y - 3, x + 4, y - 6, x + 1, y - 10)
            p.setPen(QPen(QColor(185, 212, 229, alpha), 1.6, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(steam)
        p.restore()

    def _chime(self, p, t):
        strength = abs(self._ring(t))
        if strength < 0.08:
            return
        p.save()
        p.setPen(QPen(QColor(224, 185, 107, int(strength * 150)), 1.8, Qt.SolidLine, Qt.RoundCap))
        for side in (-1, 1):
            x = 326 + side * (31 + strength * 2)
            path = QPainterPath(QPointF(x, 403))
            path.quadTo(x + side * 6, 411, x, 419)
            p.drawPath(path)
        p.restore()
