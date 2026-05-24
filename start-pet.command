#!/usr/bin/env bash
# Double-click at repo root → runs scripts/macos/start-pet.sh (Terminal opens).
# You can also double-click scripts/macos/start-pet.command.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/scripts/macos/start-pet.sh" "$@"
