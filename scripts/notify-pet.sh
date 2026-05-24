#!/bin/bash
# Send a phase to the running desktop pet over TCP localhost.
# Usage: ./scripts/notify-pet.sh <phase>
# Env:   DESKTOP_PET_HOST (default 127.0.0.1)
#        DESKTOP_PET_PORT (default 19847)
HOST="${DESKTOP_PET_HOST:-127.0.0.1}"
PORT="${DESKTOP_PET_PORT:-19847}"
echo "$1" | nc "$HOST" "$PORT" 2>/dev/null || true
