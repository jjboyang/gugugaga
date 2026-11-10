#!/usr/bin/env python3
"""Export actual Pomodoro rig frames without reading or changing timer data."""
from __future__ import annotations

import argparse
from io import BytesIO
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=16)
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0.1 <= args.seconds <= 30:
        parser.error("--seconds must be between 0.1 and 30")
    if not 1 <= args.fps <= 30:
        parser.error("--fps must be between 1 and 30")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    from pet.pomodoro_renderer import PomodoroRenderer
    from pet.rig_animator import RigRenderer
    from pet.rig_motion import RigMotion

    app = QApplication.instance() or QApplication([])
    rig = RigRenderer(ROOT / "pet/characters/dafeiyu/rig")
    art = PomodoroRenderer()
    modes = [("focus", "专注 · 轻敲键盘"), ("focus_done", "完成 · 轻摇手铃"),
             ("break", "休息 · 捧杯放松"), ("activity", "活动 · 舒展一下")]
    output = args.export_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    width, height, tile = 1120, 340, 280

    def character(mode, t, motion, dt):
        pose = motion.step(dt, "idle")
        art.apply_pose(pose, mode, t)
        pixmap = rig.render(pose, texture=art.texture(mode, t, eye_open=pose.eye_open),
                            vertex_deformer=lambda points: art.deform_vertices(points, mode, t))
        return art.paint(pixmap, mode, t, artwork_rendered=True)

    def sheet(images, dark=False):
        image = QPixmap(width, height)
        image.fill(QColor("#1e2b42" if dark else "#f2f5fc"))
        p = QPainter(image)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setFont(QFont("Noto Sans CJK SC", 12))
        for i, ((mode, title), sprite) in enumerate(zip(modes, images)):
            x = i * tile
            p.setPen(QColor("#dae7fd" if dark else "#344b75"))
            p.drawText(QRectF(x, 16, tile, 30), Qt.AlignCenter, title)
            p.drawPixmap(QRectF(x + 4, 39, 272, 272), sprite, QRectF(sprite.rect()))
            p.setPen(QColor("#92a7c8" if dark else "#6d7d98"))
            p.setFont(QFont("Noto Sans CJK SC", 9))
            p.drawText(QRectF(x, 303, tile, 25), Qt.AlignCenter, "实际骨骼动画 · 透明素材")
            p.setFont(QFont("Noto Sans CJK SC", 12))
        p.end()
        return image

    def save(image, path):
        if not image.save(str(path), "PNG"):
            raise OSError(f"Cannot export {path}")

    # Static overview checks transparency on both desktop background tones.
    snapshots = [character(mode, 3.5, RigMotion(), 0.1) for mode, _ in modes]
    contact = QPixmap(width, height * 2)
    p = QPainter(contact)
    p.drawPixmap(0, 0, sheet(snapshots))
    p.drawPixmap(0, height, sheet(snapshots, dark=True))
    p.end()
    save(contact, output / "overview.png")
    for (mode, _), sprite in zip(modes, snapshots):
        save(sprite, output / f"{mode}.png")

    frames = []
    motions = [RigMotion() for _ in modes]
    for index in range(max(1, round(args.seconds * args.fps))):
        t = index / args.fps
        images = [character(mode, t, motion, 1 / args.fps)
                  for (mode, _), motion in zip(modes, motions)]
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        sheet(images).save(buffer, "PNG")
        frames.append(Image.open(BytesIO(bytes(buffer.data()))).convert("RGB"))
    frames[0].save(output / "animation.gif", save_all=True, append_images=frames[1:],
                   duration=round(1000 / args.fps), loop=0, optimize=True)
    print(f"Exported {len(frames)} animated frames and light/dark overview to {output}")


if __name__ == "__main__":
    main()
