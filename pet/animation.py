"""Animation state machine and sprite frame controller."""
import os
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap


SPRITES_DIR = os.path.join(os.path.dirname(__file__), "sprites")

# After reading/writing with no new IPC for this long → "thinking" (between tools).
_GAP_TO_THINKING_MS = 3000
# After user submit ("question"), switch to thinking so the pet matches model reasoning
# before the first tool hook fires (hooks never send "thinking" directly).
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

# Phases where prolonged silence should eventually mean "turn finished".
_SILENCE_IDLE_PHASES = frozenset(
    {"question", "reading", "thinking", "writing", "executing"}
)

STATE_CONFIG = {
    "idle":      {"interval": 150, "loops": True},
    "question":  {"interval": 80,  "loops": False},
    "reading":   {"interval": 120, "loops": True},
    "thinking":  {"interval": 120, "loops": True},
    "writing":   {"interval": 100, "loops": True},
    "executing": {"interval": 80,  "loops": True},
    "done":      {"interval": 100, "loops": False},
    # Local interaction-only state shown while the user is dragging the pet.
    "dragged":   {"interval": 110, "loops": True},
}


class AnimationEngine(QObject):
    frame_changed = Signal(QPixmap)

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

        self._load_all_sprites()

    def _load_all_sprites(self):
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

    def _fallback_pixmap(self, phase):
        """Generate a 150x150 solid-color placeholder."""
        from PySide6.QtGui import QPainter, QColor, QFont
        pixmap = QPixmap(150, 150)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        colors = {
            "idle": "#3498db", "question": "#f39c12", "reading": "#2ecc71",
            "thinking": "#9b59b6", "writing": "#e74c3c", "executing": "#1abc9c",
            "done": "#f1c40f",
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
            return

        self._thinking_timer.stop()
        self._done_timer.stop()

        self.current_phase = phase
        self.frame_index = 0
        self.timer.start(STATE_CONFIG[phase]["interval"])
        self._emit_frame()

        if phase in ("reading", "writing"):
            self._thinking_timer.start(_GAP_TO_THINKING_MS)
        elif phase == "question":
            self._thinking_timer.start(_QUESTION_TO_THINKING_MS)

        self._schedule_silence_idle(phase)

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
        self._emit_frame()

    def _emit_frame(self):
        frames = self.frames[self.current_phase]
        if frames:
            self.frame_changed.emit(frames[self.frame_index])
