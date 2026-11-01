"""Preserve the original sitting artwork and animate it with a weighted mesh.

The bind texture is rendered from the original atlas with AnimationEngine's
anchor/scale convention.  Every shared mesh vertex blends continuous bone
weights.  No character pixels are redrawn, cut into replacement body parts, or
generated here; joints therefore cannot expose missing artwork underneath.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QTransform

from pet.rig_motion import NodePose, RigPose


def _smooth(low, high, value):
    value = max(0.0, min(1.0, (value - low) / (high - low)))
    return value * value * (3.0 - 2.0 * value)


def _gaussian(x, y, cx, cy, width, height):
    return math.exp(-0.5 * (((x - cx) / width) ** 2 + ((y - cy) / height) ** 2))


class OriginalMeshRenderer:
    """A small CPU-skinned triangle renderer using only the existing Qt runtime.

    ``asset_dir`` is the ``dafeiyu/rig`` directory; the immutable source artwork
    and its crop manifest are read from its parent.  ``texture`` is the neutral
    512px bind image.  ``_texture_for_pose`` is the composition hook for original
    expression/prop patches before the *same* mesh deformation is applied.
    """

    size = [512, 512]

    def __init__(self, asset_dir):
        self.asset_dir = Path(asset_dir)
        source_dir = self.asset_dir.parent
        manifest_path = source_dir / "atlas.json"
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame_index = self.manifest["phases"]["idle"][0]
            frame = self.manifest["frames"][frame_index]
            source_size = self.manifest["canvas_size"]
            if len(source_size) != 2 or any(float(v) <= 0 for v in source_size):
                raise ValueError("Invalid original canvas size")
            source_scale = float(self.manifest["scale"])
            baseline = float(self.manifest["baseline"])
            anchor_x, anchor_y = (float(v) for v in frame["anchor"])
            if source_scale <= 0 or not all(math.isfinite(v) for v in (
                source_scale, baseline, anchor_x, anchor_y,
            )):
                raise ValueError("Invalid original frame anchor/scale")
            rect = frame["rect"]
            if len(rect) != 4 or any(not isinstance(v, int) for v in rect):
                raise ValueError("Invalid original frame crop")
            atlas = QPixmap(str(source_dir / self.manifest["image"]))
            if atlas.isNull():
                raise ValueError("Cannot load original character atlas")
            crop = QRect(*rect)
            if crop.isEmpty() or not atlas.rect().contains(crop):
                raise ValueError("Original frame crop lies outside its atlas")
        except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"Cannot load original DaFeiYu mesh source: {exc}") from exc

        self.texture = QPixmap(*self.size)
        self.texture.fill(Qt.transparent)
        painter = QPainter(self.texture)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.scale(self.size[0] / source_size[0], self.size[1] / source_size[1])
            painter.translate(source_size[0] / 2, baseline)
            painter.scale(source_scale, source_scale)
            painter.drawPixmap(QPointF(-anchor_x, -anchor_y), atlas.copy(crop))
        finally:
            painter.end()
        self.base_pixmap = self.texture

        factor_x, factor_y = self.size[0] / source_size[0], self.size[1] / source_size[1]
        self._content_rect = QRectF(
            factor_x * (source_size[0] / 2 - anchor_x * source_scale),
            factor_y * (baseline - anchor_y * source_scale),
            crop.width() * source_scale * factor_x,
            crop.height() * source_scale * factor_y,
        ).adjusted(-2, -2, 2, 2)

        # Absolute bind pivots are measured on the unchanged sitting image.
        self.pivots = {
            "root": (256.0, 475.0), "body": (256.0, 435.0),
            "head": (256.0, 365.0), "hair_left": (155.0, 280.0),
            "hair_right": (355.0, 280.0), "arm_left": (230.0, 402.0),
            "arm_right": (283.0, 402.0), "leg_left": (224.0, 448.0),
            "leg_right": (286.0, 448.0), "eyes": (256.0, 325.0),
            "mouth": (256.0, 357.0), "headdress": (256.0, 170.0),
            "book": (256.0, 421.0),
        }
        parents = {
            "root": None, "body": "root", "head": "body",
            "hair_left": "head", "hair_right": "head", "eyes": "head",
            "mouth": "head", "headdress": "head", "arm_left": "body",
            "arm_right": "body", "leg_left": "body", "leg_right": "body",
            "book": "body",
        }
        self.bones = {}
        for name, pivot in self.pivots.items():
            parent = parents[name]
            origin = self.pivots[parent] if parent else (0.0, 0.0)
            self.bones[name] = {
                "parent": parent,
                "position": [pivot[0] - origin[0], pivot[1] - origin[1]],
            }
        config_path = self.asset_dir / "manifest.json"
        try:
            self.rig_manifest = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
            columns = self.rig_manifest.get("mesh_columns", 16)
            rows = self.rig_manifest.get("mesh_rows", 16)
            if any(not isinstance(v, int) or not 4 <= v <= 32 for v in (columns, rows)):
                raise ValueError("Mesh rows and columns must be integers from 4 to 32")
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot load DaFeiYu mesh configuration: {exc}") from exc
        self._make_grid(columns, rows)

    def _weights_at(self, x, y):
        # Hair below the cheeks inherits the head, but receives its own slower
        # secondary transform. Smooth ownership avoids rigid cutout boundaries.
        lower_hair = _smooth(260.0, 345.0, y) * (1.0 - _smooth(440.0, 505.0, y))
        hair_left = 0.88 * (1.0 - _smooth(160.0, 222.0, x)) * lower_hair
        hair_right = 0.88 * _smooth(290.0, 352.0, x) * lower_hair
        remaining = 1.0 - hair_left - hair_right
        upper = 1.0 - _smooth(340.0, 410.0, y)
        headdress = 0.50 * _gaussian(x, y, 256.0, 164.0, 98.0, 62.0)
        raw = {
            "hair_left": hair_left, "hair_right": hair_right,
            "headdress": remaining * upper * headdress,
            "head": remaining * upper * (1.0 - headdress),
            "body": remaining * (1.0 - upper),
        }
        # Hands and feet remain in their original folded/sitting locations.
        # Their influence deforms existing pixels rather than attaching new limbs.
        limb_region = remaining * (1.0 - upper)
        limbs = {
            "arm_left": 0.72 * _gaussian(x, y, 230.0, 402.0, 19.0, 23.0),
            "arm_right": 0.72 * _gaussian(x, y, 283.0, 402.0, 19.0, 23.0),
            "leg_left": 0.82 * _gaussian(x, y, 224.0, 451.0, 23.0, 22.0),
            "leg_right": 0.82 * _gaussian(x, y, 286.0, 451.0, 23.0, 22.0),
        }
        total_limb = sum(limbs.values())
        fraction = min(0.88, total_limb)
        raw["body"] *= 1.0 - fraction
        if total_limb > 0:
            for name, weight in limbs.items():
                raw[name] = limb_region * fraction * weight / total_limb
        # Tiny far-away influences add work but no visible deformation.
        raw = {name: weight for name, weight in raw.items() if weight > 0.0001}
        total = sum(raw.values())
        return {name: weight / total for name, weight in raw.items()}

    def _make_grid(self, columns, rows):
        self.vertices, self.weights, self.triangles = [], [], []
        self._triangle_sources = []
        for row in range(rows + 1):
            for column in range(columns + 1):
                x, y = column * self.size[0] / columns, row * self.size[1] / rows
                self.vertices.append(QPointF(x, y))
                self.weights.append(self._weights_at(x, y))
        for row in range(rows):
            for column in range(columns):
                a = row * (columns + 1) + column
                b, c, d = a + 1, a + columns + 2, a + columns + 1
                for triangle in ((a, b, c), (a, c, d)):
                    self.triangles.append(triangle)
                    p, q, r = (self.vertices[index] for index in triangle)
                    u1, v1 = q.x() - p.x(), q.y() - p.y()
                    u2, v2 = r.x() - p.x(), r.y() - p.y()
                    determinant = u1 * v2 - u2 * v1
                    rect = QRectF(
                        min(p.x(), q.x(), r.x()), min(p.y(), q.y(), r.y()),
                        max(p.x(), q.x(), r.x()) - min(p.x(), q.x(), r.x()),
                        max(p.y(), q.y(), r.y()) - min(p.y(), q.y(), r.y()),
                    ).adjusted(-1, -1, 1, 1)
                    # Sleep's ZZZ and the lifted pose extend beyond idle's
                    # bounds. Keep the complete shared mesh for every texture.
                    active = True
                    self._triangle_sources.append((p.x(), p.y(), u1, v1, u2, v2, determinant, rect, active))

    def transforms(self, pose):
        """Return bone-origin world transforms and inherited opacity, as before."""
        result = {}

        def resolve(name):
            if name in result:
                return result[name]
            bone = self.bones[name]
            parent = bone["parent"]
            parent_transform, opacity = resolve(parent) if parent else (QTransform(), 1.0)
            node = pose.nodes.get(name, NodePose())
            x, y = bone["position"]
            transform = QTransform(parent_transform)
            transform.translate(x + node.dx, y + node.dy)
            transform.rotate(node.angle)
            transform.scale(node.sx, node.sy)
            result[name] = transform, opacity * node.opacity
            return result[name]

        for name in self.bones:
            resolve(name)
        return result

    def _texture_for_pose(self, pose):
        """Compose optional original-art eye/prop patches before skinning."""
        return self.base_pixmap

    def deformed_vertices(self, pose):
        """Expose the shared skinned vertices for rig editors and validation."""
        return self._deformed_vertices(self.transforms(pose))

    def _deformed_vertices(self, transforms):
        vertices = []
        for point, weights in zip(self.vertices, self.weights):
            x = y = 0.0
            for bone, weight in weights.items():
                px, py = self.pivots[bone]
                transformed = transforms[bone][0].map(QPointF(point.x() - px, point.y() - py))
                x += transformed.x() * weight
                y += transformed.y() * weight
            vertices.append(QPointF(x, y))
        return vertices

    def render(self, pose: RigPose, scale=1.0):
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0 or scale > 4:
            raise ValueError("Render scale must be greater than 0 and at most 4")
        image = QPixmap(round(self.size[0] * scale), round(self.size[1] * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        root_opacity = max(0.0, min(1.0, pose.nodes.get("root", NodePose()).opacity))
        if root_opacity <= 0:
            return image
        texture = self._texture_for_pose(pose)
        transforms = self.transforms(pose)
        vertices = self._deformed_vertices(transforms)
        neutral = all(
            abs(a.x() - b.x()) < 1e-8 and abs(a.y() - b.y()) < 1e-8
            for a, b in zip(self.vertices, vertices)
        )
        if neutral and scale == 1.0 and root_opacity == 1.0:
            return QPixmap(texture)
        painter = QPainter(image)
        try:
            painter.setOpacity(root_opacity)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            if neutral:
                # A bind pose has exactly the same artwork and rasterization as
                # drawing the original frame: no needless mesh edge resampling.
                painter.drawPixmap(QPointF(0, 0), texture)
                return image
            # Aliased shared clips partition coverage without fractional-alpha
            # cracks. Source composition makes a shared raster edge idempotent,
            # preserving transparent hair pixels instead of doubling their alpha.
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            for triangle, source in zip(self.triangles, self._triangle_sources):
                x0, y0, u1, v1, u2, v2, determinant, rect, active = source
                if not active:
                    continue
                p, q, r = (vertices[index] for index in triangle)
                dx1, dy1 = q.x() - p.x(), q.y() - p.y()
                dx2, dy2 = r.x() - p.x(), r.y() - p.y()
                m11 = (dx1 * v2 - dx2 * v1) / determinant
                m21 = (dx2 * u1 - dx1 * u2) / determinant
                m12 = (dy1 * v2 - dy2 * v1) / determinant
                m22 = (dy2 * u1 - dy1 * u2) / determinant
                affine = QTransform(
                    m11, m12, m21, m22,
                    p.x() - m11 * x0 - m21 * y0,
                    p.y() - m12 * x0 - m22 * y0,
                )
                clip = QPainterPath(p)
                clip.lineTo(q)
                clip.lineTo(r)
                clip.closeSubpath()
                painter.save()
                painter.setClipPath(clip, Qt.ReplaceClip)
                painter.setWorldTransform(affine)
                painter.drawPixmap(rect, texture, rect)
                painter.restore()
        finally:
            painter.end()
        return image
