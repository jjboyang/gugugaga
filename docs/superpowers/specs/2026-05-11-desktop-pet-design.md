# Desktop Pet — Design Spec

**Date:** 2026-05-11
**Status:** Draft
**Topic:** Claude Code desktop pet companion with phase-driven animations

## Overview

A desktop pet (penguin character, "咕咕嘎嘎" cartoon style) that lives on macOS desktop as an always-on-top companion. It reflects Claude Code's current thinking phase through sprite-based frame animations. User can click and drag the pet to any screen position.

## Architecture

```
Claude Code Hooks (settings.json)
    |
    | PostToolUse:Read/Grep/Glob → "reading"
    | PostToolUse:Edit/Write     → "writing"
    | PostToolUse:Bash           → "executing"
    | UserPromptSubmit           → "question"
    | Stop                        → "done"
    | SessionStart                → "idle"
    |
    v  shell: notify-pet <phase>
notify-pet.sh  ──→  Unix Socket (/tmp/desktop-pet.sock)
                         |
                         v
              ┌──────────────────────┐
              │  PySide6 App          │
              │  ┌────────┐ ┌───────┐│
              │  │ IPC    │→│State  ││
              │  │Listener│ │Machine││
              │  └────────┘ └───┬───┘│
              │                 │    │
              │  ┌──────────────▼───┐│
              │  │ Animation Engine ││
              │  │ (sprite frames)  ││
              │  └──────┬──────────┘│
              │         │           │
              │  ┌──────▼──────────┐│
              │  │Transparent      ││
              │  │Always-on-Top    ││
              │  │Draggable Window ││
              │  └─────────────────┘│
              └──────────────────────┘
```

## Tech Stack

- **Language:** Python 3.11+
- **GUI:** PySide6
- **IPC:** Unix domain socket (text protocol)
- **Sprite generation:** Pillow (placeholder sprites, replaceable with real art)
- **Platform:** macOS (tested on Darwin 24.5.0)

## Project Structure

```
desktop-pet/
├── pet_app.py                       # Main entry point
├── pet/
│   ├── __init__.py
│   ├── window.py                    # Transparent frameless window + drag
│   ├── animation.py                 # State machine + frame controller
│   ├── ipc.py                       # Unix socket server (QThread)
│   ├── sprites/                     # Sprite frame PNGs
│   │   ├── idle/                    # Blinking/idle animation
│   │   ├── question/                # Surprised/look-up
│   │   ├── reading/                 # Walking/glancing around
│   │   ├── thinking/                # Pondering/spinning
│   │   ├── writing/                 # Typing on keyboard
│   │   ├── executing/               # Running
│   │   └── done/                    # Happy/jumping
│   └── generate_sprites.py          # Placeholder sprite generator
├── scripts/
│   └── notify-pet.sh               # Signal script for CC hooks
├── requirements.txt                # PySide6, Pillow
└── docs/superpowers/specs/         # Design docs
```

## State Machine

7 discrete states. Transitions triggered by IPC messages from CC hooks:

```
idle ──(UserPromptSubmit)──→ question
question ──(PostToolUse:Read/Glob/Grep)──→ reading
reading ──(no signal 3s)──→ thinking
reading ──(PostToolUse:Edit/Write)──→ writing
thinking ──(PostToolUse:Edit/Write)──→ writing
thinking ──(PostToolUse:Bash)──→ executing
writing ──(PostToolUse:Bash)──→ executing
writing ──(PostToolUse:Read/Glob/Grep)──→ reading
executing ──(Stop)──→ done
done ──(auto after 3s)──→ idle
any ──(Stop without prior tool)──→ idle
```

**Special handling:**
- `thinking` phase has no direct hook trigger. A 3-second timer fires if no new signal arrives after `reading` or `writing`. This covers the gap between tool calls when Claude is analyzing.
- `done` plays once then auto-transitions to `idle` after 3 seconds.

## Animation System

**Sprite format:** PNG frame sequences, named `frame_01.png`, `frame_02.png`, etc. in `sprites/<phase>/`.

| Phase      | Frames | Loop?  | Speed    | Behavior                  |
|------------|--------|--------|----------|---------------------------|
| idle       | 6      | loop   | 150ms    | Gentle blink, slow idle   |
| question   | 4      | once   | 80ms     | Quick head-tilt/surprise  |
| reading    | 8      | loop   | 120ms    | Walking/glancing          |
| thinking   | 8      | loop   | 120ms    | Pondering/spinning        |
| writing    | 4      | loop   | 100ms    | Typing action             |
| executing  | 6      | loop   | 80ms     | Fast running              |
| done       | 4      | once→  | 100ms    | Happy jump, then idle     |

**Placeholder sprites:** A `generate_sprites.py` script uses Pillow to draw a simple penguin shape (ellipse body, eyes, beak, feet) with per-frame pose variations (position offset, rotation, scale). Color-coded per state for visual distinction. Replaceable with real artwork by dropping in replacement PNGs.

**Frame rendering:** QLabel with QPixmap, updated on QTimer tick. Window sized to 150x150px with sprite centered.

## IPC Protocol

**Transport:** Unix domain socket at `/tmp/desktop-pet.sock`

**Protocol:** Text-based, newline-delimited. Each message is a single phase name string: `idle`, `question`, `reading`, `thinking`, `writing`, `executing`, `done`.

**Client (notify-pet.sh):**
```bash
#!/bin/bash
echo "$1" | nc -U /tmp/desktop-pet.sock 2>/dev/null || true
```

**Server (pet/ipc.py):** Runs in a QThread. Creates socket, listens, reads line by line, emits Qt signal `phase_changed(str)` to main thread.

## CC Hooks Configuration

Added to `~/.claude/settings.json` under the `hooks` key:

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

## Window Properties

```python
window.setWindowFlags(
    Qt.FramelessWindowHint
    | Qt.WindowStaysOnTopHint
    | Qt.Tool
    | Qt.NoFocus
)
window.setAttribute(Qt.WA_TranslucentBackground)
```

- **Size:** 150×150 px
- **Position:** Bottom-right of screen by default
- **Drag:** Override `mousePressEvent` / `mouseMoveEvent` — click anywhere, drag anywhere
- **No Dock icon:** `Qt.Tool` flag hides from Dock

## Error Handling

- Socket file cleanup: remove stale `/tmp/desktop-pet.sock` on startup
- Socket write failures: `notify-pet.sh` uses `|| true` to never block hooks
- Missing sprites: fall back to solid-color placeholder square
- App not running: hooks silently succeed (pet is optional companion)
- Graceful shutdown: clean up socket file on app exit

## Future Enhancements (out of scope for v1)

- Right-click context menu (exit, switch state manually, settings)
- Position persistence between launches
- Lottie/skeleton animation support for smoother art
- Voice/sound effects per state
- Multiple pets
- Click interaction (pet reacts to clicks)
