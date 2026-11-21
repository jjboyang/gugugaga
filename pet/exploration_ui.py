"""Shared colours, character artwork and controls for Dafeiyu's exploration windows."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QStyle, QStyledItemDelegate, QVBoxLayout,
)


STYLE = """
QDialog#explorationWindow {
    background: #f0f4fc;
    color: #1e2e51;
}
QLabel { color: #203356; }
QLabel[role="muted"] { color: #526683; }
QLabel[role="section"] { color: #24426f; font-size: 13px; font-weight: 700; }
QLabel[role="heading"] { color: #1c335d; font-size: 24px; font-weight: 700; }
QLabel[role="noteTitle"] { color: #1b3159; font-size: 20px; font-weight: 700; }
QLabel[role="reaction"] { color: #244b87; font-size: 15px; font-weight: 600; }
QLabel[role="error"] { color: #a53d51; }
QFrame[surface="hero"] {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #dceaff,stop:0.68 #e8efff,stop:1 #eee8ff);
    border: 1px solid #ccdafa;
    border-radius: 20px;
}
QFrame[surface="paper"] {
    background: #fcfdff;
    border: 1px solid #dce5f5;
    border-radius: 16px;
}
QFrame[surface="bubble"] {
    background: #eaf2ff;
    border: 1px solid #dae7fc;
    border-radius: 13px;
}
QFrame[surface="followup"] {
    background: #f2efff;
    border: 1px solid #e8e1fc;
    border-radius: 12px;
}
QFrame[surface="separator"] { background: #e4ebf7; }
QPushButton {
    color: #254875;
    background: #fcfdff;
    border: 1px solid #d1def3;
    border-radius: 10px;
    padding: 7px 13px;
    min-height: 19px;
    font-weight: 600;
}
QPushButton:hover { color: #224d89; background: #eaf2ff; border-color: #adbfe1; }
QPushButton:pressed { background: #dce9fc; }
QPushButton:focus { border-color: #6087c6; }
QPushButton[role="primary"] { color: #ffffff; background: #2f5eae; border-color: #2f5eae; }
QPushButton[role="primary"]:hover { background: #254e9a; }
QPushButton[role="primary"]:pressed { background: #1e407e; }
QPushButton[role="primary"]:focus { border-color: #17376f; }
QPushButton[role="remove"] { color: #993f55; }
QPushButton[role="remove"]:hover { background: #fff1f5; border-color: #e9bbc9; }
QPushButton:disabled, QPushButton[role="primary"]:disabled, QPushButton[role="remove"]:disabled {
    color: #657691;
    background: #eef2fa;
    border-color: #e0e7f3;
}
QLineEdit, QComboBox, QSpinBox {
    color: #203356;
    background: #fcfdff;
    border: 1px solid #cddaf0;
    border-radius: 9px;
    min-height: 21px;
    padding: 6px 10px;
    selection-background-color: #cfe2fc;
    selection-color: #19355e;
}
QLineEdit[readOnly="true"], QLineEdit:disabled, QComboBox:disabled {
    background: #edf2fb;
    color: #4d6180;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #5d85c4; }
QComboBox { padding-right: 27px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    background: transparent;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #fcfdff;
    color: #203356;
    border: 1px solid #cddaf0;
    selection-background-color: #dbe9ff;
    selection-color: #1f497f;
    padding: 4px;
}
QComboBox QAbstractItemView::item { padding: 5px 8px; min-height: 24px; }
QListWidget { background: transparent; border: none; outline: none; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 3px 1px;
}
QScrollBar::handle:vertical { background: #bacbe7; border-radius: 3px; min-height: 26px; }
QScrollBar::handle:vertical:hover { background: #899fc8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar {
    background: #cdddf5;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar::chunk { background: #4b78c5; border-radius: 3px; }
"""


def themed_layout(dialog, width, height, *, minimum_width=None):
    dialog.setObjectName("explorationWindow")
    font = QFont(dialog.font())
    font.setFamilies(["PingFang SC", "Microsoft YaHei UI", "Noto Sans CJK SC", "sans-serif"])
    font.setPixelSize(13)
    dialog.setFont(font)
    palette = dialog.palette()
    palette.setColor(QPalette.WindowText, QColor("#203356"))
    palette.setColor(QPalette.Text, QColor("#203356"))
    palette.setColor(QPalette.Base, QColor("#fcfdff"))
    palette.setColor(QPalette.Highlight, QColor("#dceaff"))
    palette.setColor(QPalette.HighlightedText, QColor("#1e457d"))
    palette.setColor(QPalette.PlaceholderText, QColor("#596c8a"))
    dialog.setPalette(palette)
    dialog.setStyleSheet(STYLE)
    dialog.setMinimumWidth(minimum_width if minimum_width is not None else width - 36)
    dialog.resize(width, height)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 16)
    layout.setSpacing(13)
    return layout


def label(text="", role=None, *, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text, role=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    if role:
        widget.setProperty("role", role)
    return widget


class Toggle(QCheckBox):
    """Draw the same switch on each platform, with native checkbox input."""

    def __init__(self, text):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(25)
        self.setToolTip(text)

    def sizeHint(self):
        return QSize(43 + self.fontMetrics().horizontalAdvance(self.text()), 25)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        checked = self.isChecked()
        middle = self.height() / 2
        track = QRectF(1, middle - 8, 30, 16)
        painter.setPen(QColor("#5180cd" if self.hasFocus() else "#aebdd6" if not checked else "#3b64ac"))
        painter.setBrush(QColor("#3970bd" if checked and enabled else "#e0e9f8"))
        painter.drawRoundedRect(track, 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff" if enabled else "#f4f7fb"))
        painter.drawEllipse(QRectF(17 if checked else 3, middle - 6, 12, 12))
        painter.setPen(QColor("#294369" if enabled else "#687a94"))
        text_rect = QRect(41, 0, max(0, self.width() - 41), self.height())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()


class ConnectorPicker(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#486a9a" if self.isEnabled() else "#8294b0"),
                            1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 15, self.height() / 2
        painter.drawPolyline([QPointF(x - 4, y - 2), QPointF(x, y + 2), QPointF(x + 4, y - 2)])
        painter.end()


def surface(kind="paper"):
    widget = QFrame()
    widget.setProperty("surface", kind)
    return widget


@lru_cache(maxsize=10)
def _sprite(phase, size):
    path = Path(__file__).parent / "characters" / "dafeiyu"
    try:
        manifest = json.loads((path / "atlas.json").read_text(encoding="utf-8"))
        frame = manifest["frames"][manifest["phases"][phase][0]]
        atlas = QImage(str(path / manifest["image"]))
        art = atlas.copy(QRect(*frame["rect"]))
        art = art.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        art.setDevicePixelRatio(2)
        return art
    except (OSError, KeyError, ValueError, IndexError):
        return QImage()


def character(phase, size):
    portrait = QLabel()
    portrait.setFixedSize(size, size)
    portrait.setAlignment(Qt.AlignCenter)
    portrait.setPixmap(QPixmap.fromImage(_sprite(phase, size)))
    return portrait


def header(title, phase="idle", *, subtitle="", metric=None, art_size=58):
    banner = surface("hero")
    layout = QHBoxLayout(banner)
    layout.setContentsMargins(17, 8, 14, 8)
    layout.setSpacing(14)
    names = QVBoxLayout()
    names.setAlignment(Qt.AlignVCenter)
    names.setSpacing(3)
    names.addWidget(label(title, "heading"))
    caption = label(subtitle, "muted", wrap=True)
    caption.setVisible(bool(subtitle))
    names.addWidget(caption)
    layout.addLayout(names, 1)
    if metric:
        layout.addWidget(metric)
    layout.addWidget(character(phase, art_size))
    return banner, caption


SUBTITLE = Qt.ItemDataRole.UserRole + 1


class CardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 56)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rectangle = QRectF(option.rect).adjusted(1, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.setBrush(QColor("#e5efff" if selected else "#f0f5ff" if hovered else "#f6f9ff"))
        painter.setPen(QColor("#6a8fc9" if option.state & QStyle.State_HasFocus
                              else "#c2d6f4" if selected else "#e7eef9"))
        painter.drawRoundedRect(rectangle, 10, 10)

        area = rectangle.adjusted(12, 0, -10, 0)
        title = QFont(option.font)
        title.setPixelSize(13)
        title.setWeight(QFont.DemiBold)
        painter.setFont(title)
        painter.setPen(QColor("#234a83" if selected else "#243957"))
        name = QFontMetrics(title).elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, int(area.width()))
        painter.drawText(area.adjusted(0, 6, 0, -25), Qt.AlignVCenter | Qt.AlignLeft, name)

        subtitle = QFont(option.font)
        subtitle.setPixelSize(11)
        painter.setFont(subtitle)
        painter.setPen(QColor("#536783"))
        meta = QFontMetrics(subtitle).elidedText(index.data(SUBTITLE) or "", Qt.ElideRight, int(area.width()))
        painter.drawText(area.adjusted(0, 26, 0, -5), Qt.AlignVCenter | Qt.AlignLeft, meta)
        painter.restore()


def card_list(name):
    widget = QListWidget()
    widget.setAccessibleName(name)
    widget.setMouseTracking(True)
    widget.setUniformItemSizes(True)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
    widget.setItemDelegate(CardDelegate(widget))
    widget.setMinimumHeight(56)
    return widget


def add_card(widget, title, subtitle, *, value=None):
    item = QListWidgetItem(title)
    item.setData(SUBTITLE, subtitle)
    item.setData(Qt.AccessibleTextRole, f"{title}，{subtitle}")
    item.setData(Qt.UserRole, value)
    item.setToolTip(title)
    widget.addItem(item)
