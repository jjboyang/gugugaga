"""DaFeiYu sorts through a few prints, then lifts the picture she picked."""

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from pet.companion import smooth


REVEAL_SECONDS = 1.24
DURATION_SECONDS = 1.68


def motion_time(seconds, style):
    if style == "eager":
        return seconds * 1.22
    if style == "peek":
        # Linger over the back of the print before turning it towards the user.
        return seconds - 0.35 * smooth((seconds - 0.83) / 0.58)
    return seconds


def apply_pose(pose, age, style="normal"):
    age = motion_time(age, style)
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
    if style == "eager":
        reach = smooth((age - 0.53) / 0.43) * (1 - smooth((age - 1.34) / 0.34))
        # Lean the original seated rig forward as a whole, with both feet planted.
        body.dx += 4 * reach
        body.dy -= 4 * reach
        head.dx += 7 * reach
        head.angle -= 3 * reach
        right.dy -= 5 * reach
        pose.mouth_open += 0.20 * reach
    elif style == "peek":
        glance = smooth((age - 0.60) / 0.23) * (1 - smooth((age - 1.02) / 0.18))
        head.angle += 6 * glance
        head.dy += 3 * glance
        pose.gaze_x += (0.85 - pose.gaze_x) * glance
        pose.gaze_y += (0.65 - pose.gaze_y) * glance


def texture(awake, image, age, style="normal"):
    age = motion_time(age, style)
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
    if style == "eager":
        reach = 1 + 0.25 * pull
        painter.scale(reach, reach)
    turn = smooth((age - 0.99) / 0.23) if style == "peek" else 1.0
    painter.scale(max(0.045, abs(math.cos(math.pi * turn))), 1)
    painter.setPen(QPen(QColor("#8599b8"), 1.8))
    painter.setBrush(QColor("#fbfcff"))
    painter.drawRoundedRect(QRectF(-36, -28, 72, 58), 4, 4)
    if turn < 0.5:
        painter.setPen(QPen(QColor("#b8c9dc"), 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(-25, 15, -4, 15)
        painter.drawLine(-25, 20, -12, 20)
    else:
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
