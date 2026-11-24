"""A small cutout skeleton renderer for DaFeiYu, using the existing Qt runtime.

The logical AnimationEngine owns phase changes. The animator paints the
layered character and applies bounded desktop movement for its idle walk.
"""
from __future__ import annotations

import time
from pathlib import Path
import math

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
    QRadialGradient, QTransform,
)
from PySide6.QtWidgets import QApplication

from pet.browsing_motion import HUM_START
from pet.rig_motion import NodePose, RigMotion
from pet.rig_mesh import OriginalMeshRenderer
from pet.companion import CallWalk, FaceReaction
from pet.idle_behavior import IdleBehavior, IdleCue
from pet.attention_renderer import AttentionRenderer
from pet.pomodoro_renderer import PomodoroRenderer
from pet.social_gestures import SocialGestures


class RigRenderer(OriginalMeshRenderer):
    """Keep the original artwork and reuse its original blink/book drawings."""

    _WALK_NECK_Y = 375
    _WALK_RISE = 30
    _WALK_SOLE_Y = 487

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
        self._prepare_walk_artwork()
        self._prepare_cover_artwork()

    def _prepare_cover_artwork(self):
        # Use the raised arms and the unobstructed apron from the atlas cheer.
        cheer = self.attention.hop_frame

        def cut(points):
            result = QPixmap(*self.size)
            result.fill(Qt.transparent)
            painter = QPainter(result)
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, cheer)
            painter.end()
            return result

        self._cover_bodice = QPixmap(*self.size)
        self._cover_bodice.fill(Qt.transparent)
        painter = QPainter(self._cover_bodice)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(0, 370, 512, 114), cheer, QRectF(0, 349, 512, 137))
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.translate(255, 401)
        painter.scale(83, 37)
        mask = QRadialGradient(0, 0, 1)
        mask.setColorAt(0.79, Qt.white)
        mask.setColorAt(1.0, Qt.transparent)
        painter.fillRect(QRectF(-4, -12, 8, 16), mask)
        painter.end()
        # Coordinates follow the outlines of the fingers, cuffs and navy sleeves.
        self._cover_arms = [
            (cut([(201, 352), (185, 340), (168, 335), (151, 326), (144, 317),
                  (142, 306), (139, 304), (136, 308), (133, 314), (126, 307),
                  (119, 304), (116, 308), (120, 316), (113, 313), (110, 316),
                  (109, 320), (113, 323), (106, 325), (105, 330), (112, 333),
                  (108, 337), (111, 342), (120, 344), (129, 349), (136, 349),
                  (147, 358), (154, 362), (160, 365), (169, 370), (183, 379),
                  (199, 381), (208, 378)]), -1, 202, 366),
            (cut([(302, 347), (319, 337), (337, 331), (345, 325), (350, 312),
                  (351, 303), (355, 302), (358, 305), (361, 310), (369, 304),
                  (377, 300), (381, 301), (381, 306), (378, 313), (385, 311),
                  (389, 314), (387, 319), (383, 321), (389, 321), (390, 325),
                  (388, 329), (383, 331), (388, 332), (387, 337), (379, 339),
                  (371, 344), (365, 345), (358, 351), (349, 357), (342, 360),
                  (337, 365), (329, 374), (316, 379), (301, 381)]), 1, 305, 365),
        ]

    def _draw_cover(self, painter, pose):
        lift = pose.cover_hands
        painter.save()
        painter.setOpacity(min(1.0, lift * 2))
        painter.drawPixmap(0, 0, self._cover_bodice)
        painter.restore()
        for arm, side, pivot_x, pivot_y in self._cover_arms:
            painter.save()
            painter.setOpacity(min(1.0, lift * 2))
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.translate(pivot_x - side * 8, 397)
            # The near hand drops to the cheek first, exposing one eye.
            peek = pose.peek if side > 0 else 0
            angle = 98 - lift * 37 - peek * 39
            painter.rotate(-side * angle)
            painter.scale(0.90, 0.90)
            painter.drawPixmap(-pivot_x, -pivot_y, arm)
            painter.restore()

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

    def _prepare_walk_artwork(self):
        # Reuse the exact idle head, including its silhouette, and the body
        # beneath the neck of the atlas's original two-feet-down stance.
        width, height = self.size
        neck = self._WALK_NECK_Y
        standing_neck = neck - self._WALK_RISE
        standing = self.attention.angry_frame
        self._seated_body = self.base_pixmap.copy(0, neck, width, height - neck)
        self._standing_body = standing.copy(0, standing_neck, width, height - standing_neck)
        self._walk_head = QPixmap(self.base_pixmap)
        mask = QLinearGradient(0, neck, 0, neck + 10)
        mask.setColorAt(0, Qt.white)
        mask.setColorAt(1, Qt.transparent)
        painter = QPainter(self._walk_head)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.fillRect(self._walk_head.rect(), mask)
        painter.end()
        self._standing_walk = self._walk_texture(1.0)

    def _walk_texture(self, strength):
        texture = QPixmap(*self.size)
        texture.fill(Qt.transparent)
        painter = QPainter(texture)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        rise = self._WALK_RISE * strength
        neck = self._WALK_NECK_Y - rise
        sole = self._WALK_SOLE_Y
        for lower, source_neck, opacity in (
            (self._seated_body, self._WALK_NECK_Y, 1.0 - strength),
            (self._standing_body, self._WALK_NECK_Y - self._WALK_RISE, strength),
        ):
            if opacity > 0:
                # Move both necklines with the same head while keeping the
                # original soles on their shared baseline.
                height = lower.height() * (sole - neck) / (sole - source_neck)
                painter.setOpacity(opacity)
                painter.drawPixmap(QRectF(0, neck, lower.width(), height), lower, QRectF(lower.rect()))
        painter.setOpacity(1)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(QPointF(0, -rise), self._walk_head)
        painter.end()
        return texture

    def _awake_texture(self, pose):
        angry = max(0.0, min(1.0, pose.angry))
        blink = max(0.0, min(1.0, 1.0 - pose.eye_open)) * (1.0 - angry)
        book = pose.nodes.get("book", NodePose(opacity=0)).opacity * (1.0 - angry)
        walk = pose.walk_blend if pose.phase == "idle" and pose.idle_action == "walk" else 0.0
        awake = self.base_pixmap
        if walk > 0:
            awake = self._standing_walk if walk >= 1 else self._walk_texture(walk)
        if blink < 0.0001 and book < 0.0001 and angry < 0.0001 and not pose.cover_hands:
            return awake
        result = QPixmap(awake)
        painter = QPainter(result)
        if angry >= 0.0001:
            painter.setOpacity(angry)
            painter.drawPixmap(0, 0, self._angry_face)
            painter.drawPixmap(0, 0, self._anger_mark)
        if blink >= 0.0001:
            painter.setOpacity(blink)
            painter.drawPixmap(QPointF(0, -self._WALK_RISE * walk), self._closed_eyes)
        if book >= 0.0001:
            painter.setOpacity(max(0.0, min(1.0, book)))
            painter.drawPixmap(0, 0, self._book)
        if pose.cover_hands:
            self._draw_cover(painter, pose)
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

    BROWSING_MIN_SECONDS = 1.35
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
        self.work_mode = False
        self.work_action = None
        self._work_elapsed = 0.0
        self._exploring = False
        self._exploration_elapsed = None
        self._exploration_sound = None
        self._exploration_gesture = None
        self._scroll_direction = 0
        self._pomodoro_elapsed = 0.0
        self._pomodoro_frame = None
        self.idle_behavior = IdleBehavior(walk_mode="nearby")
        self.idle_behavior.enabled = False
        self._walk_origin = None
        self.call = None
        self.face = FaceReaction()
        self.social = SocialGestures(self)
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
        self.cancel_interaction()
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
            self.cancel_interaction()
            self.notify_user_activity()
        self.pomodoro_mode = mode
        self.pomodoro_paused = paused

    def set_work_mode(self, active):
        if active != self.work_mode:
            self.work_mode = active
            self.set_work_action()
            self.cancel_interaction()
            self.notify_user_activity()

    def set_work_action(self, action=None, direction=0):
        if action and self.social.kind == "stretch":
            self.social.clear()
        if (action, direction) != (self.work_action, self._scroll_direction):
            self._work_elapsed = 0.0
        self.work_action = action
        self._scroll_direction = direction

    def set_exploring(self, active):
        if active == self._exploring:
            return
        self._exploring = active
        if active:
            self._exploration_elapsed = 0.0
            if self._exploration_sound is None:
                self._exploration_sound = self._load_exploration_sound()
        else:
            self._stop_exploration_sound()
            if not self.can_show_exploration(browsing=True):
                self._exploration_elapsed = None

    def _load_exploration_sound(self):
        source = self.renderer.asset_dir / "browsing_hum.wav"
        if not source.is_file():
            return None
        try:
            from PySide6.QtMultimedia import QSoundEffect
        except ImportError:
            return None
        sound = QSoundEffect(self)
        sound.setVolume(0.30)
        sound.setSource(QUrl.fromLocalFile(str(source.resolve())))
        return sound

    def _stop_exploration_sound(self):
        if self._exploration_sound is not None and self._exploration_sound.isPlaying():
            self._exploration_sound.stop()

    def _advance_browsing(self, elapsed):
        age = self._exploration_elapsed
        if age is None:
            return None
        visible = elapsed <= IdleBehavior.RESUME_GAP_S and self.can_show_exploration(browsing=True)
        if not visible or (not self._exploring and age >= self.BROWSING_MIN_SECONDS):
            self._stop_exploration_sound()
            if not self._exploring:
                self._exploration_elapsed = None
            return None
        # Advance visible time only. A suspended desktop or another gesture
        # should never skip ahead and start playing the hum on a later frame.
        self._exploration_elapsed = age + min(elapsed, 0.10)
        if self._exploring and age < HUM_START <= self._exploration_elapsed:
            if self._exploration_sound is not None:
                self._exploration_sound.play()
        return self._exploration_elapsed

    def can_show_exploration(self, *, allowed_speech=None, browsing=False):
        if browsing and (self.work_action or self.pomodoro_mode not in {"idle", "focus", "break"}):
            return False
        return (self.enabled and self.engine.current_phase in {"idle", "sleep"}
                and not (self.call or self.face.kind or self.social.kind
                         or getattr(self.window, "_dragging", False)
                         or self._idle_blocked(allowed_speech=allowed_speech, allow_passive_modes=browsing)))

    def start_exploration_gesture(self, action, prompt):
        self.notify_user_activity()
        self._exploration_gesture = (action, prompt, 0.0)

    def _advance_exploration_gesture(self, elapsed):
        if self._exploration_gesture is None:
            return None
        action, prompt, age = self._exploration_gesture
        age += elapsed
        duration = 3.2
        if (age >= duration or self.window._speech_popup is not prompt
                or not self.can_show_exploration(allowed_speech=prompt)):
            self._exploration_gesture = None
            return None
        self._exploration_gesture = (action, prompt, age)
        return IdleCue(action=action, elapsed=age, duration=duration)

    def cancel_interaction(self):
        self._exploration_gesture = None
        self._stop_exploration_sound()
        self.social.clear()
        self.call = None
        self.face.clear()

    def call_over(self):
        if self.enabled:
            self.engine.notify_user_activity()
            self.notify_user_activity()
            self.face.clear()
            self.social.clear()
            self.call = CallWalk()
            self.window.say("鼠标指一下，我就来", "bubbles")

    def touch_face(self, region, side):
        if self.enabled and self.engine.current_phase != "angry":
            self.social.clear()
            if self.face.tap(region, side):
                self.window.say("别吵别吵", "hush")

    def notify_tap(self):
        if self.enabled:
            self.notify_user_activity()
            self.face.clear()
            self.social.clear()
            self.motion.tap()

    def notify_user_activity(self):
        """Freeze any local walk at its current position before handling input."""
        self._exploration_gesture = None
        self.call = None
        self.idle_behavior.notify_activity()
        self.motion.cancel_idle_actions()
        self._walk_origin = None

    def notify_drag_started(self):
        if self.enabled:
            self.notify_user_activity()
            self.face.clear()
            self.social.clear()
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
        if dragging or not self.window.isVisible() or elapsed > IdleBehavior.RESUME_GAP_S:
            self.cancel_interaction()
        if self.social.kind:
            self.social.advance(elapsed, cursor)
        interacting = bool(self.call or self.face.kind or self.social.kind)
        browsing_time = self._advance_browsing(elapsed)
        exploring = browsing_time is not None
        work = self.work_mode and not (dragging or interacting or exploring)
        pomodoro = self.pomodoro_mode != "idle" and not (work or dragging or interacting or exploring)
        paused = pomodoro and self.pomodoro_paused
        if paused and self._pomodoro_frame is not None:
            self.frame_changed.emit(self._pomodoro_frame)
            return
        phase = "dragged" if dragging else "idle" if work or pomodoro or interacting or exploring else self.engine.current_phase or "idle"
        gesture = self._advance_exploration_gesture(elapsed)
        if self.call:
            cue = self.call.advance(elapsed, self.window, cursor)
            if self.call.finished:
                if self.call.nearby:
                    self.window.say("干嘛", "bubbles")
                self.call = None
                self.idle_behavior.notify_activity()
        elif gesture:
            phase, cue = "idle", gesture
        else:
            blocked = interacting or exploring or self._idle_blocked()
            room = self._walk_room() if phase == "idle" and not blocked else None
            cue = self.idle_behavior.step(
                elapsed, phase, blocked=blocked, walk_room=room,
                step_length=IdleBehavior.WALK_STEP_PX * self.window.width() / 140,
            )
            self._apply_idle_walk(cue)
        angle = getattr(self.window, "_sway_angle", 0.0)
        pose = self.motion.step(
            elapsed, phase, drag_angle=angle, pointer=pointer,
            idle_action=cue.action, action_elapsed=cue.elapsed,
            action_duration=cue.duration, walk_cue=cue if cue.action == "walk" else None,
        )
        self.window.face_rise_ratio = pose.walk_blend * self.renderer._WALK_RISE / self.renderer.size[1]
        if self.face.kind:
            self.face.apply(pose, elapsed)
        illustrated = {"bell": "focus_done", "cup": "toast", "clink": "clink", "stretch": "work_stretch"}.get(self.social.kind)
        if illustrated:
            mode, animation_time = illustrated, self.social.age
        elif work:
            mode = {None: "work_idle", "typing": "work_typing", "scroll": "work_scroll"}[self.work_action]
            self._work_elapsed += elapsed
            animation_time = self._work_elapsed
        elif pomodoro:
            mode = self.pomodoro_mode
            if not paused:
                self._pomodoro_elapsed += elapsed
            animation_time = self._pomodoro_elapsed
        elif exploring:
            mode, animation_time = "browsing", browsing_time
        # A 512px logical canvas already covers the maximum 300px window at
        # normal DPI; only render larger when the actual screen needs it.
        scale = min(3.0, max(1.0, self.window.width() * self.window.devicePixelRatioF() / self.renderer.size[0]))
        if illustrated or work or pomodoro or exploring:
            self.pomodoro_renderer.apply_pose(pose, mode, animation_time, paused=paused)
            texture = self.pomodoro_renderer.texture(
                mode, animation_time, eye_open=pose.eye_open,
            )
            pixmap = self.renderer.render(
                pose, scale=scale, texture=texture,
                vertex_deformer=lambda vertices: self.pomodoro_renderer.deform_vertices(
                    vertices, mode, animation_time, scroll_direction=self._scroll_direction,
                ),
            )
            pixmap = self.pomodoro_renderer.paint(
                pixmap, mode, animation_time,
                paused=paused,
                artwork_rendered=True,
            )
            if pomodoro:
                self._pomodoro_frame = QPixmap(pixmap)
        else:
            texture = None
            deformer = None
            if self.social.kind:
                self.social.apply_pose(pose)
                if self.social.kind == "eat":
                    texture = self.social.eating_texture(self.renderer._awake_texture(pose))
                    deformer = self.social.lift_snack
            pixmap = self.renderer.render(pose, scale=scale, texture=texture, vertex_deformer=deformer)
        self.frame_changed.emit(pixmap)

    def _idle_blocked(self, *, allowed_speech=None, allow_passive_modes=False):
        if not allow_passive_modes and (self.work_mode or self.pomodoro_mode != "idle"):
            return True
        if not self.window.isVisible() or getattr(self.window, "_left_down", False):
            return True
        popup = QApplication.activePopupWidget()
        if popup is not None and popup.isVisible():
            return True
        for name in ("_speech_popup", "_question_popup", "_settings_popup"):
            popup = getattr(self.window, name, None)
            try:
                if popup is not None and popup is not allowed_speech and popup.isVisible():
                    return True
            except RuntimeError:
                pass  # A closed Qt popup may already have been destroyed.
        return False

    def _walk_room(self):
        screen = self.window.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            origin = self._walk_origin if self._walk_origin is not None else self.window.pos()
            if bounds.contains(QRect(origin, self.window.size())):
                return origin.x() - bounds.left(), bounds.right() - origin.x() - self.window.width() + 1
        return 0, 0

    def _apply_idle_walk(self, cue):
        if cue.action != "walk":
            # Cancellation freezes in place; never pull the pet away from a
            # click/drag or an incoming work state to an old walking origin.
            self._walk_origin = None
            return
        if self._walk_origin is None:
            self._walk_origin = QPoint(self.window.pos())
        screen = self.window.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            origin = self._walk_origin
            # A manually placed partly off-screen pet still animates, but is
            # not snapped to the screen edge when an automatic gesture starts.
            if bounds.contains(QRect(origin, self.window.size())):
                minimum = bounds.left()
                maximum = bounds.right() - self.window.width() + 1
                target_x = max(minimum, min(maximum, round(origin.x() + cue.offset_x)))
                if self.window.x() != target_x or self.window.y() != origin.y():
                    self.window.move(target_x, origin.y())
        if cue.finished:
            self._walk_origin = None
