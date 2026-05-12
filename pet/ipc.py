"""TCP localhost IPC listener for desktop pet phase signals.

We use a loopback TCP socket instead of AF_UNIX so the same code runs on
Linux, macOS, and Windows (whose CPython build still doesn't expose AF_UNIX).
"""
import os
import socket
import sys
from PySide6.QtCore import QThread, Signal


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19847
VALID_PHASES = {"idle", "question", "reading", "thinking", "writing", "executing", "done"}


def _resolve_endpoint():
    """Allow override via env vars, otherwise fall back to defaults."""
    host = os.environ.get("DESKTOP_PET_HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("DESKTOP_PET_PORT", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT
    return host, port


class PetIPC(QThread):
    phase_changed = Signal(str)

    def __init__(self, host=None, port=None, parent=None):
        super().__init__(parent)
        default_host, default_port = _resolve_endpoint()
        self.host = host or default_host
        self.port = port or default_port
        self._running = True
        self._server = None

    def run(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(4)
            server.settimeout(0.5)
        except OSError as e:
            print(f"[pet-ipc] failed to bind {self.host}:{self.port}: {e}",
                  file=sys.stderr)
            return

        self._server = server
        print(f"[pet-ipc] listening on {self.host}:{self.port}", file=sys.stderr)

        while self._running:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                try:
                    data = conn.recv(1024).decode("utf-8", errors="replace").strip()
                    if data and data in VALID_PHASES:
                        self.phase_changed.emit(data)
                except OSError:
                    pass
                finally:
                    conn.close()

        server.close()
        self._server = None

    def stop(self):
        self._running = False
        # Force a socket close so accept() returns immediately instead of
        # blocking up to the 500ms timeout.
        srv = self._server
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        self.wait(1500)
