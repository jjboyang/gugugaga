# Desktop Pet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS desktop pet (penguin) that reflects Claude Code thinking phases via sprite animations, controlled through IPC signals from CC hooks.

**Architecture:** PySide6 app with three components — PetIPC (Unix socket listener in QThread), AnimationEngine (state machine + sprite frame controller), PetWindow (transparent always-on-top draggable window). IPC signals flow PetIPC → AnimationEngine.set_state → PetWindow.set_pixmap.

**Tech Stack:** Python 3.11+, PySide6, Pillow (placeholder sprites), Unix domain sockets

---

## File Map

| File | Role |
|------|------|
| `pet/__init__.py` | Empty init |
| `pet/ipc.py` | Unix socket server in QThread, emits `phase_changed(str)` |
| `pet/animation.py` | State machine, loads sprites, ticks frames, emits `frame_changed(QPixmap)` |
| `pet/window.py` | Transparent frameless always-on-top QWidget, drag handling, QLabel sprite display |
| `pet/generate_sprites.py` | Pillow script generating placeholder penguin PNGs for all 7 phases |
| `pet_app.py` | Main entry — creates window, engine, IPC; wires signals; starts event loop |
| `scripts/notify-pet.sh` | Shell one-liner for CC hooks |
| `requirements.txt` | PySide6, Pillow |

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `pet/__init__.py`
- Create: `scripts/notify-pet.sh`

- [ ] **Step 1: Create requirements.txt**

```txt
PySide6>=6.5.0
Pillow>=10.0.0
```

- [ ] **Step 2: Create pet/__init__.py**

Empty file.

- [ ] **Step 3: Create scripts/notify-pet.sh**

```bash
#!/bin/bash
echo "$1" | nc -U /tmp/desktop-pet.sock 2>/dev/null || true
```

- [ ] **Step 4: Make notify-pet.sh executable**

Run: `chmod +x scripts/notify-pet.sh`

- [ ] **Step 5: Install dependencies**

Run: `pip install PySide6 Pillow`

- [ ] **Step 6: Verify PySide6 can create a window**

Run: `python -c "from PySide6.QtWidgets import QApplication; print('OK')"`
Expected: `OK`

---

### Task 2: Placeholder Sprite Generator

**Files:**
- Create: `pet/generate_sprites.py`

- [ ] **Step 1: Write generate_sprites.py — penguin drawing functions**

```python
"""Generate placeholder penguin sprites for all 7 animation phases."""
import os
from PIL import Image, ImageDraw

SPRITES_DIR = os.path.join(os.path.dirname(__file__), "sprites")
SIZE = 150
PHASES = {
    "idle":      {"frames": 6,  "color": "#3498db"},
    "question":  {"frames": 4,  "color": "#f39c12"},
    "reading":   {"frames": 8,  "color": "#2ecc71"},
    "thinking":  {"frames": 8,  "color": "#9b59b6"},
    "writing":   {"frames": 4,  "color": "#e74c3c"},
    "executing": {"frames": 6,  "color": "#1abc9c"},
    "done":      {"frames": 4,  "color": "#f1c40f"},
}


def draw_penguin(draw, cx, cy, frame, total_frames, phase):
    """Draw a simple penguin at center (cx, cy) with pose variation."""
    import math

    # Body bob: gentle vertical oscillation
    bob = int(3 * math.sin(frame / total_frames * 2 * math.pi))
    body_top = cy - 35 + bob
    body_bot = cy + 40 + bob

    # Body (black ellipse)
    draw.ellipse(
        [cx - 30, body_top, cx + 30, body_bot],
        fill="#2C3E50", outline="#1a252f", width=2
    )

    # Belly (white ellipse)
    draw.ellipse(
        [cx - 18, body_top + 10, cx + 18, body_bot - 5],
        fill="#ECF0F1", outline="#bdc3c7", width=1
    )

    # Eyes vary by phase
    eye_y = body_top + 18
    if phase == "idle" and frame % 3 == 0:
        # Blink: horizontal lines
        draw.line([cx - 10, eye_y, cx - 4, eye_y], fill="#2C3E50", width=3)
        draw.line([cx + 4, eye_y, cx + 10, eye_y], fill="#2C3E50", width=3)
    elif phase == "question":
        # Wide eyes (surprised)
        draw.ellipse([cx - 11, eye_y - 4, cx - 3, eye_y + 3], fill="white")
        draw.ellipse([cx + 3, eye_y - 4, cx + 11, eye_y + 3], fill="white")
        draw.ellipse([cx - 9, eye_y - 2, cx - 5, eye_y + 2], fill="#2C3E50")
        draw.ellipse([cx + 5, eye_y - 2, cx + 9, eye_y + 2], fill="#2C3E50")
    else:
        # Normal eyes
        draw.ellipse([cx - 10, eye_y - 3, cx - 4, eye_y + 3], fill="white")
        draw.ellipse([cx + 4, eye_y - 3, cx + 10, eye_y + 3], fill="white")
        draw.ellipse([cx - 8, eye_y - 1, cx - 5, eye_y + 2], fill="#2C3E50")
        draw.ellipse([cx + 5, eye_y - 1, cx + 8, eye_y + 2], fill="#2C3E50")

    # Beak
    beak_y = eye_y + 10
    draw.polygon(
        [cx - 6, beak_y, cx + 6, beak_y, cx, beak_y + 10],
        fill="#F39C12", outline="#e67e22", width=1
    )

    # Feet
    foot_offset = int(6 * math.sin(frame / total_frames * 4 * math.pi))
    foot_y = body_bot - 2
    draw.ellipse([cx - 20 + foot_offset, foot_y - 5, cx - 8 + foot_offset, foot_y + 5], fill="#F39C12")
    draw.ellipse([cx + 8 - foot_offset, foot_y - 5, cx + 20 - foot_offset, foot_y + 5], fill="#F39C12")

    # Phase-specific extras
    if phase == "question":
        # Exclamation mark above head
        ex_y = body_top - 15
        draw.text((cx - 3, ex_y - 10), "!", fill="#e74c3c")
    elif phase == "thinking":
        # Thought bubble dots
        dot_phase = frame / total_frames
        for i in range(3):
            r = 3 + i * 1.5
            alpha = dot_phase * 2 * math.pi + i
            dx = int(20 * math.cos(alpha))
            dy = body_top - 15 + int(8 * math.sin(alpha))
            draw.ellipse([cx + dx - r, dy - r, cx + dx + r, dy + r], fill="#bdc3c7")
    elif phase == "writing":
        # Tiny keyboard rectangle below
        kb_y = body_bot + 8
        draw.rectangle([cx - 15, kb_y - 4, cx + 15, kb_y + 4], fill="#7f8c8d", outline="#6c7a7a")
        # Fingers/hands tapping
        tap = frame % 2
        draw.ellipse([cx - 18 - tap * 3, kb_y - 12, cx - 10 - tap * 3, kb_y - 4], fill="#2C3E50")
        draw.ellipse([cx + 10 + tap * 3, kb_y - 12, cx + 18 + tap * 3, kb_y - 4], fill="#2C3E50")
    elif phase == "executing":
        # Motion lines behind
        for i in range(3):
            lx = cx - 40 + i * 8 + (frame % 3) * 5
            ly = cy - 5 + i * 5
            draw.line([lx, ly, lx + 8, ly], fill="#95a5a6", width=2)
    elif phase == "done":
        # Sparkle stars
        import random
        rng = random.Random(frame + total_frames)
        for _ in range(3):
            sx = cx - 20 + rng.randint(0, 40)
            sy = body_top - 15 + rng.randint(-10, 5)
            draw.text((sx, sy), "★", fill="#f1c40f")


def generate_sprites():
    """Generate all placeholder sprite PNGs."""
    for phase, config in PHASES.items():
        phase_dir = os.path.join(SPRITES_DIR, phase)
        os.makedirs(phase_dir, exist_ok=True)

        total = config["frames"]
        for i in range(total):
            img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw_penguin(draw, SIZE // 2, SIZE // 2, i, total, phase)
            filepath = os.path.join(phase_dir, f"frame_{i+1:02d}.png")
            img.save(filepath)
            print(f"  {filepath}")


if __name__ == "__main__":
    print("Generating placeholder sprites...")
    generate_sprites()
    print("Done.")
```

- [ ] **Step 2: Run sprite generator**

Run: `python pet/generate_sprites.py`
Expected: Prints paths for 7×N PNG files created under `pet/sprites/`

- [ ] **Step 3: Verify sprites exist**

Run: `find pet/sprites -name "*.png" | wc -l`
Expected: 40 (6+4+8+8+4+6+4)

---

### Task 3: IPC Listener

**Files:**
- Create: `pet/ipc.py`

- [ ] **Step 1: Write pet/ipc.py**

```python
"""Unix socket IPC listener for desktop pet phase signals."""
import os
import socket
from PySide6.QtCore import QThread, Signal


SOCKET_PATH = "/tmp/desktop-pet.sock"


class PetIPC(QThread):
    phase_changed = Signal(str)

    def __init__(self, socket_path=SOCKET_PATH, parent=None):
        super().__init__(parent)
        self.socket_path = socket_path
        self._running = True

    def run(self):
        # Clean up stale socket file
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        server.listen(1)
        server.settimeout(0.5)

        while self._running:
            try:
                conn, _ = server.accept()
                data = conn.recv(1024).decode("utf-8").strip()
                if data:
                    self.phase_changed.emit(data)
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                break

        server.close()
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def stop(self):
        self._running = False
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from pet.ipc import PetIPC; print('OK')"`
Expected: `OK`

---

### Task 4: Animation Engine

**Files:**
- Create: `pet/animation.py`

- [ ] **Step 1: Write pet/animation.py**

```python
"""Animation state machine and sprite frame controller."""
import os
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap


SPRITES_DIR = os.path.join(os.path.dirname(__file__), "sprites")

STATE_CONFIG = {
    "idle":      {"interval": 150, "loops": True},
    "question":  {"interval": 80,  "loops": False},
    "reading":   {"interval": 120, "loops": True},
    "thinking":  {"interval": 120, "loops": True},
    "writing":   {"interval": 100, "loops": True},
    "executing": {"interval": 80,  "loops": True},
    "done":      {"interval": 100, "loops": False},
}


class AnimationEngine(QObject):
    frame_changed = Signal(QPixmap)

    def __init__(self, sprites_dir=SPRITES_DIR, parent=None):
        super().__init__(parent)
        self.sprites_dir = sprites_dir
        self.frames = {}          # phase -> [QPixmap, ...]
        self.current_phase = "idle"
        self.frame_index = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        self._thinking_timer = QTimer(self)
        self._thinking_timer.setSingleShot(True)
        self._thinking_timer.timeout.connect(self._on_thinking_timeout)

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
            # Fallback: solid color placeholder if no sprites found
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
        painter.drawText(0, 0, 150, 150, 0x0084, phase)
        painter.end()
        return pixmap

    def set_state(self, phase):
        if phase not in self.frames:
            return
        self._thinking_timer.stop()
        self.current_phase = phase
        self.frame_index = 0
        self.timer.start(STATE_CONFIG[phase]["interval"])
        self._emit_frame()

        # Start thinking timer for reading/writing phases
        if phase in ("reading", "writing"):
            self._thinking_timer.start(3000)

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
                # Auto-transition done -> idle after a brief pause
                QTimer.singleShot(3000, lambda: self.set_state("idle"))
                return
            elif self.current_phase == "question":
                # question plays once then stays on last frame until next signal
                return
        self._emit_frame()

    def _emit_frame(self):
        frames = self.frames[self.current_phase]
        if frames:
            self.frame_changed.emit(frames[self.frame_index])
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from pet.animation import AnimationEngine; print('OK')"`
Expected: `OK`

---

### Task 5: Pet Window

**Files:**
- Create: `pet/window.py`

- [ ] **Step 1: Write pet/window.py**

```python
"""Transparent, always-on-top, draggable pet window."""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtGui import QPixmap, QMouseEvent


class PetWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(150, 150)

        # Set initial position: bottom-right corner
        screen = self.screen().availableGeometry()
        self.move(screen.width() - 180, screen.height() - 180)

        # Sprite label
        self.label = QLabel(self)
        self.label.setFixedSize(150, 150)
        self.label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        # Drag state
        self._drag_offset = QPoint()

    def set_pixmap(self, pixmap: QPixmap):
        scaled = pixmap.scaled(
            150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.label.setPixmap(scaled)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from pet.window import PetWindow; print('OK')"`
Expected: `OK`

---

### Task 6: Main Entry Point

**Files:**
- Create: `pet_app.py`

- [ ] **Step 1: Write pet_app.py**

```python
"""Desktop Pet — main entry point."""
import sys
import signal
from PySide6.QtWidgets import QApplication
from pet.window import PetWindow
from pet.animation import AnimationEngine
from pet.ipc import PetIPC


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    engine = AnimationEngine()
    ipc = PetIPC()

    # Wire signals
    ipc.phase_changed.connect(engine.set_state)
    engine.frame_changed.connect(window.set_pixmap)

    # Cleanup on exit
    def cleanup(*args):
        ipc.stop()
        app.quit()

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Start
    ipc.start()
    engine.set_state("idle")
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test basic launch (window appears, close with Ctrl+C)**

Run: `python pet_app.py &`
Expected: Window appears in bottom-right, 150×150, no title bar, on top of other windows.

- [ ] **Step 3: Kill the test process**

Run: `pkill -f pet_app.py`

---

### Task 7: End-to-End Integration Test

**Files:**
- No new files. Verify existing files work together.

- [ ] **Step 1: Start the pet app in background**

Run: `python pet_app.py &`
Wait 2 seconds for socket to be ready.

- [ ] **Step 2: Test state transitions via signal script**

```bash
./scripts/notify-pet.sh question && sleep 1.5
./scripts/notify-pet.sh reading && sleep 2
./scripts/notify-pet.sh writing && sleep 2
./scripts/notify-pet.sh executing && sleep 2
./scripts/notify-pet.sh done
```

Expected: Pet window shows different colored-placeholder/frames for each phase. `question` plays once, `reading` transitions to `thinking` after 3s, `done` auto-returns to `idle`.

- [ ] **Step 3: Test drag interaction**

Manual: Click and drag the pet window. Expected: window follows cursor.

- [ ] **Step 4: Kill the pet**

Run: `pkill -f pet_app.py`
Verify: `/tmp/desktop-pet.sock` is cleaned up (run `ls /tmp/desktop-pet.sock` — should fail with "No such file")

---

### Task 8: Configure Claude Code Hooks

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Read current settings.json**

Run: `cat ~/.claude/settings.json 2>/dev/null || echo "{}"`

- [ ] **Step 2: Merge pet hooks into settings.json**

Add or merge the `hooks` key. The notify-pet.sh path must be absolute.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {"command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh question"}
    ],
    "PostToolUse": [
      {"matcher": "Read|Grep|Glob", "command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh reading"},
      {"matcher": "Edit|Write", "command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh writing"},
      {"matcher": "Bash", "command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh executing"}
    ],
    "Stop": [
      {"command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh done"}
    ],
    "SessionStart": [
      {"command": "/Users/liyueyang/Desktop/desktop-pet/scripts/notify-pet.sh idle"}
    ]
  }
}
```

**Warning:** If settings.json already has hooks, merge the keys carefully. Existing hooks should be preserved alongside pet hooks. If a hook type (e.g., PostToolUse) already exists, append to its array rather than overwriting.

- [ ] **Step 3: Launch pet before next CC session**

Run: `python ~/Desktop/desktop-pet/pet_app.py &`

The pet will now react to all CC phases automatically.
