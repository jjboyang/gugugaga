"""Transparent, always-on-top, draggable pet window."""
import math
import sys
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import (
    QAction,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QColor,
    QBrush,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QWidget, QLabel, QMenu


# Logical pet footprint (sprites scale to fit). 30% smaller than the prior 200px default.
WINDOW_SIZE = 140

# Movement below this (logical px) counts as a tap, not a drag.
_DRAG_COMMIT_THRESHOLD_PX = 12


class PetWindow(QWidget):
    quit_requested = Signal()
    drag_started = Signal()
    drag_ended = Signal()
    hook_config_requested = Signal()
    pet_tapped = Signal()

    def __init__(self, parent=None, debug=False):
        super().__init__(parent)
        self._debug = debug
        # On macOS, Qt.Tool maps to NSPanel which is auto-hidden when the
        # owning app loses activation. Combined with WA_ShowWithoutActivating
        # the window may never appear. Use a plain top-level window there.
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if sys.platform != "darwin":
            flags |= Qt.Tool
        self.setWindowFlags(flags)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)

        # availableGeometry() is in global coordinates; on macOS / multi-monitor
        # setups x() and y() are non-zero and must be included, otherwise the
        # window can land off-screen. Fall back to the primary screen if the
        # widget isn't yet attached to one (can happen before show()).
        screen = self.screen() or QGuiApplication.primaryScreen()
        geom = screen.availableGeometry()
        margin = 30
        self.move(
            geom.x() + geom.width() - self.width() - margin,
            geom.y() + geom.height() - self.height() - margin,
        )

        self.label = QLabel(self)
        self.label.setFixedSize(WINDOW_SIZE, WINDOW_SIZE)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAttribute(Qt.WA_TranslucentBackground)
        self.label.setStyleSheet("background: transparent;")
        self.label.setGeometry(0, 0, WINDOW_SIZE, WINDOW_SIZE)

        # Try to drop the Windows DWM drop-shadow that some compositors keep
        # drawing around frameless top-level windows. Best-effort; safe if it
        # fails (e.g. non-Windows, older Win10 builds).
        self._disable_windows_shadow()

        self._drag_offset = QPoint()
        self._dragging = False
        self._left_down = False
        self._press_global = QPoint()
        self._last_global_pos = QPoint()
        # Smoothed horizontal drag velocity → pendulum-like sway angle (degrees).
        self._sway_velocity_smooth = 0.0
        self._sway_angle = 0.0
        self._last_scaled_pixmap = QPixmap()

    def _disable_windows_shadow(self):
        """Strip every DWM decoration Windows 11 still draws around frameless
        translucent windows: drop shadow, 1px non-client border, rounded
        corner outline, and any extended client-area frame."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            HWND = wintypes.HWND(hwnd)

            # 1) Disable non-client rendering (kills the drop shadow / glow).
            DWMWA_NCRENDERING_POLICY = 2
            DWMNCRP_DISABLED = 1
            v = ctypes.c_int(DWMNCRP_DISABLED)
            dwm.DwmSetWindowAttribute(
                HWND, wintypes.DWORD(DWMWA_NCRENDERING_POLICY),
                ctypes.byref(v), ctypes.sizeof(v))

            # 2) Don't extend any DWM frame into the client area.
            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth",   ctypes.c_int),
                    ("cxRightWidth",  ctypes.c_int),
                    ("cyTopHeight",   ctypes.c_int),
                    ("cyBottomHeight",ctypes.c_int),
                ]
            margins = MARGINS(0, 0, 0, 0)
            dwm.DwmExtendFrameIntoClientArea(HWND, ctypes.byref(margins))

            # 3) Windows 11 22000+: explicitly hide the thin border outline.
            DWMWA_BORDER_COLOR = 34
            DWMWA_COLOR_NONE   = 0xFFFFFFFE  # special: no border drawn at all
            bc = ctypes.c_uint32(DWMWA_COLOR_NONE)
            dwm.DwmSetWindowAttribute(
                HWND, wintypes.DWORD(DWMWA_BORDER_COLOR),
                ctypes.byref(bc), ctypes.sizeof(bc))

            # 4) Windows 11 22000+: square corners (default rounding can look
            #    like a faint outlined rectangle around translucent windows).
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            cp = ctypes.c_int(DWMWCP_DONOTROUND)
            dwm.DwmSetWindowAttribute(
                HWND, wintypes.DWORD(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(cp), ctypes.sizeof(cp))
        except (OSError, AttributeError):
            # Older Windows builds without these attributes - harmless.
            pass

    def showEvent(self, event):
        # Some DWM attributes only stick once the window has a composited
        # surface, so re-apply them on first show.
        super().showEvent(event)
        self._disable_windows_shadow()

    def paintEvent(self, event):
        # Normal mode: draw nothing so only the sprite shows. Debug mode keeps
        # a high-contrast outline so the window is visible without a sprite.
        if self._debug:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(255, 0, 0, 80))
            painter.setPen(QColor(255, 0, 0, 255))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
            painter.end()
        super().paintEvent(event)

    def set_pixmap(self, pixmap: QPixmap):
        scaled = pixmap.scaled(
            WINDOW_SIZE, WINDOW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._last_scaled_pixmap = scaled
        self._apply_label_pixmap()

    def _apply_label_pixmap(self):
        """Apply optional drag sway rotation to the last scaled sprite."""
        pm = self._last_scaled_pixmap
        if pm.isNull():
            return
        # During drag, apply rotation once tilt exceeds ~0.25° (below that looks flat).
        if not self._dragging or abs(self._sway_angle) < 0.25:
            self.label.setPixmap(pm)
            return
        t = QTransform()
        t.translate(pm.width() / 2.0, pm.height() / 2.0)
        t.rotate(self._sway_angle)
        t.translate(-pm.width() / 2.0, -pm.height() / 2.0)
        rotated = pm.transformed(t, Qt.SmoothTransformation)
        rotated = rotated.scaled(
            WINDOW_SIZE,
            WINDOW_SIZE,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.label.setPixmap(rotated)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._left_down = True
            self._dragging = False
            self._press_global = event.globalPosition().toPoint()
            self._last_global_pos = self._press_global
            self._sway_velocity_smooth = 0.0
            self._sway_angle = 0.0

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton:
            cur = event.globalPosition().toPoint()
            if self._left_down and not self._dragging:
                moved = max(
                    abs(cur.x() - self._press_global.x()),
                    abs(cur.y() - self._press_global.y()),
                )
                if moved >= _DRAG_COMMIT_THRESHOLD_PX:
                    self._dragging = True
                    self._last_global_pos = cur
                    try:
                        self.grabMouse()
                    except Exception:
                        pass
                    self.drag_started.emit()

            if not self._dragging:
                return

            dx = cur.x() - self._last_global_pos.x()
            dy = cur.y() - self._last_global_pos.y()
            self._last_global_pos = cur

            # Drive sway from BOTH axes: purely vertical drags often have dx≈0 and looked "dead".
            # Horizontal dominates; vertical contributes ~35% so diagonal / vertical drag still rocks.
            combined = 1.35 * float(dx) + 0.42 * float(dy)
            self._sway_velocity_smooth = (
                0.58 * self._sway_velocity_smooth + 0.42 * combined
            )

            sens = 0.95
            max_deg = 26.0
            target = max(
                -max_deg,
                min(max_deg, self._sway_velocity_smooth * sens),
            )
            # Faster angle response so rotation is obvious while dragging.
            self._sway_angle = 0.38 * self._sway_angle + 0.62 * target

            # Gentle settle only when the pointer really stopped (no micro-jitter kill).
            speed = math.hypot(float(dx), float(dy))
            if speed < 0.35:
                self._sway_angle *= 0.91
                self._sway_velocity_smooth *= 0.88

            self.move(cur - self._drag_offset)
            self._apply_label_pixmap()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            was_drag = self._dragging
            self._left_down = False
            self._drag_offset = QPoint()
            self._dragging = False
            self._sway_velocity_smooth = 0.0
            self._sway_angle = 0.0
            try:
                self.releaseMouse()
            except Exception:
                pass
            self._apply_label_pixmap()
            if was_drag:
                self.drag_ended.emit()
            else:
                self.pet_tapped.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_TranslucentBackground, False)

        hook_act = QAction("配置Hook", menu)
        hook_act.triggered.connect(self.hook_config_requested.emit)
        menu.addAction(hook_act)

        menu.addSeparator()

        quit_act = QAction("退出", menu)
        quit_act.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_act)
        menu.exec(event.globalPos())
