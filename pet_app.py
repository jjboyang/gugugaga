"""Desktop Pet — main entry point."""
import os
import sys
import signal
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from pet.window import PetWindow
from pet.animation import AnimationEngine
from pet.ipc import PetIPC


DEBUG = os.environ.get("PET_DEBUG") == "1"


def _dlog(*args):
    if DEBUG:
        print("[pet]", *args, file=sys.stderr, flush=True)


def main():
    _dlog("starting; platform=", sys.platform, "python=", sys.version.split()[0])
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _dlog("QApplication ready")

    window = PetWindow(debug=DEBUG)
    engine = AnimationEngine()
    ipc = PetIPC()
    _dlog("window/engine/ipc constructed")
    _dlog("sprites loaded:", {k: len(v) for k, v in engine.frames.items()})

    app.aboutToQuit.connect(ipc.stop)

    ipc.phase_changed.connect(engine.set_state)
    engine.frame_changed.connect(window.set_pixmap)

    window.drag_started.connect(engine.begin_drag)
    window.drag_ended.connect(engine.end_drag)

    def cleanup(*args):
        ipc.stop()
        app.quit()

    window.quit_requested.connect(cleanup)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Qt's C++ event loop blocks the Python interpreter, so POSIX signals
    # (SIGINT / SIGTERM) won't be delivered until Python regains control.
    # A no-op timer wakes the interpreter periodically so Ctrl+C works.
    _sigwake = QTimer()
    _sigwake.start(250)
    _sigwake.timeout.connect(lambda: None)

    ipc.start()
    engine.set_state("idle")
    window.show()
    window.raise_()
    window.activateWindow()

    _dlog("window.show() called")
    _dlog("  geometry        =", window.geometry())
    _dlog("  frameGeometry   =", window.frameGeometry())
    _dlog("  isVisible       =", window.isVisible())
    _dlog("  windowState     =", window.windowState())
    scr = window.screen()
    if scr is not None:
        _dlog("  screen name     =", scr.name())
        _dlog("  screen geom     =", scr.geometry())
        _dlog("  screen avail    =", scr.availableGeometry())
        _dlog("  devicePixelRatio=", scr.devicePixelRatio())

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
