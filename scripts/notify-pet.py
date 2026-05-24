#!/usr/bin/env python3
"""Cross-platform notifier for the desktop pet IPC socket.

Usage:
    python scripts/notify-pet.py <phase>

Where <phase> is one of:
    idle, question, reading, thinking, writing, executing, done

Override the endpoint with DESKTOP_PET_HOST / DESKTOP_PET_PORT env vars.
"""
import os
import socket
import sys

VALID_PHASES = ("idle", "question", "reading", "thinking", "writing", "executing", "done")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19847


def main(argv):
    if len(argv) != 2 or argv[1] not in VALID_PHASES:
        print(f"usage: {argv[0]} <{' | '.join(VALID_PHASES)}>", file=sys.stderr)
        return 2

    phase = argv[1]
    host = os.environ.get("DESKTOP_PET_HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("DESKTOP_PET_PORT", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT

    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            sock.sendall(phase.encode("utf-8"))
    except OSError as e:
        print(f"failed to notify pet at {host}:{port}: {e}", file=sys.stderr)
        print("is the pet running?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
