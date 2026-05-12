#!/usr/bin/env bash
# Double-click in Finder to launch (Terminal opens). Same as repo root start-pet.command.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/start-pet.sh" "$@"
