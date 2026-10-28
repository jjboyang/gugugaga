"""Animation state machine and sprite frame controller."""
import json
import os
import time
from PySide6.QtCore import QObject, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPixmap


SPRITES_DIR = os.path.join(os.path.dirname(__file__), "sprites")

# After reading/writing with no new IPC for this long → "thinking" (between tools).
_GAP_TO_THINKING_MS = 3000
# After user submit ("question"), switch to thinking until the first tool signal arrives.
# PostToolBatch also sends "thinking" between tool batches (see pet_app PET_HOOKS_TEMPLATE).
_QUESTION_TO_THINKING_MS = 1200
# After "done" animation finishes, wait this long then switch to idle.
_DONE_TO_IDLE_MS = 3000


def _env_ms(name, default):
    try:
        v = int(os.environ.get(name, str(default)))
        return max(0, v)
    except ValueError:
        return default


# If hooks never send idle/done, still return to idle after this much quiet time
# on active phases. Set DESKTOP_PET_SILENCE_IDLE_MS=0 to disable.
_DEFAULT_SILENCE_IDLE_MS = 25000

# After this long in *idle* with no IPC / local activity → sleep (local only).
_DEFAULT_IDLE_TO_SLEEP_MS = 20000
# After this long in *sleep* → waddle to screen center.
_DEFAULT_SLEEP_TO_WADDLE_MS = 20000

# Rapid taps (short clicks, not drags) within this window → angry.
_ANGRY_TAP_WINDOW_S = 1.35
_ANGRY_TAP_COUNT = 4

# Phases where prolonged silence should eventually mean "turn finished".
_SILENCE_IDLE_PHASES = frozenset(
    {"question", "reading", "thinking", "writing", "executing"}
)

STATE_CONFIG = {
    "idle":      {"interval": 380, "loops": True},
    "question":  {"interval": 200, "loops": False},
    "reading":   {"interval": 320, "loops": True},
    "thinking":  {"interval": 320, "loops": True},
    "writing":   {"interval": 260, "loops": True},
    "executing": {"interval": 200, "loops": True},
    "done":      {"interval": 250, "loops": False},
    # Local-only: deep idle / annoyance / drag.
    "sleep":     {"interval": 450, "loops": True},
    "angry":     {"interval": 180, "loops": False},
    "dragged":   {"interval": 280, "loops": True},
    "waddle":    {"interval": 100, "loops": True},
}


class AnimationEngine(QObject):
    frame_changed = Signal(QPixmap)
    waddle_started = Signal()
    waddle_cancelled = Signal()

    def __init__(self, sprites_dir=SPRITES_DIR, parent=None):
        super().__init__(parent)
        self.sprites_dir = sprites_dir
        self.frames = {}          # phase -> [QPixmap, ...]
        # None (not "idle") so the very first set_state("idle") call from main
        # actually starts the timer and emits frame 0 instead of being treated
        # as a no-op redundant transition.
        self.current_phase = None
        self.frame_index = 0
        # When the user is dragging the pet, we display the "dragged" pose
        # and remember whatever phase IPC last requested so we can restore it
        # on release.
        self._is_dragging = False
        self._pre_drag_phase = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self._thinking_timer = QTimer(self)
        self._thinking_timer.setSingleShot(True)
        self._thinking_timer.timeout.connect(self._on_thinking_timeout)

        self._done_timer = QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(lambda: self.set_state("idle"))

        self._silence_idle_timer = QTimer(self)
        self._silence_idle_timer.setSingleShot(True)
        self._silence_idle_timer.timeout.connect(self._on_silence_idle)

        self._silence_to_idle_ms = _env_ms(
            "DESKTOP_PET_SILENCE_IDLE_MS", _DEFAULT_SILENCE_IDLE_MS
        )
        self._idle_to_sleep_ms = _env_ms(
            "DESKTOP_PET_IDLE_SLEEP_MS", _DEFAULT_IDLE_TO_SLEEP_MS
        )
        self._sleep_to_waddle_ms = _env_ms(
            "DESKTOP_PET_SLEEP_WADDLE_MS", _DEFAULT_SLEEP_TO_WADDLE_MS
        )

        self._idle_sleep_timer = QTimer(self)
        self._idle_sleep_timer.setSingleShot(True)
        self._idle_sleep_timer.timeout.connect(self._on_idle_sleep_timeout)

        self._waddle_timer = QTimer(self)
        self._waddle_timer.setSingleShot(True)
        self._waddle_timer.timeout.connect(self._on_sleep_waddle_timeout)

        self._angry_done_timer = QTimer(self)
        self._angry_done_timer.setSingleShot(True)
        self._angry_done_timer.timeout.connect(self._to_idle_after_angry)

        self._tap_times = []

        self._load_all_sprites()

    def _load_all_sprites(self):
        atlas_path = os.path.join(self.sprites_dir, "atlas.json")
        if os.path.isfile(atlas_path):
            self.frames = self._load_sprite_atlas(atlas_path)
            return

        for phase in STATE_CONFIG:
            phase_dir = os.path.join(self.sprites_dir, phase)
            pixmaps = []
            if os.path.isdir(phase_dir):
                for fname in sorted(os.listdir(phase_dir)):
                    if fname.endswith(".png"):
                        path = os.path.join(phase_dir, fname)
                        pixmaps.append(QPixmap(path))
            if not pixmaps:
                pixmaps = [self._fallback_pixmap(phase)]
            self.frames[phase] = pixmaps

    def _load_sprite_atlas(self, manifest_path):
        """Read explicit single-character crops and align their body anchors.

        A shared canvas, scale and foot baseline keep changing poses in place.
        Directory-based characters continue to use the existing PNG loader.
        """
        with open(manifest_path, encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        atlas = QPixmap(os.path.join(self.sprites_dir, manifest["image"]))
        if atlas.isNull():
            raise ValueError(f"Cannot load sprite atlas: {manifest_path}")

        width, height = manifest["canvas_size"]
        scale = manifest["scale"]
        baseline = manifest["baseline"]
        if width <= 0 or height <= 0 or scale <= 0:
            raise ValueError("Sprite atlas canvas and scale must be positive")

        cells = []
        for frame in manifest["frames"]:
            rect = QRect(*frame["rect"])
            if rect.isEmpty() or not atlas.rect().contains(rect):
                raise ValueError("Sprite atlas frame lies outside its image")
            anchor_x, anchor_y = frame["anchor"]
            canvas = QPixmap(width, height)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.translate(width / 2, baseline)
            painter.scale(scale, scale)
            painter.drawPixmap(QPointF(-anchor_x, -anchor_y), atlas.copy(rect))
            painter.end()
            cells.append(canvas)

        frames = {}
        for phase in STATE_CONFIG:
            indices = manifest["phases"].get(phase, [])
            if not indices or any(
                not isinstance(index, int) or not 0 <= index < len(cells)
                for index in indices
            ):
                raise ValueError(f"Invalid sprite atlas frames for phase: {phase}")
            frames[phase] = [cells[index] for index in indices]
        return frames

    def _fallback_pixmap(self, phase):
        """Generate a 150x150 solid-color placeholder."""
        from PySide6.QtGui import QPainter, QColor, QFont
        pixmap = QPixmap(150, 150)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        colors = {
            "idle": "#3498db", "question": "#f39c12", "reading": "#2ecc71",
            "thinking": "#9b59b6", "writing": "#e74c3c", "executing": "#1abc9c",
            "done": "#f1c40f", "sleep": "#5d6d7e", "angry": "#c0392b",
            "waddle": "#2980b9",
        }
        color = QColor(colors.get(phase, "#95a5a6"))
        painter.setBrush(color)
        painter.setPen(QColor(0, 0, 0, 0))
        painter.drawEllipse(25, 25, 100, 100)
        painter.setPen(QColor("white"))
        font = QFont("Arial", 14)
        painter.setFont(font)
        painter.drawText(0, 0, 150, 150, Qt.AlignmentFlag.AlignCenter, phase)
        painter.end()
        return pixmap

    def set_state(self, phase):
        if phase not in self.frames:
            return

        # While the user is dragging the pet, external (IPC) state changes
        # are deferred — we just remember the latest requested phase and
        # restore it when the drag ends. The "dragged" state itself is
        # always allowed through.
        if self._is_dragging and phase != "dragged":
            self._pre_drag_phase = phase
            return

        # Same-phase IPC must not cancel pending done→idle or silence→idle timers.
        if phase == self.current_phase:
            if phase in ("reading", "writing"):
                self._thinking_timer.start(_GAP_TO_THINKING_MS)
                self._schedule_silence_idle(phase)
                return
            if phase == "question":
                self._thinking_timer.start(_QUESTION_TO_THINKING_MS)
                self._schedule_silence_idle(phase)
                return
            if phase == "done":
                if self._done_timer.isActive():
                    self._done_timer.start(_DONE_TO_IDLE_MS)
                return
            if phase in _SILENCE_IDLE_PHASES:
                self._schedule_silence_idle(phase)
                return
            if phase == "idle":
                self._schedule_idle_sleep()
                return
            if phase == "sleep":
                return
            if phase == "waddle":
                return
            return

        self._thinking_timer.stop()
        self._done_timer.stop()
        self._angry_done_timer.stop()

        if self.current_phase == "waddle" and phase != "waddle":
            self.waddle_cancelled.emit()

        if phase not in ("idle", "sleep", "angry", "dragged", "waddle"):
            self._tap_times.clear()

        self.current_phase = phase
        self.frame_index = 0
        self.timer.start(STATE_CONFIG[phase]["interval"])
        self._emit_frame()

        if phase in ("reading", "writing"):
            self._thinking_timer.start(_GAP_TO_THINKING_MS)
        elif phase == "question":
            self._thinking_timer.start(_QUESTION_TO_THINKING_MS)

        self._schedule_silence_idle(phase)
        if phase == "idle":
            self._schedule_idle_sleep()
        else:
            self._idle_sleep_timer.stop()

        if phase == "sleep":
            if self._sleep_to_waddle_ms > 0:
                self._waddle_timer.start(self._sleep_to_waddle_ms)
        elif phase != "waddle":
            self._waddle_timer.stop()

    def notify_user_activity(self):
        """Wake from sleep or reset the idle→sleep countdown (drag / tap)."""
        self._waddle_timer.stop()
        if self.current_phase == "sleep":
            self.set_state("idle")
            return
        if self.current_phase == "waddle":
            self.set_state("idle")
            return
        if self.current_phase == "idle":
            self._schedule_idle_sleep()

    def notify_pet_tap(self):
        """Short click on the pet — wakes from sleep and may trigger angry."""
        self.notify_user_activity()
        if self._is_dragging:
            return
        if self.current_phase != "idle":
            return
        now = time.monotonic()
        self._tap_times = [t for t in self._tap_times if now - t < _ANGRY_TAP_WINDOW_S]
        self._tap_times.append(now)
        if len(self._tap_times) >= _ANGRY_TAP_COUNT:
            self._tap_times.clear()
            self.set_state("angry")

    def _schedule_idle_sleep(self):
        self._idle_sleep_timer.stop()
        if self._idle_to_sleep_ms <= 0:
            return
        if self.current_phase == "idle":
            self._idle_sleep_timer.start(self._idle_to_sleep_ms)

    def _on_idle_sleep_timeout(self):
        if self.current_phase == "idle":
            self.set_state("sleep")

    def _on_sleep_waddle_timeout(self):
        if self.current_phase == "sleep":
            self.set_state("waddle")
            self.waddle_started.emit()

    def on_waddle_complete(self):
        if self.current_phase == "waddle":
            self.set_state("idle")

    def _to_idle_after_angry(self):
        if self.current_phase == "angry":
            self.set_state("idle")

    def _schedule_silence_idle(self, phase):
        self._silence_idle_timer.stop()
        if self._silence_to_idle_ms <= 0:
            return
        if phase in _SILENCE_IDLE_PHASES:
            self._silence_idle_timer.start(self._silence_to_idle_ms)

    def _on_silence_idle(self):
        self.set_state("idle")

    def begin_drag(self):
        if self._is_dragging:
            return
        self._is_dragging = True
        # Remember what we were doing so we can restore it on release.
        self._pre_drag_phase = self.current_phase or "idle"
        # Flip dragging on AFTER calling set_state below, otherwise the guard
        # at the top of set_state would block the transition we want.
        self._is_dragging = False
        self.set_state("dragged")
        self._is_dragging = True

    def end_drag(self):
        if not self._is_dragging:
            return
        self._is_dragging = False
        restore = self._pre_drag_phase or "idle"
        self._pre_drag_phase = None
        # Force a real transition even if restore happens to equal "dragged".
        if restore == self.current_phase:
            self.current_phase = None
        self.set_state(restore)

    def _on_thinking_timeout(self):
        self.set_state("thinking")

    def _tick(self):
        frames = self.frames[self.current_phase]
        loops = STATE_CONFIG[self.current_phase]["loops"]

        if self.frame_index < len(frames) - 1:
            self.frame_index += 1
        elif loops:
            self.frame_index = 0
        else:
            self.timer.stop()
            if self.current_phase == "done":
                self._done_timer.start(_DONE_TO_IDLE_MS)
                return
            elif self.current_phase == "question":
                return
            elif self.current_phase == "angry":
                self._angry_done_timer.start(450)
                return
        self._emit_frame()

    def _emit_frame(self):
        frames = self.frames[self.current_phase]
        if frames:
            self.frame_changed.emit(frames[self.frame_index])
