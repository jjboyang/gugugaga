"""Artwork selection for small, interruptible idle attention gestures.

The logical state machine and the motion controller stay outside this helper.
It only selects existing character artwork, an optional screen-knocking pose,
and a subtle contact ripple. It never opens a window or moves the desktop pet.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform


def _unit(value):
    value = float(value)
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


class AttentionRenderer:
    """Compose gesture textures on a 512px logical character canvas.

    ``frame_loader`` is the rig's existing atlas-frame loader. ``manifest`` is
    the atlas manifest, while optional knocking metadata is read from the rig's
    own manifest. A newly supplied knock.png is picked up lazily for previews.
    """

    def __init__(self, frame_loader, asset_dir, manifest):
        self.asset_dir = Path(asset_dir)
        self.manifest = manifest
        phases = manifest["phases"]
        walk_path = self.asset_dir / "walk.png"
        self.authored_walk = walk_path.is_file()
        if self.authored_walk:
            walk = QPixmap(str(walk_path))
            if (walk.width(), walk.height()) != (2048, 1024):
                raise ValueError(f"Walking artwork must contain eight 512px frames: {walk_path}")
            self.walk_frames = [walk.copy(QRect(column * 512, row * 512, 512, 512))
                                for row in range(2) for column in range(4)]
        else:
            self.walk_frames = [frame_loader(index) for index in dict.fromkeys(phases["waddle"])]
        self._walk_mirrors = [frame.transformed(QTransform().scale(-1, 1))
                              for frame in self.walk_frames]
        self.hop_frame = frame_loader(phases["done"][0])
        self.angry_frame = frame_loader(phases["angry"][0])
        done = phases["done"]
        self._knock_fallback = frame_loader(done[min(1, len(done) - 1)])
        self.knock_frame = self._knock_fallback
        self.knock_contact = QPointF(338.0, 318.0)
        self._knock_stamp = None
        self._load_knock()

    def _load_knock(self):
        image_path = self.asset_dir / "knock.png"
        config_path = self.asset_dir / "manifest.json"
        stamp = tuple(path.stat().st_mtime_ns if path.exists() else None
                      for path in (image_path, config_path))
        if stamp == self._knock_stamp:
            return
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"Cannot load attention gesture metadata: {config_path}") from exc
        contact = config.get("knock_contact", [338.0, 318.0])
        if (len(contact) != 2 or any(not math.isfinite(float(v)) for v in contact)
                or any(not 0 <= float(v) <= 512 for v in contact)):
            raise ValueError("knock_contact must lie inside the 512px canvas")
        self.knock_contact = QPointF(float(contact[0]), float(contact[1]))
        if image_path.exists():
            source = QPixmap(str(image_path))
            if source.isNull():
                raise ValueError(f"Cannot load screen-knocking pose: {image_path}")
            scaled = source.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.knock_frame = QPixmap(512, 512)
            self.knock_frame.fill(Qt.transparent)
            painter = QPainter(self.knock_frame)
            painter.drawPixmap((512 - scaled.width()) // 2,
                               (512 - scaled.height()) // 2, scaled)
            painter.end()
        else:
            self.knock_frame = self._knock_fallback
        self._knock_stamp = stamp

    @staticmethod
    def _mix(awake, gesture, strength):
        strength = _unit(strength)
        if strength <= 0.0001:
            return awake
        if strength >= 0.995:
            return QPixmap(gesture)
        # Only the short pose entrance/exit mixes silhouettes. Full gestures
        # use their exact source pixels rather than retaining an idle ghost.
        result = QPixmap(512, 512)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setOpacity(1.0 - strength)
        painter.drawPixmap(0, 0, awake)
        painter.setOpacity(strength)
        painter.drawPixmap(0, 0, gesture)
        painter.end()
        return result

    def texture(self, pose, awake):
        """Return gesture artwork only while its logical phase allows it."""
        phase = getattr(pose, "phase", "idle")
        if phase == "angry":
            return self._mix(awake, self.angry_frame,
                             getattr(pose, "anger_action", 0.0))
        if phase != "idle":
            return awake

        action = getattr(pose, "idle_action", "")
        if action == "walk":
            return self._mix(awake, self._walk_frame(pose), pose.walk_blend)
        if action == "hop":
            return self._mix(awake, self.hop_frame, getattr(pose, "hop_blend", 0.0))
        if action == "knock":
            self._load_knock()
            return self._mix(awake, self.knock_frame, getattr(pose, "knock_blend", 0.0))
        return awake

    def _walk_frame(self, pose):
        cycle = pose.walk_cycle if pose.walk_cycle is not None else pose.action_elapsed * 1.4
        frames = self._walk_mirrors if pose.walk_direction < 0 else self.walk_frames
        frame = frames[int((cycle % 1.0) * len(frames))]
        if not 0 < pose.walk_turn < 1:
            return frame
        # Briefly show a narrower profile as the character pivots in place.
        result = QPixmap(512, 512)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(256, 0)
        painter.scale(1 - 0.18 * math.sin(math.pi * pose.walk_turn), 1)
        painter.drawPixmap(-256, 0, frame)
        painter.end()
        return result

    def overlay(self, painter, pose):
        """Draw brief, quiet contact rings after the character mesh is painted."""
        if getattr(pose, "phase", "idle") != "idle" or getattr(pose, "idle_action", "") != "knock":
            return
        blend = _unit(getattr(pose, "knock_blend", 0.0))
        root = getattr(pose, "nodes", {}).get("root")
        opacity = _unit(getattr(root, "opacity", 1.0))
        if blend * opacity < 0.001:
            return
        progress = _unit(getattr(pose, "action_progress", 0.0))
        impact = _unit(getattr(pose, "knock_impact", 0.0))
        # Keep even the outer ring off the border if a replacement asset has
        # placed its contact point close to a screen edge.
        center = QPointF(max(42.0, min(470.0, self.knock_contact.x())),
                         max(42.0, min(470.0, self.knock_contact.y())))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        for contact in (0.22, 0.43, 0.64):
            age = progress - contact
            if not 0 <= age <= 0.10:
                continue
            expansion = age / 0.10
            strength = ((1.0 - expansion) * blend * opacity * 0.45
                        * max(0.25, impact))
            radius = 8.0 + expansion * 24.0
            painter.setOpacity(strength)
            painter.setPen(QPen(QColor("#a7c3df"), 1.6))
            painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius,
                                      radius * 2, radius * 2))
            painter.setOpacity(strength * 0.45)
            radius += 6.0
            painter.drawEllipse(QRectF(center.x() - radius, center.y() - radius,
                                      radius * 2, radius * 2))
        painter.restore()
