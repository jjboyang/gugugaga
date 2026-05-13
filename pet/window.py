"""Transparent, always-on-top, draggable pet window."""
import ctypes
import json
import math
import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QColor,
    QBrush,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton, QSlider,
)


# Logical pet footprint (sprites scale to fit). 30% smaller than the prior 200px default.
DEFAULT_PET_SIZE = 140
MIN_PET_SIZE = 80
MAX_PET_SIZE = 300

# Movement below this (logical px) counts as a tap, not a drag.
_DRAG_COMMIT_THRESHOLD_PX = 12

_CONFIG_PATH = Path.home() / ".desktop-pet-config.json"


def _load_config():
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_config(data):
    _CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


class PetWindow(QWidget):
    quit_requested = Signal()
    drag_started = Signal()
    drag_ended = Signal()
    hook_config_requested = Signal()
    pet_tapped = Signal()
    question_answered = Signal(str)  # selected option label
    waddle_completed = Signal()

    def __init__(self, parent=None, debug=False):
        super().__init__(parent)
        self._debug = debug

        config = _load_config()
        self._pet_size = config.get("pet_size", DEFAULT_PET_SIZE)
        self._pet_size = max(MIN_PET_SIZE, min(MAX_PET_SIZE, self._pet_size))

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
        self.setFixedSize(self._pet_size, self._pet_size)

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
        self.label.setFixedSize(self._pet_size, self._pet_size)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAttribute(Qt.WA_TranslucentBackground)
        self.label.setStyleSheet("background: transparent;")
        self.label.setGeometry(0, 0, self._pet_size, self._pet_size)

        # Try to drop the Windows DWM drop-shadow that some compositors keep
        # drawing around frameless top-level windows. Best-effort; safe if it
        # fails (e.g. non-Windows, older Win10 builds).
        self._disable_windows_shadow()
        self._disable_mac_shadow()

        self._drag_offset = QPoint()
        self._dragging = False
        self._left_down = False
        self._press_global = QPoint()
        self._last_global_pos = QPoint()
        # Smoothed horizontal drag velocity → pendulum-like sway angle (degrees).
        self._sway_velocity_smooth = 0.0
        self._sway_angle = 0.0
        # Belly triple-tap easter egg
        self._belly_tap_times = []
        self._speech_popup = None
        self._question_popup = None
        self._settings_popup = None
        self._last_scaled_pixmap = QPixmap()
        self._last_original_pixmap = QPixmap()
        self._waddle_move_timer = QTimer(self)
        self._waddle_move_timer.timeout.connect(self._waddle_tick)
        self._waddle_anim = {}

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

    def _disable_mac_shadow(self):
        """Remove NSWindow shadow and enforce transparent background."""
        if sys.platform != "darwin":
            return
        try:
            objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.A.dylib")

            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]

            msg_addr = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

            # (id, SEL) -> id
            _SID = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            send_id = _SID(msg_addr)

            # (id, SEL, BOOL) -> void
            _SVB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
            send_void_bool = _SVB(msg_addr)

            # (id, SEL, id) -> void
            _SVI = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            send_void_id = _SVI(msg_addr)

            view = ctypes.c_void_p(int(self.winId()))
            sel_window = objc.sel_registerName(b"window")
            window = send_id(view, sel_window)

            if not window:
                return

            # [window setHasShadow:NO]
            send_void_bool(window, objc.sel_registerName(b"setHasShadow:"), ctypes.c_bool(False))

            # [window setOpaque:NO]
            send_void_bool(window, objc.sel_registerName(b"setOpaque:"), ctypes.c_bool(False))

            # [window setBackgroundColor:[NSColor clearColor]]
            cls_color = objc.objc_getClass(b"NSColor")
            sel_clear = objc.sel_registerName(b"clearColor")
            clear_color = send_id(cls_color, sel_clear)
            if clear_color:
                send_void_id(window, objc.sel_registerName(b"setBackgroundColor:"), clear_color)
        except (OSError, AttributeError):
            pass

    def showEvent(self, event):
        # Some DWM attributes only stick once the window has a composited
        # surface, so re-apply them on first show.
        super().showEvent(event)
        self._disable_windows_shadow()
        self._disable_mac_shadow()

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
        self._last_original_pixmap = pixmap
        scaled = pixmap.scaled(
            self._pet_size, self._pet_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
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
            self._pet_size,
            self._pet_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.label.setPixmap(rotated)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._waddle_move_timer.stop()
            self._waddle_anim = {}
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
                self._check_belly_tap(event.position().toPoint())

    # --- Belly triple-tap easter egg ---
    _BELLY_Y_MIN_RATIO = 0.55
    _BELLY_TAP_WINDOW_S = 1.5
    _BELLY_TAP_COUNT = 3

    def _check_belly_tap(self, pos):
        """Detect triple-tap on the belly area."""
        belly_y = int(self._pet_size * self._BELLY_Y_MIN_RATIO)
        if pos.y() < belly_y:
            return

        now = time.monotonic()
        self._belly_tap_times = [t for t in self._belly_tap_times if now - t < self._BELLY_TAP_WINDOW_S]
        self._belly_tap_times.append(now)

        if len(self._belly_tap_times) >= self._BELLY_TAP_COUNT:
            self._belly_tap_times.clear()
            self._show_speech_bubble("咕咕嘎嘎")

    def _show_speech_bubble(self, text):
        """Show a speech bubble above the pet that auto-dismisses."""
        # Close previous bubble if still visible
        if self._speech_popup is not None:
            try:
                self._speech_popup.close()
            except RuntimeError:
                pass
            self._speech_popup = None

        popup = QWidget(None, Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setAttribute(Qt.WA_ShowWithoutActivating)
        popup.setStyleSheet("""
            QWidget#speechBubble {
                background: rgba(40, 40, 40, 0.90);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                font-size: 18px;
                font-weight: bold;
                padding: 10px 18px;
            }
        """)

        panel = QWidget(popup)
        panel.setObjectName("speechBubble")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 2, 4, 2)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        panel_layout = QVBoxLayout(popup)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(panel)

        popup.adjustSize()

        pet_geom = self.frameGeometry()
        popup_x = pet_geom.center().x() - popup.width() // 2
        popup_y = pet_geom.top() - popup.height() - 6

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            if popup_x < avail.left():
                popup_x = avail.left() + 4
            elif popup_x + popup.width() > avail.right():
                popup_x = avail.right() - popup.width() - 4
            if popup_y < avail.top():
                popup_y = pet_geom.bottom() + 6

        popup.move(popup_x, popup_y)
        popup.show()
        self._speech_popup = popup
        QTimer.singleShot(2200, self._dismiss_speech_bubble)

    def _dismiss_speech_bubble(self):
        if self._speech_popup is not None:
            try:
                self._speech_popup.close()
            except RuntimeError:
                pass
            self._speech_popup = None

    # --- Waddle to center ---
    _WADDLE_ACTIVE_MOVE_S = 4.5       # total active movement time (excluding pauses)
    _WADDLE_INTERVAL_MS = 16
    _WADDLE_FREQ_HZ = 1.8
    _WADDLE_AMPLITUDE_PX = 18.0
    _WADDLE_ROTATION_DEG = 8.0
    _WADDLE_PAUSE_MIN_S = 0.3
    _WADDLE_PAUSE_MAX_S = 1.0
    _WADDLE_BURST_MIN = 0.06           # min progress per move burst
    _WADDLE_BURST_MAX = 0.18           # max progress per move burst

    def stop_waddle(self):
        self._waddle_move_timer.stop()
        self._waddle_anim = {}
        self._sway_angle = 0.0
        self._apply_label_pixmap()

    def start_waddle(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        geom = screen.availableGeometry()
        target_x = geom.x() + (geom.width() - self.width()) // 2
        target_y = geom.y() + (geom.height() - self.height()) // 2

        import random
        rng = random.Random()
        first_pause = rng.uniform(self._WADDLE_BURST_MIN, self._WADDLE_BURST_MAX)

        now = time.monotonic()
        self._waddle_anim = {
            "start_x": self.x(),
            "start_y": self.y(),
            "target_x": target_x,
            "target_y": target_y,
            "progress": 0.0,
            "active_elapsed": 0.0,
            "paused_until": 0.0,
            "next_pause_at": first_pause,
            "move_speed": 1.0 / self._WADDLE_ACTIVE_MOVE_S,
            "last_tick": now,
        }
        self._waddle_move_timer.start(self._WADDLE_INTERVAL_MS)

    def _waddle_tick(self):
        state = self._waddle_anim
        if not state:
            self._waddle_move_timer.stop()
            return

        now = time.monotonic()
        dt = now - state["last_tick"]
        state["last_tick"] = now

        # --- paused: hold position with subtle idle sway ---
        if now < state["paused_until"]:
            idle_phase = now * 1.2 * 2 * math.pi
            self._sway_angle = math.sin(idle_phase) * 2.5
            self._apply_label_pixmap()
            return

        # --- moving ---
        state["active_elapsed"] += dt
        state["progress"] += state["move_speed"] * dt

        if state["progress"] >= 1.0:
            self.move(state["target_x"], state["target_y"])
            self._sway_angle = 0.0
            self._apply_label_pixmap()
            self._waddle_move_timer.stop()
            self._waddle_anim = {}
            self.waddle_completed.emit()
            return

        # --- decide whether to pause ---
        if state["progress"] >= state["next_pause_at"] and state["progress"] < 0.92:
            import random
            rng = random.Random()
            state["paused_until"] = now + rng.uniform(
                self._WADDLE_PAUSE_MIN_S, self._WADDLE_PAUSE_MAX_S
            )
            state["next_pause_at"] = min(
                state["progress"] + rng.uniform(self._WADDLE_BURST_MIN, self._WADDLE_BURST_MAX),
                0.98,
            )
            return

        # --- move with wobble ---
        t = state["progress"]
        if t < 0.5:
            ease = 2.0 * t * t
        else:
            ease = -1.0 + (4.0 - 2.0 * t) * t

        cur_x = state["start_x"] + (state["target_x"] - state["start_x"]) * ease
        cur_y = state["start_y"] + (state["target_y"] - state["start_y"]) * ease

        decay = 1.0 - t
        wobble_phase = state["active_elapsed"] * self._WADDLE_FREQ_HZ * 2 * math.pi
        wobble_offset = math.sin(wobble_phase) * self._WADDLE_AMPLITUDE_PX * decay
        rotation = math.cos(wobble_phase) * self._WADDLE_ROTATION_DEG * decay

        self.move(int(cur_x + wobble_offset), int(cur_y))
        self._sway_angle = rotation
        self._apply_label_pixmap()

    def contextMenuEvent(self, event):
        popup = QWidget(None, Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setAttribute(Qt.WA_ShowWithoutActivating)
        popup.setStyleSheet("""
            QWidget#menuPanel {
                background: rgba(30, 30, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 10px;
            }
            QPushButton {
                color: #e0e0e0;
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 14px;
                text-align: left;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.06);
            }
        """)

        panel = QWidget(popup)
        panel.setObjectName("menuPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        settings_btn = QPushButton("设置")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(lambda: self._on_menu_action(popup, "settings"))
        layout.addWidget(settings_btn)

        sep1 = QWidget()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background: rgba(255,255,255,0.10); margin: 3px 8px;")
        layout.addWidget(sep1)

        hook_btn = QPushButton("配置Hook")
        hook_btn.setCursor(Qt.PointingHandCursor)
        hook_btn.clicked.connect(lambda: self._on_menu_action(popup, "hook"))
        layout.addWidget(hook_btn)

        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: rgba(255,255,255,0.10); margin: 3px 8px;")
        layout.addWidget(sep2)

        quit_btn = QPushButton("退出")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(lambda: self._on_menu_action(popup, "quit"))
        layout.addWidget(quit_btn)

        panel_layout = QVBoxLayout(popup)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(panel)

        popup.adjustSize()

        pet_geom = self.frameGeometry()
        popup_x = pet_geom.right() + 8
        popup_y = pet_geom.top()

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            if popup_x + popup.width() > avail.right():
                popup_x = pet_geom.left() - popup.width() - 8
            if popup_y + popup.height() > avail.bottom():
                popup_y = avail.bottom() - popup.height()

        popup.move(popup_x, popup_y)
        popup.show()

    def _on_menu_action(self, popup, action):
        popup.close()
        if action == "settings":
            self._show_settings_popup()
        elif action == "hook":
            self.hook_config_requested.emit()
        elif action == "quit":
            self.quit_requested.emit()

    def _show_settings_popup(self):
        if self._settings_popup is not None:
            try:
                self._settings_popup.close()
            except RuntimeError:
                pass
            self._settings_popup = None

        popup = QWidget(None, Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setAttribute(Qt.WA_ShowWithoutActivating)
        popup.setStyleSheet("""
            QWidget#settingsPanel {
                background: rgba(30, 30, 30, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 12px;
            }
            QLabel#settingsTitle {
                color: #ffffff;
                font-size: 15px;
                font-weight: bold;
            }
            QLabel#sizeValue {
                color: #cccccc;
                font-size: 14px;
                min-width: 40px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -5px 0;
                background: #ffffff;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(255, 255, 255, 0.25);
                border-radius: 3px;
            }
        """)

        panel = QWidget(popup)
        panel.setObjectName("settingsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("人物大小")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(MIN_PET_SIZE)
        slider.setMaximum(MAX_PET_SIZE)
        slider.setValue(self._pet_size)
        slider.setPageStep(10)
        slider.setCursor(Qt.PointingHandCursor)
        row.addWidget(slider, 1)

        value_label = QLabel(str(self._pet_size))
        value_label.setObjectName("sizeValue")
        row.addWidget(value_label)

        layout.addLayout(row)

        panel_layout = QVBoxLayout(popup)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(panel)

        popup.adjustSize()
        popup.setFixedWidth(240)

        pet_geom = self.frameGeometry()
        popup_x = pet_geom.right() + 8
        popup_y = pet_geom.top()

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            if popup_x + popup.width() > avail.right():
                popup_x = pet_geom.left() - popup.width() - 8
            if popup_y + popup.height() > avail.bottom():
                popup_y = avail.bottom() - popup.height()

        popup.move(popup_x, popup_y)

        def on_slider_changed(value):
            value_label.setText(str(value))
            self._on_size_changed(value)

        slider.valueChanged.connect(on_slider_changed)
        self._settings_popup = popup
        popup.show()

    def _on_size_changed(self, size):
        self._pet_size = size
        self.setFixedSize(size, size)
        self.label.setFixedSize(size, size)
        self.label.setGeometry(0, 0, size, size)
        if not self._last_original_pixmap.isNull():
            scaled = self._last_original_pixmap.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._last_scaled_pixmap = scaled
            self._apply_label_pixmap()
        _save_config({"pet_size": size})

    def show_question(self, text, options):
        popup = QWidget(None, Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setAttribute(Qt.WA_ShowWithoutActivating)
        popup.setStyleSheet("""
            QWidget#questionPanel {
                background: rgba(30, 30, 30, 0.94);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 12px;
            }
            QLabel#questionText {
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 2px 4px;
            }
            QPushButton {
                color: #e0e0e0;
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 13px;
                text-align: left;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.08);
            }
        """)

        panel = QWidget(popup)
        panel.setObjectName("questionPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        max_width = 260

        qlabel = QLabel(text)
        qlabel.setObjectName("questionText")
        qlabel.setWordWrap(True)
        qlabel.setMaximumWidth(max_width)
        layout.addWidget(qlabel)

        for opt in options:
            label = opt.get("label", "")
            desc = opt.get("description", "")
            btn_text = label if not desc else f"{label}\n{desc}"

            btn = QPushButton(btn_text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMaximumWidth(max_width)

            def make_handler(selected_label):
                return lambda: self._on_question_action(popup, selected_label)

            btn.clicked.connect(make_handler(label))
            layout.addWidget(btn)

        panel_layout = QVBoxLayout(popup)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(panel)

        popup.adjustSize()

        pet_geom = self.frameGeometry()
        popup_x = pet_geom.right() + 8
        popup_y = pet_geom.top()

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            if popup_x + popup.width() > avail.right():
                popup_x = pet_geom.left() - popup.width() - 8
            if popup_y + popup.height() > avail.bottom():
                popup_y = avail.bottom() - popup.height()
            if popup_y < avail.top():
                popup_y = avail.top()

        popup.move(popup_x, popup_y)
        # Close previous question popup if still visible
        if self._question_popup is not None:
            try:
                self._question_popup.close()
            except RuntimeError:
                pass
        self._question_popup = popup
        popup.show()

    def _on_question_action(self, popup, selected):
        self._question_popup = None
        popup.close()
        self.question_answered.emit(selected)
