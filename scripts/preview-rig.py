#!/usr/bin/env python3
"""Preview or export the DaFeiYu skeleton without IPC or desktop-pet settings."""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
PHASES = (
    ("idle", "待机"), ("question", "提问"), ("reading", "阅读"),
    ("thinking", "思考"), ("writing", "书写"), ("executing", "执行"),
    ("done", "完成"), ("sleep", "睡觉"), ("angry", "生气"),
    ("dragged", "拖动"), ("waddle", "原地行走姿势"),
)
ACTIONS = (("walk", "待机走动"), ("knock", "敲敲屏幕"), ("hop", "蹦跳引起注意"))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", type=Path, help="Export PNG frames and contact-sheet.png, then exit")
    parser.add_argument("--phase", choices=[name for name, _ in PHASES], default="idle")
    parser.add_argument("--action", choices=[name for name, _ in ACTIONS],
                        help="Preview an idle gesture; requires --phase idle (the default)")
    parser.add_argument("--seconds", type=float, default=4.0, help="Animation length, default: 4 seconds")
    parser.add_argument("--fps", type=int, default=30, help="Export frame rate, default: 30")
    parser.add_argument("--reduced-motion", action="store_true", help="Use gentler motion")
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0.1 <= args.seconds <= 30:
        parser.error("--seconds must be between 0.1 and 30")
    if not 1 <= args.fps <= 120:
        parser.error("--fps must be between 1 and 120")
    if args.action is not None and args.phase != "idle":
        parser.error("--action requires --phase idle")
    return args


def main():
    args = parse_args()
    if args.export_dir is not None:
        # CLI exports work on a machine without a desktop/display server.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton,
        QVBoxLayout, QWidget,
    )
    from pet.rig_animator import RigRenderer
    from pet.rig_motion import RigMotion

    app = QApplication(sys.argv[:1])
    renderer = RigRenderer(PROJECT_ROOT / "pet" / "characters" / "dafeiyu" / "rig")

    def advance(motion, dt, phase, elapsed, action="", action_duration=4.8):
        drag_angle = 19.0 * math.sin(elapsed * 4.8) if phase == "dragged" else 0.0
        pointer = (0.35 * math.sin(elapsed * 0.65), 0.18 * math.cos(elapsed * 0.5))
        action_elapsed = elapsed % action_duration if action else 0.0
        return motion.step(
            dt, phase, drag_angle=drag_angle, pointer=pointer,
            idle_action=action, action_elapsed=action_elapsed,
            action_duration=action_duration,
        )

    def save_png(pixmap, path):
        if not pixmap.save(str(path), "PNG"):
            raise OSError(f"Cannot write preview: {path}")

    if args.export_dir is not None:
        output = args.export_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        # Do not leave old extra frames when exporting a shorter second take.
        for old_frame in output.glob("frame_[0-9][0-9][0-9][0-9].png"):
            old_frame.unlink()
        motion = RigMotion(seed=137, reduced_motion=args.reduced_motion)
        motion.reset(args.phase)
        frame_count = max(1, round(args.seconds * args.fps))
        for index in range(frame_count):
            elapsed = index / args.fps
            pose = advance(motion, 0.0 if index == 0 else 1 / args.fps,
                           args.phase, elapsed, args.action or "", args.seconds)
            save_png(renderer.render(pose), output / f"frame_{index:04d}.png")

        columns, tile_width, tile_height = 4, 280, 320
        samples = [(phase, "", phase) for phase, _ in PHASES]
        samples.extend(("idle", action, f"idle / {action}") for action, _ in ACTIONS)
        rows = math.ceil(len(samples) / columns)
        sheet = QPixmap(columns * tile_width, rows * tile_height)
        sheet.fill(QColor("#edf0f5"))
        painter = QPainter(sheet)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setFont(QFont("Sans Serif", 11))
        for index, (phase, action, label) in enumerate(samples):
            sample = RigMotion(seed=137, reduced_motion=args.reduced_motion)
            sample.reset(phase)
            seconds = {"walk": 1.2, "knock": 2.064, "hop": 1.2}.get(
                action, 0.75 if phase == "done" else 1.8,
            )
            for step in range(round(seconds * 60)):
                pose = advance(sample, 1 / 60, phase, (step + 1) / 60, action)
            pixmap = renderer.render(pose)
            x, y = (index % columns) * tile_width, (index // columns) * tile_height
            painter.drawPixmap(QRectF(x + 8, y + 2, 264, 264), pixmap, QRectF(pixmap.rect()))
            painter.setPen(QColor("#293450"))
            painter.drawText(QRectF(x + 8, y + 270, 264, 35), Qt.AlignCenter, label)
        painter.end()
        save_png(sheet, output / "contact-sheet.png")
        label = f"idle/{args.action}" if args.action else args.phase
        print(f"Exported {frame_count} transparent {label} frames at {args.fps} FPS to {output}")
        print(f"All {len(PHASES)} states and {len(ACTIONS)} idle gestures: {output / 'contact-sheet.png'}")
        return 0

    class Canvas(QLabel):
        clicked = Signal()

        def mousePressEvent(self, event):
            if event.button() == Qt.LeftButton:
                self.clicked.emit()
            super().mousePressEvent(event)

    class PreviewWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("大肥鱼 · 分层骨骼动画预览")
            self.setStyleSheet("QWidget { font-size: 14px; } QPushButton { padding: 6px 12px; }")
            self.motion = RigMotion(seed=137, reduced_motion=args.reduced_motion)
            self.motion.reset(args.phase)
            self.phase = args.phase
            self.action = args.action or ""
            self.elapsed = 0.0
            self.last_tick = time.monotonic()
            layout = QVBoxLayout(self)
            title = QLabel("大肥鱼 · 分层骨骼动画")
            title.setStyleSheet("font-size: 20px; font-weight: 600; padding: 6px;")
            layout.addWidget(title)
            self.canvas = Canvas()
            self.canvas.setFixedSize(512, 512)
            self.canvas.setAlignment(Qt.AlignCenter)
            self.canvas.setStyleSheet("background: #edf0f5; border-radius: 12px;")
            self.canvas.setCursor(Qt.PointingHandCursor)
            self.canvas.clicked.connect(self.on_tap)
            layout.addWidget(self.canvas)

            controls = QHBoxLayout()
            self.phase_selector = QComboBox()
            for name, label in PHASES:
                self.phase_selector.addItem(f"{label} · {name}", name)
            for name, label in ACTIONS:
                self.phase_selector.addItem(f"{label} · idle/{name}", f"action:{name}")
            initial_index = ([name for name, _ in PHASES].index(args.phase) if not self.action
                             else len(PHASES) + [name for name, _ in ACTIONS].index(self.action))
            self.phase_selector.setCurrentIndex(initial_index)
            self.phase_selector.currentIndexChanged.connect(self.change_phase)
            controls.addWidget(self.phase_selector, 1)
            self.play_button = QPushButton("暂停")
            self.play_button.clicked.connect(self.toggle_playback)
            controls.addWidget(self.play_button)
            reset_button = QPushButton("重置")
            reset_button.clicked.connect(self.reset_motion)
            controls.addWidget(reset_button)
            layout.addLayout(controls)

            options = QHBoxLayout()
            self.gentle = QCheckBox("减小动作幅度")
            self.gentle.setChecked(args.reduced_motion)
            self.gentle.toggled.connect(self.set_gentle)
            options.addWidget(self.gentle)
            options.addStretch()
            tap_button = QPushButton("点击反馈")
            tap_button.clicked.connect(self.on_tap)
            options.addWidget(tap_button)
            layout.addLayout(options)
            hint = QLabel("点击角色可预览回弹；拖动状态会模拟摇摆；待机动作每 4.8 秒循环。\n走动只预览步态；真实桌宠才会在附近移动。此窗口不连接 IPC 或修改配置。")
            hint.setStyleSheet("color: #59677a; padding: 5px;")
            layout.addWidget(hint)

            self.timer = QTimer(self)
            self.timer.setTimerType(Qt.PreciseTimer)
            self.timer.setInterval(16)
            self.timer.timeout.connect(self.tick)
            self.timer.start()
            self.paint_pose(0.0)
            self.setFixedSize(self.sizeHint())

        def paint_pose(self, dt):
            pose = advance(self.motion, dt, self.phase, self.elapsed, self.action)
            self.canvas.setPixmap(renderer.render(pose))

        def tick(self):
            now = time.monotonic()
            dt = max(0.0, min(0.1, now - self.last_tick))
            self.last_tick = now
            self.elapsed += dt
            self.paint_pose(dt)

        def change_phase(self):
            selection = self.phase_selector.currentData()
            self.action = selection.removeprefix("action:") if selection.startswith("action:") else ""
            self.phase = "idle" if self.action else selection
            self.elapsed = 0.0
            self.last_tick = time.monotonic()
            # Preserve spring positions so state changes remain continuous.
            self.paint_pose(0.0)

        def toggle_playback(self):
            if self.timer.isActive():
                self.timer.stop()
                self.play_button.setText("播放")
            else:
                self.last_tick = time.monotonic()
                self.timer.start()
                self.play_button.setText("暂停")

        def reset_motion(self):
            self.motion.reset(self.phase)
            self.elapsed = 0.0
            self.last_tick = time.monotonic()
            self.paint_pose(0.0)

        def set_gentle(self, enabled):
            self.motion.reduced_motion = enabled

        def on_tap(self):
            self.motion.tap()

    window = PreviewWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
