#!/usr/bin/env python3
"""Export the actual dialogue widgets and character on light/dark desktops."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pet-size", type=int, default=140, choices=range(80, 301), metavar="80..300")
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from unittest.mock import patch
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    from pet.rig_animator import RigRenderer
    from pet.rig_motion import RigPose
    from pet.speech_bubble import DAFEIYU_REPLIES
    from pet.window import PetWindow

    app = QApplication.instance() or QApplication([])
    with patch("pet.window._load_config", return_value={"pet_size": args.pet_size}):
        window = PetWindow()
    window.move(320, 320)
    window.set_pixmap(RigRenderer(ROOT / "pet/characters/dafeiyu/rig").render(RigPose()))
    window.show()
    app.processEvents()
    tile = max(230, args.pet_size + 60)
    row_height = args.pet_size + 90
    image = QPixmap(tile * 4, (row_height + 40) * 2)
    image.fill(QColor("#f3f6fb"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    font = QFont()
    font.setFamilies(["PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC"])
    font.setPixelSize(14)
    painter.setFont(font)

    for row, dark in enumerate((False, True)):
        top = row * (row_height + 40)
        if dark:
            painter.fillRect(0, top, image.width(), row_height + 40, QColor("#233047"))
        painter.setPen(QColor("#b7cae3" if dark else "#5b7293"))
        painter.drawText(QRectF(24, top + 10, image.width() - 48, 26),
                         Qt.AlignVCenter, f"{'深色' if dark else '浅色'}桌面 · 实际角色尺寸 {args.pet_size}px")
        for column, reply in enumerate(DAFEIYU_REPLIES):
            window._show_speech_bubble(reply)
            bubble = window._speech_popup
            # Freeze at the settled animation frame, using the real widget painter.
            bubble._animation.stop()
            bubble._hold_timer.stop()
            bubble._set_progress(1.0)
            app.processEvents()
            pet_x = column * tile + (tile - window.width()) // 2
            pet_y = top + 100
            painter.drawPixmap(pet_x, pet_y, window.grab())
            relative = bubble.pos() - window.pos()
            painter.drawPixmap(pet_x + relative.x(), pet_y + relative.y(), bubble.grab())
    painter.end()
    window.close()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "PNG"):
        raise OSError(f"Cannot export {output}")
    print(f"Exported actual dialogue widgets to {output}")


if __name__ == "__main__":
    main()
