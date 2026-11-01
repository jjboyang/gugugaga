"""A small cutout skeleton renderer for DaFeiYu, using the existing Qt runtime.

The logical AnimationEngine owns phase changes. This module only paints the
layered character inside its window; it never changes the desktop position.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPixmap, QRadialGradient

from pet.rig_motion import NodePose, RigMotion
from pet.rig_mesh import OriginalMeshRenderer


class RigRenderer(OriginalMeshRenderer):
    """Keep the original artwork and reuse its original blink/book drawings."""

    def __init__(self, asset_dir):
        super().__init__(asset_dir)
        # These are the character's actual sleeping and suspended poses. The
        # happy closed-eye idle frame below is only a blink, not a sleep pose.
        self._sleeping = self._frame(self.manifest["phases"]["sleep"][0])
        self._dragged = self._frame(self.manifest["phases"]["dragged"][0])
        self._closed_eyes = self._frame(1)
        eye_mask = QPixmap(*self.size)
        eye_mask.fill(Qt.transparent)
        painter = QPainter(eye_mask)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for cx, cy, width, height in ((207, 327, 38, 27), (301, 319, 38, 27)):
            painter.save()
            painter.translate(cx, cy)
            painter.scale(1.0, height / width)
            gradient = QRadialGradient(0, 0, width)
            gradient.setColorAt(0, QColor(255, 255, 255, 255))
            gradient.setColorAt(0.72, QColor(255, 255, 255, 255))
            gradient.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(0, 0), width, width)
            painter.restore()
        painter.end()
        painter = QPainter(self._closed_eyes)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, eye_mask)
        painter.end()

        # Original book and hands sit over the original folded hands. No
        # replacement face, hair, legs, or standing body is introduced.
        self._book = self._frame(self.manifest["phases"]["reading"][0])
        book_mask = QPixmap(*self.size)
        book_mask.fill(Qt.transparent)
        painter = QPainter(book_mask)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath(QPointF(165, 361))
        for x, y in ((210, 357), (256, 376), (303, 357), (342, 361),
                     (349, 416), (326, 433), (318, 444), (257, 451),
                     (195, 444), (187, 431), (162, 417)):
            path.lineTo(x, y)
        path.closeSubpath()
        painter.fillPath(path, Qt.white)
        painter.end()
        painter = QPainter(self._book)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, book_mask)
        painter.end()

    def _frame(self, index):
        source_dir = self.asset_dir.parent
        frame = self.manifest["frames"][index]
        atlas = QPixmap(str(source_dir / self.manifest["image"]))
        result = QPixmap(*self.size)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        width, height = self.manifest["canvas_size"]
        painter.scale(self.size[0] / width, self.size[1] / height)
        painter.translate(width / 2, self.manifest["baseline"])
        painter.scale(self.manifest["scale"], self.manifest["scale"])
        anchor_x, anchor_y = frame["anchor"]
        painter.drawPixmap(QPointF(-anchor_x, -anchor_y), atlas.copy(QRect(*frame["rect"])))
        painter.end()
        return result

    def _awake_texture(self, pose):
        blink = max(0.0, min(1.0, 1.0 - pose.eye_open))
        book = pose.nodes.get("book", NodePose(opacity=0)).opacity
        if blink < 0.0001 and book < 0.0001:
            return self.base_pixmap
        result = QPixmap(self.base_pixmap)
        painter = QPainter(result)
        if blink >= 0.0001:
            painter.setOpacity(blink)
            painter.drawPixmap(0, 0, self._closed_eyes)
        if book >= 0.0001:
            painter.setOpacity(max(0.0, min(1.0, book)))
            painter.drawPixmap(0, 0, self._book)
        painter.end()
        return result

    def _texture_for_pose(self, pose):
        sleeping = max(0.0, min(1.0, getattr(pose, "sleep_blend", 0.0)))
        dragged = max(0.0, min(1.0, getattr(pose, "drag_blend", 0.0)))
        # Select the exact source drawing once a pose settles. In particular,
        # neither the blink's smiling eyes nor a lingering book overlays sleep
        # or dragging. A held pet has priority while waking from sleep.
        if dragged >= 0.995:
            return self._dragged
        if sleeping >= 0.995 and dragged < 0.0001:
            return self._sleeping
        if sleeping < 0.0001 and dragged < 0.0001:
            return self._awake_texture(pose)

        # A short transition keeps the original character artwork intact.
        # Premultiplied additive weighting avoids leaving the idle silhouette
        # underneath transparent regions of the sleeping/suspended drawings.
        result = QPixmap(*self.size)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        for texture, weight in (
            (self.base_pixmap, (1.0 - dragged) * (1.0 - sleeping)),
            (self._sleeping, (1.0 - dragged) * sleeping),
            (self._dragged, dragged),
        ):
            if weight >= 0.0001:
                painter.setOpacity(weight)
                painter.drawPixmap(0, 0, texture)
        painter.end()
        return result


class RigAnimator(QObject):
    """Run smooth visual motion independently of the logical sprite timers."""

    frame_changed = Signal(QPixmap)

    def __init__(self, engine, window, asset_dir, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.window = window
        self.renderer = RigRenderer(asset_dir)
        self.motion = RigMotion()
        self.enabled = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._last_tick = None

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if enabled:
            self.motion.reset(self.engine.current_phase or "idle")
            self._last_tick = time.monotonic()
            self._paint(0.0)
            self.timer.start()
        else:
            self.timer.stop()
            self._last_tick = None

    def stop(self):
        self.set_enabled(False)

    def notify_tap(self):
        if self.enabled:
            self.motion.tap()

    def notify_drag_started(self):
        if self.enabled:
            self.motion.begin_drag()
            self._last_tick = time.monotonic()
            self._paint(0.0)

    def notify_drag_ended(self):
        if self.enabled:
            self.motion.end_drag()
            self._last_tick = time.monotonic()
            self._paint(0.0)

    def notify_drag_motion(self, angle=0.0):
        # Input-driven rendering also works when a busy stream of mouse
        # events delays a timer callback. Bound work on high-rate mice.
        if self.enabled and (self._last_tick is None or time.monotonic() - self._last_tick >= 1 / 90):
            self._tick()

    def _tick(self):
        if not self.enabled:
            return
        now = time.monotonic()
        elapsed = now - self._last_tick if self._last_tick is not None else 0.0
        self._last_tick = now
        self._paint(max(0.0, elapsed))

    def _paint(self, elapsed):
        center = self.window.frameGeometry().center()
        cursor = QCursor.pos()
        # Distant cursors still produce only a small, smoothly damped glance.
        distance = max(150.0, self.window.width() * 2.5)
        pointer = ((cursor.x() - center.x()) / distance, (cursor.y() - center.y()) / distance)
        phase = "dragged" if getattr(self.window, "_dragging", False) else self.engine.current_phase or "idle"
        angle = getattr(self.window, "_sway_angle", 0.0)
        pose = self.motion.step(elapsed, phase, drag_angle=angle, pointer=pointer)
        # A 512px logical canvas already covers the maximum 300px window at
        # normal DPI; only render larger when the actual screen needs it.
        scale = min(3.0, max(1.0, self.window.width() * self.window.devicePixelRatioF() / self.renderer.size[0]))
        self.frame_changed.emit(self.renderer.render(pose, scale=scale))
