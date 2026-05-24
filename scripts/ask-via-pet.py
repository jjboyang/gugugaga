#!/usr/bin/env python3
"""Send a question to the desktop pet and print the selected answer.

Usage:
    ask-via-pet.py '{"text":"Pick one","options":[{"label":"A","description":"..."}]}'
    echo '{"text":"...","options":[...]}' | ask-via-pet.py

Output: selected label string, or empty if dismissed/timeout.
"""
import json
import socket
import sys

HOST = "127.0.0.1"
PORT = 19847
TIMEOUT = 130  # slightly longer than pet's internal 120s


def main():
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if msg.get("type") != "question":
        msg["type"] = "question"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect((HOST, PORT))
        sock.sendall(json.dumps(msg).encode("utf-8"))
        data = sock.recv(4096).decode("utf-8", errors="replace")
        resp = json.loads(data)
        selected = resp.get("selected", "")
        if selected:
            print(selected)
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"Pet unreachable: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
