"""TCP localhost IPC listener for desktop pet phase signals and question/answer flow."""
import json
import os
import socket
import sys
import threading
from PySide6.QtCore import QThread, Signal


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19847
VALID_PHASES = {"idle", "question", "reading", "thinking", "writing", "executing", "done"}
QUESTION_TIMEOUT_S = 120


def _resolve_endpoint():
    host = os.environ.get("DESKTOP_PET_HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("DESKTOP_PET_PORT", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT
    return host, port


class PetIPC(QThread):
    phase_changed = Signal(str)
    question_received = Signal(str, list)  # text, options (list of {label,description})

    def __init__(self, host=None, port=None, parent=None):
        super().__init__(parent)
        default_host, default_port = _resolve_endpoint()
        self.host = host or default_host
        self.port = port or default_port
        self._running = True
        self._server = None
        self._answer_event = threading.Event()
        self._answer_value = None
        self._answer_lock = threading.Lock()

    def set_answer(self, value):
        with self._answer_lock:
            self._answer_value = value
            self._answer_event.set()

    def _reset_answer_state(self):
        with self._answer_lock:
            self._answer_event.clear()
            self._answer_value = None

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
                self._handle_connection(conn)

        server.close()
        self._server = None

    def _handle_connection(self, conn):
        try:
            data = conn.recv(4096).decode("utf-8", errors="replace").strip()
        except OSError:
            conn.close()
            return

        if not data:
            conn.close()
            return

        # JSON message → question/answer flow
        if data.startswith("{"):
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                conn.close()
                return

            if msg.get("type") == "question":
                text = msg.get("text", "")
                options = msg.get("options", [])
                self._reset_answer_state()
                self.question_received.emit(text, options)

                answered = self._answer_event.wait(QUESTION_TIMEOUT_S)
                with self._answer_lock:
                    selected = self._answer_value
                response = json.dumps({"selected": selected if answered else None})
                try:
                    conn.sendall(response.encode("utf-8"))
                except OSError:
                    pass
            conn.close()
            return

        # Plain word → phase change (backward-compatible)
        if data in VALID_PHASES:
            self.phase_changed.emit(data)
        conn.close()

    def stop(self):
        self._running = False
        self._answer_event.set()  # unblock any waiting question
        srv = self._server
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        self.wait(1500)
