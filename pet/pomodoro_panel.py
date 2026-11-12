"""Pomodoro controls and local focus statistics, independent of timer scheduling."""
from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


def format_duration(seconds):
    """Show only earned full minutes in statistics."""
    minutes = max(0, int(seconds)) // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes:02d} 分钟"


class WeekChart(QWidget):
    """A compact seven-day chart with a useful empty state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = []
        self.setMinimumHeight(116)
        self.setAccessibleName("本周每天专注时长")

    def set_days(self, days):
        if days == self.days:
            return
        self.days = [dict(day) for day in days]
        self.setAccessibleDescription("；".join(
            f"{day['date']}：{format_duration(day['focus_seconds'])}"
            for day in days
        ))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        days = self.days[:7]
        maximum = max([3600] + [day["focus_seconds"] for day in days])
        column_width = self.width() / 7
        height = max(1, self.height() - 43)
        today = date.today().isoformat()
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        for i in range(7):
            day = days[i] if i < len(days) else {}
            seconds = max(0, day.get("focus_seconds", 0))
            day_text = str(day.get("date", ""))[:10]
            x = i * column_width
            bar_width = min(24, column_width - 14)
            bar_x = x + (column_width - bar_width) / 2
            painter.setBrush(QColor("#30353b"))
            painter.drawRoundedRect(QRectF(bar_x, 19, bar_width, height), 5, 5)
            if seconds:
                bar_height = max(3, height * seconds / maximum)
                painter.setBrush(QColor("#f6a38f" if day_text == today else "#78899a"))
                painter.drawRoundedRect(
                    QRectF(bar_x, 19 + height - bar_height, bar_width, bar_height), 5, 5
                )
            painter.setPen(QColor("#d6dce1"))
            painter.drawText(QRectF(x, 0, column_width, 17), Qt.AlignCenter, str(int(seconds // 60)))
            painter.setPen(QColor("#f6a38f" if day_text == today else "#9aa5af"))
            painter.drawText(
                QRectF(x, self.height() - 20, column_width, 20), Qt.AlignCenter,
                ("一", "二", "三", "四", "五", "六", "日")[i],
            )
            painter.setPen(Qt.NoPen)
        painter.end()


class PomodoroPanel(QDialog):
    """Closing the window leaves the externally scheduled timer running.

    The application calls refresh() after ticking its shared timer. A user action
    emits the model's returned events so the application can update pet visuals
    and alerts immediately, without creating another timer in this widget.
    """

    action_taken = Signal(object)

    def __init__(self, timer, parent=None):
        super().__init__(parent)
        self.timer = timer
        self.setWindowTitle("大肥鱼 · 番茄时钟")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setMinimumWidth(410)
        self.resize(442, 680)
        self.setStyleSheet("""
            QDialog { background: #20252b; color: #edf0f2; }
            QScrollArea { background: #20252b; border: none; }
            QWidget#content { background: #20252b; }
            QLabel { color: #edf0f2; background: transparent; font-size: 13px; }
            QLabel#title { font-size: 22px; font-weight: 700; }
            QLabel#muted { color: #9aa5af; font-size: 12px; }
            QLabel#phase { color: #f6a38f; font-size: 14px; font-weight: 600; }
            QLabel#clock { font-size: 57px; font-weight: 700; }
            QLabel#statValue { font-size: 21px; font-weight: 600; }
            QLabel#section { font-size: 14px; font-weight: 600; }
            QFrame#card { background: #292f36; border: 1px solid #353c45; border-radius: 12px; }
            QFrame#activity { background: #3b342b; border: 1px solid #756244; border-radius: 10px; }
            QLabel#warning { color: #f4cd90; font-size: 12px; }
            QPushButton { background: #343c45; color: #edf0f2; border: none;
                          border-radius: 8px; padding: 10px 14px; font-size: 13px; }
            QPushButton:hover { background: #424d58; }
            QPushButton:pressed { background: #29313a; }
            QPushButton:disabled { color: #6b7680; background: #292f36; }
            QPushButton#primary { background: #f6a38f; color: #33221f; font-weight: 600; }
            QPushButton#primary:hover { background: #ffb6a5; }
            QPushButton#primary:pressed { background: #dc8d7b; }
            QProgressBar { border: none; border-radius: 3px; background: #343c45; }
            QProgressBar::chunk { background: #f6a38f; border-radius: 3px; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("content")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(13)

        heading = QLabel("和大肥鱼一起专注")
        heading.setObjectName("title")
        layout.addWidget(heading)
        subtitle = QLabel("专心 25 分钟，让小小的进步慢慢累积。")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        self.phase_label = QLabel()
        self.phase_label.setObjectName("phase")
        self.phase_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.phase_label)
        self.countdown_label = QLabel()
        self.countdown_label.setObjectName("clock")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setAccessibleName("剩余时间")
        layout.addWidget(self.countdown_label)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        actions = QHBoxLayout()
        self.primary_button = QPushButton()
        self.primary_button.setObjectName("primary")
        self.primary_button.clicked.connect(self._primary_action)
        self.reset_button = QPushButton("结束并保留时长")
        self.reset_button.setToolTip("已专注时间会保留，未完成的一轮不计入番茄数。")
        self.reset_button.clicked.connect(lambda: self._run_action("reset"))
        actions.addWidget(self.primary_button, 1)
        actions.addWidget(self.reset_button)
        layout.addLayout(actions)

        self.activity_banner = QFrame()
        self.activity_banner.setObjectName("activity")
        activity_layout = QVBoxLayout(self.activity_banner)
        activity_text = QLabel("已经专注两小时啦，起来走走、伸个懒腰吧！")
        activity_text.setObjectName("warning")
        activity_text.setWordWrap(True)
        activity_layout.addWidget(activity_text)
        self.activity_button = QPushButton("我已起来活动")
        self.activity_button.clicked.connect(lambda: self._run_action("mark_activity"))
        activity_layout.addWidget(self.activity_button)
        layout.addWidget(self.activity_banner)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.stat_values = {}
        definitions = (
            ("today_focus_seconds", "今日专注时间", "暂停和休息不计入专注时间。"),
            ("today_pomodoros", "今日完成番茄数", "完成一轮 25 分钟才记作一个番茄。"),
            ("streak_days", "连续专注天数", "每天至少完成一个番茄；今天尚未完成时延续至昨天。"),
            ("week_focus_seconds", "本周工作时间", "按本地日期统计，周一至周日。"),
        )
        for i, (key, title, tip) in enumerate(definitions):
            card = QFrame()
            card.setObjectName("card")
            card.setToolTip(tip)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(13, 11, 13, 11)
            name = QLabel(title)
            name.setObjectName("muted")
            value = QLabel()
            value.setObjectName("statValue")
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            cards.addWidget(card, i // 2, i % 2)
            self.stat_values[key] = value
        layout.addLayout(cards)

        week_heading = QHBoxLayout()
        week_title = QLabel("这一周的专注")
        week_title.setObjectName("section")
        unit = QLabel("周一至周日 · 分钟")
        unit.setObjectName("muted")
        week_heading.addWidget(week_title)
        week_heading.addStretch()
        week_heading.addWidget(unit)
        layout.addLayout(week_heading)
        self.week_chart = WeekChart()
        layout.addWidget(self.week_chart)

        self.storage_label = QLabel()
        self.storage_label.setObjectName("warning")
        self.storage_label.setWordWrap(True)
        layout.addWidget(self.storage_label)
        footer = QLabel("关闭面板后仍会继续计时，右键大肥鱼可再次打开。")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.refresh()

    def _run_action(self, name):
        events = getattr(self.timer, name)()
        self.action_taken.emit(events)
        self.refresh()

    def _primary_action(self):
        if self.timer.phase in ("idle", "break_done"):
            self._run_action("start_focus")
        elif self.timer.phase == "focus_done":
            self._run_action("start_break")
        elif self.timer.paused:
            self._run_action("resume")
        else:
            self._run_action("pause")

    def refresh(self):
        phase = self.timer.phase
        running_phase = phase in ("focus", "break")
        paused = self.timer.paused and running_phase
        names = {
            "idle": "准备好，开始一个番茄", "focus": "大肥鱼正在陪你专注",
            "focus_done": "叮！这个番茄完成啦", "break": "喝杯咖啡，伸个懒腰",
            "break_done": "休息结束，开启下一轮吧",
        }
        self.phase_label.setText("已暂停 · 随时可以继续" if paused else names.get(phase, ""))
        remaining = 1500 if phase == "idle" else self.timer.remaining_seconds
        seconds = max(0, math.ceil(remaining))
        minutes, seconds = divmod(seconds, 60)
        self.countdown_label.setText(f"{minutes:02d}:{seconds:02d}")
        duration = 300 if phase in ("break", "break_done") else 1500
        self.progress.setRange(0, duration)
        self.progress.setValue(0 if phase == "idle" else max(0, min(duration, int(self.timer.elapsed_seconds))))
        if phase in ("idle", "break_done"):
            primary_text = "开始专注 · 25 分钟"
        elif phase == "focus_done":
            primary_text = "开始休息 · 5 分钟"
        else:
            primary_text = "继续计时" if paused else "暂停计时"
        self.primary_button.setText(primary_text)
        self.reset_button.setEnabled(phase != "idle")
        self.activity_banner.setVisible(self.timer.focus_since_activity >= 7200)

        stats = self.timer.stats()
        for key, label in self.stat_values.items():
            value = stats[key]
            if key.endswith("seconds"):
                text = format_duration(value)
            elif key == "streak_days":
                text = f"{value} 天"
            else:
                text = f"{value} 个"
            label.setText(text)
        self.week_chart.set_days(stats["week_days"])
        error = self.timer.storage_error
        self.storage_label.setText(f"统计暂未保存，本次数据仅暂存在内存中。\n{error}" if error else "")
        self.storage_label.setToolTip(error or "")
        self.storage_label.setVisible(bool(error))
