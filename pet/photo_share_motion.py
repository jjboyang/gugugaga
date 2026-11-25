"""DaFeiYu sorts through a few prints, then lifts the picture she picked."""

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from pet.companion import smooth


REVEAL_SECONDS = 1.24
DURATION_SECONDS = 1.68


def apply_pose(pose, age):
    lean = smooth(age / 0.28) * (1 - smooth((age - 0.85) / 0.31))
    lift = smooth((age - 0.77) / 0.41) * (1 - smooth((age - 1.43) / 0.25))
    searching = lean * math.sin(age * math.tau * 2.3)
    body, head = pose.nodes["body"], pose.nodes["head"]
    left, right = pose.nodes["arm_left"], pose.nodes["arm_right"]
    body.angle += 1.7 * searching
    head.angle += 3.4 * lean + 1.5 * searching - 2.7 * lift
    head.dy += 6 * lean - 3 * lift
    pose.gaze_x = pose.gaze_x * (1 - lean) + 0.39 * searching
    pose.gaze_y = pose.gaze_y * (1 - lean) + 0.85 * lean
    left.dy -= 5 * searching
    right.dy += 7 * searching - 11 * lift
    right.angle -= 12 * lift
    pose.mouth_open += 0.16 * lift


def texture(awake, image, age):
    result = QPixmap(awake)
    painter = QPainter(result)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    folder_opacity = smooth(age / 0.19) * (1 - smooth((age - 1.12) / 0.26))
    painter.setOpacity(folder_opacity)
    for start, x, slide, angle, color in ((0.17, 241, -10, -16, "#ddd8f0"), (0.44, 262, 14, 14, "#acd1e8")):
        peek = smooth((age - start) / 0.12) * (1 - smooth((age - start - 0.16) / 0.19))
        painter.save()
        painter.translate(x + slide * peek, 424 - 23 * peek)
        painter.rotate(angle * peek)
        painter.setBrush(QColor(color))
        painter.setPen(QPen(QColor("#7f91b3"), 1.6))
        painter.drawRoundedRect(QRectF(-25, -13, 50, 33), 3, 3)
        painter.restore()

    painter.setPen(QPen(QColor("#a18d7b"), 1.8))
    painter.setBrush(QColor("#f4e6d3"))
    painter.drawRoundedRect(QRectF(211, 413, 88, 29), 6, 6)
    painter.setPen(QPen(QColor("#c6a98d"), 1.5, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(218, 420, 290, 420)

    pull = smooth((age - 0.73) / 0.44)
    painter.save()
    painter.setOpacity(smooth((age - 0.73) / 0.19) * (1 - smooth((age - 1.44) / 0.24)))
    painter.translate(255 + 32 * pull, 423 - 44 * pull)
    painter.rotate(-10 + 16 * pull)
    painter.setPen(QPen(QColor("#8599b8"), 1.8))
    painter.setBrush(QColor("#fbfcff"))
    painter.drawRoundedRect(QRectF(-36, -28, 72, 58), 4, 4)
    image_size = image.size().scaled(62, 43, Qt.KeepAspectRatio)
    painter.drawImage(QRectF(-image_size.width() / 2, -25 + (43 - image_size.height()) / 2,
                            image_size.width(), image_size.height()), image)
    painter.restore()

    # Keep the original fingers in front of both the paper folder and the print.
    painter.setOpacity(1.0)
    fingertips = QPainterPath()
    fingertips.addEllipse(QRectF(218, 395, 27, 22))
    fingertips.addEllipse(QRectF(266, 396, 26, 22))
    painter.setClipPath(fingertips)
    painter.drawPixmap(0, 0, awake)
    painter.end()
    return result
