#!/usr/bin/env bash
# Bootstrap + launch the desktop pet on macOS / Linux.
#
# Usage:
#   ./scripts/start-pet.sh            # normal start
#   ./scripts/start-pet.sh --debug    # PET_DEBUG=1, prints geometry + draws red outline
#   ./scripts/start-pet.sh --reset    # wipe the venv and reinstall from scratch
#   ./scripts/start-pet.sh --regen    # regenerate sprite PNGs
#
# Idempotent: first run creates .venv, subsequent runs reuse it.

set -euo pipefail

# ---------- locate project root (script lives in scripts/) ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/.venv"
REQ_FILE="$PROJECT_ROOT/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
SPRITES_DIR="$PROJECT_ROOT/pet/sprites"

# ---------- parse args ----------
DEBUG=0
RESET=0
REGEN=0
for arg in "$@"; do
    case "$arg" in
        --debug)   DEBUG=1 ;;
        --reset)   RESET=1 ;;
        --regen)   REGEN=1 ;;
        -h|--help)
            sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

log() { printf '\033[1;36m[start-pet]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[start-pet]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[start-pet]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 1. pick a real python ----------
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        # Skip macOS Xcode stub that prints "no developer tools" on invocation.
        if "$cand" -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
            PYTHON_BIN="$(command -v "$cand")"
            break
        fi
    fi
done
[ -n "$PYTHON_BIN" ] || die "no Python >=3.9 found. Install via 'brew install python@3.12'."
log "using $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

# ---------- 2. (re)create venv ----------
if [ "$RESET" = "1" ] && [ -d "$VENV_DIR" ]; then
    log "removing existing venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "creating venv at $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"

# ---------- 3. install / refresh deps (only when requirements.txt changes) ----------
REQ_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
STAMP_HASH="$(cat "$REQ_STAMP" 2>/dev/null || true)"

if [ "$REQ_HASH" != "$STAMP_HASH" ]; then
    log "installing requirements (hash changed)"
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    "$VENV_PY" -m pip install -r "$REQ_FILE"
    printf '%s' "$REQ_HASH" > "$REQ_STAMP"
else
    log "requirements up to date"
fi

# ---------- 4. ensure sprites exist ----------
NEED_REGEN=0
if [ "$REGEN" = "1" ]; then
    NEED_REGEN=1
elif [ ! -d "$SPRITES_DIR/idle" ] || [ -z "$(ls -A "$SPRITES_DIR/idle" 2>/dev/null)" ]; then
    NEED_REGEN=1
fi

if [ "$NEED_REGEN" = "1" ]; then
    log "generating sprite PNGs"
    "$VENV_PY" -m pet.generate_sprites
else
    log "sprites present"
fi

# ---------- 5. launch ----------
if [ "$DEBUG" = "1" ]; then
    export PET_DEBUG=1
    log "launching in DEBUG mode (red outline, verbose logs)"
else
    log "launching"
fi

# Helpful Qt hints on macOS HiDPI; harmless elsewhere.
export QT_ENABLE_HIGHDPI_SCALING="${QT_ENABLE_HIGHDPI_SCALING:-1}"

exec "$VENV_PY" "$PROJECT_ROOT/pet_app.py"
