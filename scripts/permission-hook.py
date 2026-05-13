#!/usr/bin/env python3
"""Claude Code PermissionRequest hook — routes permission prompts to desktop pet.

Flow:
1. Claude Code fires PermissionRequest → this script receives JSON on stdin
2. Script sends question to desktop pet via TCP (same protocol as ask-via-pet.py)
3. Script blocks until pet user clicks an option (or timeout/error)
4. Script prints {"decision":"allow"} or {"decision":"deny"} to stdout

If pet unreachable or user dismisses popup → defaults to "allow" so terminal
prompt still appears as fallback.

Usage (in Claude Code settings.json):
  "PermissionRequest": [
    {"command": "/path/to/permission-hook.py"}
  ]

Override pet endpoint: DESKTOP_PET_HOST, DESKTOP_PET_PORT
Debug logging: PERMISSION_HOOK_LOG=/tmp/permission-hook.log
"""
import json
import os
import socket
import sys
import time

HOST = os.environ.get("DESKTOP_PET_HOST", "127.0.0.1")
PORT = int(os.environ.get("DESKTOP_PET_PORT", "19847"))
PET_TIMEOUT = 90  # slightly less than Claude Code's internal hook timeout
LOG_FILE = os.environ.get("PERMISSION_HOOK_LOG", "")


def log(msg):
    if not LOG_FILE:
        return
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _extract_request_info(request: dict):
    """Pull out tool name and reason from various possible JSON schemas."""
    # Tool name
    tool = (
        request.get("tool_name")
        or request.get("toolName")
        or request.get("tool")
        or request.get("name")
        or "unknown"
    )

    # Human-readable reason
    reason = (
        request.get("message")
        or request.get("reason")
        or request.get("description")
        or ""
    )

    # Some schemas nest under "tool_use" / "data"
    if not reason:
        inner = request.get("tool_use") or request.get("data") or {}
        if isinstance(inner, dict):
            reason = inner.get("message") or inner.get("reason") or ""

    return tool, reason


def _send_to_pet(text: str, options: list) -> str | None:
    """Send question to pet, block for answer, return selected label or None."""
    question = {"type": "question", "text": text, "options": options}
    data = json.dumps(question).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(PET_TIMEOUT + 10)
    try:
        sock.connect((HOST, PORT))
        sock.sendall(data)
        resp_raw = sock.recv(4096).decode("utf-8", errors="replace")
        resp = json.loads(resp_raw)
        return resp.get("selected")
    except (socket.timeout, ConnectionRefusedError, OSError, json.JSONDecodeError) as e:
        log(f"pet error: {e}")
        return None
    finally:
        sock.close()


def main():
    stdin_data = sys.stdin.read().strip()

    log(f"=== fired ===")
    log(f"stdin: {stdin_data[:500]}")
    log(f"CLAUDE_HOOK_EVENT: {os.environ.get('CLAUDE_HOOK_EVENT', '')}")

    try:
        request = json.loads(stdin_data) if stdin_data else {}
    except json.JSONDecodeError:
        log("stdin not JSON, allowing")
        print(json.dumps({"decision": "allow"}))
        return 0

    tool_name, reason = _extract_request_info(request)
    log(f"tool={tool_name} reason={reason[:100] if reason else ''}")

    # Build friendly text for the pet popup
    text = f"允许执行 {tool_name}？"
    if reason:
        # Truncate long reasons for display
        short_reason = reason[:120] + "..." if len(reason) > 120 else reason
        text += f"\n{short_reason}"

    options = [
        {"label": "Yes", "description": "允许本次"},
        {"label": "Yes, allow all", "description": "允许后续相同操作"},
        {"label": "No", "description": "拒绝"},
    ]

    selected = _send_to_pet(text, options)

    if selected == "Yes":
        decision = "allow"
    elif selected == "Yes, allow all":
        decision = "allow"
    elif selected == "No":
        decision = "deny"
    else:
        # Pet timeout / dismissed / unreachable → let terminal prompt handle it
        decision = "allow"

    log(f"decision={decision} (selected={selected})")
    print(json.dumps({"decision": decision}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
