#!/usr/bin/env bash
#
# Bootstrap + launch the desktop pet on macOS (same behavior as scripts/windows/start-pet.ps1).
#
# Usage:
#   Double-click start-pet.command in this folder or repo root (runs this script).
#   ./scripts/macos/start-pet.sh              normal start
#   ./scripts/macos/start-pet.sh --debug      PET_DEBUG=1 (red outline + logs)
#   ./scripts/macos/start-pet.sh --reset      remove .venv and recreate
#   ./scripts/macos/start-pet.sh --regen      regenerate sprite PNGs
#

set -euo pipefail

log()    { printf '[start-pet] %s\n' "$*" >&2; }
warn()   { printf '[start-pet] %s\n' "$*" >&2; }
die()    { warn "$*"; exit 1; }

DEBUG=false
RESET=false
REGEN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug|-Debug|-debug) DEBUG=true ;;
    --reset|-Reset|-reset) RESET=true ;;
    --regen|-Regen|-regen) REGEN=true ;;
    -h|--help)
      sed -n '2,13p' "$0" >&2
      exit 0
      ;;
    *)
      die "unknown option: $1 (try --help)"
      ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR="$PROJECT_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"
REQ_FILE="$PROJECT_ROOT/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
SPRITE_DIR="$PROJECT_ROOT/pet/sprites"

# ---------- find Python 3.9+ ----------
PYTHON_EXE=""
for cand in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PYTHON_EXE="$(command -v "$cand")"
      break
    fi
  fi
done

if [[ -z "$PYTHON_EXE" ]]; then
  warn 'No Python 3.9+ found on PATH.'
  warn 'Install with: brew install python@3.12   or   https://www.python.org/downloads/'
  die 'aborting.'
fi
log "using $PYTHON_EXE ($("$PYTHON_EXE" --version 2>&1))"

# ---------- (re)create venv ----------
if [[ "$RESET" == true && -d "$VENV_DIR" ]]; then
  log "removing existing venv at $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "$VENV_PY" ]]; then
  log "creating venv at $VENV_DIR"
  "$PYTHON_EXE" -m venv "$VENV_DIR"
fi

# Some Python installs (e.g. minimal/toolchain builds) create a venv without pip.
if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  log 'pip missing in venv; bootstrapping with ensurepip'
  "$VENV_PY" -m ensurepip --upgrade || die 'ensurepip failed; try: rm -rf .venv && ./scripts/macos/start-pet.sh --reset'
fi

# ---------- install deps when requirements.txt changes ----------
REQ_HASH="$(shasum -a 256 "$REQ_FILE" | awk '{print $1}')"
STAMP_HASH=""
if [[ -f "$REQ_STAMP" ]]; then
  STAMP_HASH="$(tr -d '[:space:]' < "$REQ_STAMP")"
fi

if [[ "$REQ_HASH" != "$STAMP_HASH" ]]; then
  log 'installing requirements (hash changed)'
  "$VENV_PY" -m pip install --upgrade pip >/dev/null
  "$VENV_PY" -m pip install -r "$REQ_FILE"
  printf '%s' "$REQ_HASH" > "$REQ_STAMP"
else
  log 'requirements up to date'
fi

# ---------- sprites ----------
NEED_REGEN=false
if [[ "$REGEN" == true ]]; then
  NEED_REGEN=true
elif [[ ! -d "$SPRITE_DIR/idle" ]]; then
  NEED_REGEN=true
else
  png_count="$(find "$SPRITE_DIR/idle" -maxdepth 1 -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "${png_count:-0}" -eq 0 ]]; then
    NEED_REGEN=true
  fi
fi

if [[ "$NEED_REGEN" == true ]]; then
  log 'generating sprite PNGs'
  "$VENV_PY" -m pet.generate_sprites
else
  log 'sprites present'
fi

# ---------- launch ----------
if [[ "$DEBUG" == true ]]; then
  export PET_DEBUG=1
  log 'launching in DEBUG mode (red outline, verbose logs)'
else
  log 'launching'
fi

if [[ -z "${QT_ENABLE_HIGHDPI_SCALING:-}" ]]; then
  export QT_ENABLE_HIGHDPI_SCALING=1
fi

exec "$VENV_PY" "$PROJECT_ROOT/pet_app.py"
