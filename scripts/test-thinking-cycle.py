"""Simulate a Claude thinking cycle to test pet phase transitions.

Usage: python scripts/test-thinking-cycle.py [--fast]
  --fast: compressed timing for quick visual verification
"""
import socket
import sys
import time
import os

HOST = os.environ.get("DESKTOP_PET_HOST", "127.0.0.1")
PORT = int(os.environ.get("DESKTOP_PET_PORT", "19847"))


def notify(phase):
    """Send a single phase to the pet IPC socket."""
    try:
        with socket.create_connection((HOST, PORT), timeout=2.0) as sock:
            sock.sendall(phase.encode("utf-8"))
        print(f"  [OK] {phase}")
        return True
    except OSError as e:
        print(f"  [FAIL] {phase} - {e}")
        return False


def run_cycle(fast=False):
    """Walk through every phase the pet knows, with realistic timing.

    Sequence mirrors Claude's internal tool-use loop:
      question → reading → thinking → writing → executing → done
    """
    if fast:
        scale = 0.2
    else:
        scale = 1.0

    scenes = [
        # (phase, duration_seconds, description)
        ("idle",      0.5,  "Initial idle"),
        ("question",  1.5,  "User question received"),
        ("reading",   2.5,  "Reading code/files"),
        ("thinking",  3.0,  "Thinking / reasoning"),
        ("reading",   1.5,  "Re-reading code / searching"),
        ("thinking",  2.0,  "More thinking / planning"),
        ("writing",   2.0,  "Writing code / editing"),
        ("executing", 2.5,  "Executing commands"),
        ("thinking",  1.5,  "Analyzing results"),
        ("writing",   1.5,  "More editing"),
        ("executing", 2.0,  "Running tests"),
        ("done",      2.0,  "Task done"),
        ("idle",      0.5,  "Back to idle"),
    ]

    print("=" * 52)
    print(f"Desktop Pet Thinking Cycle Test ({'fast' if fast else 'normal'} mode)")
    print("=" * 52)

    for phase, raw_dur, desc in scenes:
        dur = max(0.3, raw_dur * scale)
        ok = notify(phase)
        if not ok:
            print("桌宠连接失败，确认 pet_app.py 正在运行")
            return False
        pbar = "#" * int(dur * 4) + "-" * int((3.0 - dur) * 4)
        print(f"    {desc}  [{pbar}] {dur:.1f}s")
        time.sleep(dur)

    print("-" * 52)
    print("Test complete - all phases sent successfully.")
    print("Expected sequence: idle -> question -> reading -> thinking -> writing -> executing -> done -> idle")
    return True


if __name__ == "__main__":
    fast = "--fast" in sys.argv
    success = run_cycle(fast=fast)
    sys.exit(0 if success else 1)
