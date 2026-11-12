"""A small cutout skeleton renderer for DaFeiYu, using the existing Qt runtime.

The logical AnimationEngine owns phase changes. This module only paints the
layered character inside its window; it never changes the desktop position.
"""
from __future__ import annotations

import time
from pathlib import Path
import math

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
    QRadialGradient, QTransform,
)
from PySide6.QtWidgets import QApplication

from pet.rig_motion import NodePose, RigMotion
from pet.rig_mesh import OriginalMeshRenderer
from pet.idle_behavior import IdleBehavior
from pet.attention_renderer import AttentionRenderer
from pet.pomodoro_renderer import PomodoroRenderer


class RigRenderer(OriginalMeshRenderer):
    """Keep the original artwork and reuse its original blink/book drawings."""

    def __init__(self, asset_dir):
        super().__init__(asset_dir)
        # These are the character's actual sleeping and suspended poses. The
        # happy closed-eye idle frame below is only a blink, not a sleep pose.
        self._sleeping = self._frame(self.manifest["phases"]["sleep"][0])
        self._dragged = self._frame(self.manifest["phases"]["dragged"][0])
        self._pickup_complete = self._dragged
        self._grip_hand = QPixmap(*self.size)
        self._grip_hand.fill(Qt.transparent)
        pickup_path = Path(asset_dir) / self.rig_manifest.get("pickup_image", "pickup.png")
        if pickup_path.exists():
            pickup = QPixmap(str(pickup_path))
            if pickup.isNull():
                raise ValueError(f"Cannot load pickup pose: {pickup_path}")
            self._pickup_complete = pickup.scaled(*self.size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            # The fingers hold still while the character swings below them.
            # A binary mask partitions the source without double alpha edges.
            hand_mask = QPixmap(*self.size)
            hand_mask.fill(Qt.transparent)
            painter = QPainter(hand_mask)
            for points in self.rig_manifest.get("pickup_hand_polygons", []):
                if len(points) < 3:
                    continue
                path = QPainterPath(QPointF(*points[0]))
                for point in points[1:]:
                    path.lineTo(*point)
                path.closeSubpath()
                painter.fillPath(path, Qt.white)
            painter.end()
            self._grip_hand = QPixmap(self._pickup_complete)
            painter = QPainter(self._grip_hand)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, hand_mask)
            painter.end()
            self._dragged = QPixmap(self._pickup_complete)
            painter = QPainter(self._dragged)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            painter.drawPixmap(0, 0, hand_mask)
            painter.end()
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
        self._load_angry_expression()
        self.attention = AttentionRenderer(self._frame, asset_dir, self.manifest)

    def _load_angry_expression(self):
        # The angry atlas frame stands up. Align only its original facial
        # features to the seated face instead of replacing the whole character.
        source = self._frame(self.manifest["phases"]["angry"][0])
        source_left, source_right = (215.23, 306.38), (301.12, 298.81)
        target_left, target_right = (215.58, 336.61), (299.44, 325.69)
        sx, sy = (source_left[0] + source_right[0]) / 2, (source_left[1] + source_right[1]) / 2
        tx, ty = (target_left[0] + target_right[0]) / 2, (target_left[1] + target_right[1]) / 2
        source_angle = math.atan2(source_right[1] - source_left[1], source_right[0] - source_left[0])
        target_angle = math.atan2(target_right[1] - target_left[1], target_right[0] - target_left[0])
        scale = math.dist(target_left, target_right) / math.dist(source_left, source_right)
        transform = QTransform()
        transform.translate(tx, ty)
        transform.rotate(math.degrees(target_angle - source_angle))
        transform.scale(scale, scale)
        transform.translate(-sx, -sy)

        aligned = QPixmap(*self.size)
        aligned.fill(Qt.transparent)
        painter = QPainter(aligned)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setWorldTransform(transform)
        painter.drawPixmap(0, 0, source)
        painter.end()

        mask = QPixmap(*self.size)
        mask.fill(Qt.transparent)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for cx, cy, width, height in ((213, 323, 40, 31), (300, 314, 40, 32), (258, 356, 19, 14)):
            painter.save()
            painter.translate(cx, cy)
            painter.scale(1, height / width)
            gradient = QRadialGradient(0, 0, width)
            gradient.setColorAt(0, QColor(255, 255, 255, 255))
            gradient.setColorAt(0.75, QColor(255, 255, 255, 255))
            gradient.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(0, 0), width, width)
            painter.restore()
        painter.end()
        self._angry_face = aligned
        painter = QPainter(self._angry_face)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, mask)
        painter.end()

        # Isolate the original red anger symbol and its white rim, without
        # bringing a second piece of hair/headband along with it.
        image = source.toImage()
        points = []
        for y in range(128, 209):
            for x in range(65, 145):
                color = image.pixelColor(x, y)
                if color.alpha() > 80 and color.red() > 150 and color.red() > color.green() + 65 and color.red() > color.blue() + 50:
                    points.append(QPointF(x + 0.5, y + 0.5))
        mark_mask = QPixmap(*self.size)
        mark_mask.fill(Qt.transparent)
        painter = QPainter(mark_mask)
        painter.setPen(QPen(Qt.white, 7, Qt.SolidLine, Qt.RoundCap))
        painter.drawPoints(QPolygonF(points))
        painter.end()
        mark = QPixmap(source)
        painter = QPainter(mark)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawPixmap(0, 0, mark_mask)
        painter.end()
        self._anger_mark = QPixmap(*self.size)
        self._anger_mark.fill(Qt.transparent)
        painter = QPainter(self._anger_mark)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setWorldTransform(transform)
        painter.drawPixmap(0, 0, mark)
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

    def render(self, pose, scale=1.0, *, texture=None, vertex_deformer=None):
        result = super().render(pose, scale=scale, texture=texture, vertex_deformer=vertex_deformer)
        if pose.phase == "idle" and pose.idle_action == "knock":
            painter = QPainter(result)
            painter.setOpacity(pose.nodes.get("root", NodePose()).opacity)
            self.attention.overlay(painter, pose)
            painter.end()
        hand_opacity = max(0.0, min(1.0, pose.drag_blend))
        root_opacity = pose.nodes.get("root", NodePose()).opacity
        if hand_opacity * root_opacity > 0.0001:
            painter = QPainter(result)
            painter.setOpacity(hand_opacity * root_opacity)
            painter.drawPixmap(0, 0, self._grip_hand)
            painter.end()
        return result

    def _awake_texture(self, pose):
        angry = max(0.0, min(1.0, pose.angry))
        blink = max(0.0, min(1.0, 1.0 - pose.eye_open)) * (1.0 - angry)
        book = pose.nodes.get("book", NodePose(opacity=0)).opacity * (1.0 - angry)
        if blink < 0.0001 and book < 0.0001 and angry < 0.0001:
            return self.base_pixmap
        result = QPixmap(self.base_pixmap)
        painter = QPainter(result)
        if angry >= 0.0001:
            painter.setOpacity(angry)
            painter.drawPixmap(0, 0, self._angry_face)
            painter.drawPixmap(0, 0, self._anger_mark)
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
            return self.attention.texture(pose, self._awake_texture(pose))

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
        self.pomodoro_renderer = PomodoroRenderer()
        self.pomodoro_mode = "idle"
        self.pomodoro_paused = False
        self.focus_action = None
        self._focus_elapsed = 0.0
        self._scroll_direction = 0
        self._pomodoro_elapsed = 0.0
        self._pomodoro_frame = None
        self.idle_behavior = IdleBehavior(walk_mode="nearby")
        self.idle_behavior.enabled = False
        self._walk_origin = None
        self._last_walk_offset = 0.0
        self._walk_direction = 1
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
        self.idle_behavior.enabled = enabled
        self.notify_user_activity()
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

    def set_pomodoro(self, mode, paused=False):
        """Temporarily own the visual pose; IPC state continues independently."""
        if mode != self.pomodoro_mode:
            self._pomodoro_elapsed = 0.0
            self._pomodoro_frame = None
        if (mode, paused) != (self.pomodoro_mode, self.pomodoro_paused):
            self.notify_user_activity()
        self.pomodoro_mode = mode
        self.pomodoro_paused = paused

    def set_focus_action(self, action=None, direction=0):
        if (action, direction) != (self.focus_action, self._scroll_direction):
            self._focus_elapsed = 0.0
        self.focus_action = action
        self._scroll_direction = direction

    def notify_tap(self):
        if self.enabled:
            self.notify_user_activity()
            self.motion.tap()

    def notify_user_activity(self):
        """Freeze any local walk at its current position before handling input."""
        self.idle_behavior.notify_activity()
        self.motion.cancel_idle_actions()
        self._walk_origin = None
        self._last_walk_offset = 0.0

    def notify_drag_started(self):
        if self.enabled:
            self.notify_user_activity()
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
        if self.enabled:
            self.motion.note_drag_motion(angle)
            if self._last_tick is None or time.monotonic() - self._last_tick >= 1 / 90:
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
        dragging = getattr(self.window, "_dragging", False) or self.engine.current_phase == "dragged"
        pomodoro = self.pomodoro_mode != "idle" and not dragging
        if pomodoro and self.pomodoro_paused and self._pomodoro_frame is not None:
            self.frame_changed.emit(self._pomodoro_frame)
            return
        phase = "dragged" if dragging else "idle" if pomodoro else self.engine.current_phase or "idle"
        cue = self.idle_behavior.step(elapsed, phase, blocked=self._idle_blocked())
        self._apply_idle_walk(cue)
        angle = getattr(self.window, "_sway_angle", 0.0)
        pose = self.motion.step(
            elapsed, phase, drag_angle=angle, pointer=pointer,
            idle_action=cue.action, action_elapsed=cue.elapsed,
            action_duration=cue.duration,
        )
        pose.walk_direction = self._walk_direction
        if pomodoro:
            mode = self.pomodoro_mode
            if not self.pomodoro_paused:
                self._pomodoro_elapsed += elapsed
                self._focus_elapsed += elapsed
            animation_time = self._pomodoro_elapsed
            if self.focus_action and mode in {"focus", "activity"}:
                mode = "focus_scroll" if self.focus_action == "scroll" else "focus"
                animation_time = self._focus_elapsed
            elif mode == "focus":
                mode = "focus_wait"
            self.pomodoro_renderer.apply_pose(pose, mode, animation_time, paused=self.pomodoro_paused)
        # A 512px logical canvas already covers the maximum 300px window at
        # normal DPI; only render larger when the actual screen needs it.
        scale = min(3.0, max(1.0, self.window.width() * self.window.devicePixelRatioF() / self.renderer.size[0]))
        if pomodoro:
            texture = self.pomodoro_renderer.texture(
                mode, animation_time, eye_open=pose.eye_open,
            )
            pixmap = self.renderer.render(
                pose, scale=scale, texture=texture,
                vertex_deformer=lambda vertices: self.pomodoro_renderer.deform_vertices(
                    vertices, mode, animation_time, scroll_direction=self._scroll_direction,
                ),
            )
        else:
            pixmap = self.renderer.render(pose, scale=scale)
        if pomodoro:
            pixmap = self.pomodoro_renderer.paint(
                pixmap, mode, animation_time,
                paused=self.pomodoro_paused,
                artwork_rendered=True,
            )
            self._pomodoro_frame = QPixmap(pixmap)
        self.frame_changed.emit(pixmap)

    def _idle_blocked(self):
        if self.pomodoro_mode != "idle":
            return True
        if not self.window.isVisible() or getattr(self.window, "_left_down", False):
            return True
        popup = QApplication.activePopupWidget()
        if popup is not None and popup.isVisible():
            return True
        for name in ("_speech_popup", "_question_popup", "_settings_popup"):
            popup = getattr(self.window, name, None)
            try:
                if popup is not None and popup.isVisible():
                    return True
            except RuntimeError:
                pass  # A closed Qt popup may already have been destroyed.
        return False

    def _apply_idle_walk(self, cue):
        if cue.action != "walk":
            # Cancellation freezes in place; never pull the pet away from a
            # click/drag or an incoming work state to an old walking origin.
            self._walk_origin = None
            self._last_walk_offset = 0.0
            return
        if self._walk_origin is None:
            self._walk_origin = QPoint(self.window.pos())
            self._last_walk_offset = 0.0
        change = cue.offset_x - self._last_walk_offset
        if abs(change) > 0.01:
            self._walk_direction = 1 if change > 0 else -1
        self._last_walk_offset = cue.offset_x
        screen = self.window.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            origin = self._walk_origin
            # A manually placed partly off-screen pet still animates, but is
            # not snapped to the screen edge when an automatic gesture starts.
            if bounds.contains(QRect(origin, self.window.size())):
                minimum = max(bounds.left(), origin.x() - 80)
                maximum = min(bounds.right() - self.window.width() + 1, origin.x() + 80)
                target_x = max(minimum, min(maximum, round(origin.x() + cue.offset_x)))
                if self.window.x() != target_x or self.window.y() != origin.y():
                    self.window.move(target_x, origin.y())
        if cue.finished:
            self._walk_origin = None
            self._last_walk_offset = 0.0
