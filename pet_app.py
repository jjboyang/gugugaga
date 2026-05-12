"""Desktop Pet — main entry point."""
import json
import os
import pathlib
import subprocess
import sys
import signal
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from pet.window import PetWindow
from pet.animation import AnimationEngine
from pet.ipc import PetIPC


DEBUG = os.environ.get("PET_DEBUG") == "1"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent


def _dlog(*args):
    if DEBUG:
        print("[pet]", *args, file=sys.stderr, flush=True)


def _claude_settings_path():
    if sys.platform == "darwin":
        base = pathlib.Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home() / "AppData" / "Roaming"))
    else:
        base = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
    return base / "claude" / "settings.json"


PET_HOOKS_TEMPLATE = {
    "UserPromptSubmit": [
        {"command": "{notify} question"}
    ],
    "PostToolUse": [
        {"matcher": "Read|Grep|Glob", "command": "{notify} reading"},
        {"matcher": "Edit|Write", "command": "{notify} writing"},
        {"matcher": "Bash", "command": "{notify} executing"},
    ],
    "Stop": [
        {"command": "{notify} done"}
    ],
    "SessionStart": [
        {"command": "{notify} idle"}
    ],
}


def _configure_hooks():
    settings_path = _claude_settings_path()
    notify_script = PROJECT_ROOT / "scripts" / "notify-pet.py"

    if sys.platform == "win32":
        notify_cmd = f"python \"{notify_script}\""
    else:
        notify_cmd = f"\"{notify_script}\""

    # Resolve template placeholders
    pet_hooks = {}
    for event, entries in PET_HOOKS_TEMPLATE.items():
        pet_hooks[event] = []
        for entry in entries:
            resolved = {}
            for k, v in entry.items():
                resolved[k] = v.replace("{notify}", notify_cmd)
            pet_hooks[event].append(resolved)

    # Read existing settings
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text("utf-8"))
        except json.JSONDecodeError:
            pass

    # Track whether hooks already match
    existing_hooks = existing.get("hooks", {})
    existing_pet_keys = set(existing_hooks) & set(pet_hooks)
    already_configured = False
    if existing_pet_keys:
        # Check one command to see if it points to our notify script
        sample = existing_hooks.get("SessionStart")
        if sample:
            first_cmd = sample[0].get("command", "") if sample else ""
            if str(notify_script) in first_cmd:
                already_configured = True

    changed = False
    if not already_configured:
        merged_hooks = dict(existing_hooks)
        for event, new_entries in pet_hooks.items():
            if event in merged_hooks:
                merged_hooks[event] = list(merged_hooks[event]) + new_entries
            else:
                merged_hooks[event] = new_entries
        existing["hooks"] = merged_hooks
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), "utf-8")
        changed = True

    # Open the settings file in the default editor
    try:
        if sys.platform == "win32":
            os.startfile(str(settings_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(settings_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(settings_path)], check=False)
    except OSError:
        pass

    return changed, str(settings_path)


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

    def on_hook_config():
        changed, path = _configure_hooks()
        if changed:
            QMessageBox.information(
                window, "Hook 已配置",
                f"宠物 Hook 已写入:\n{path}\n\n请确认脚本路径后保存文件。\n之后重新启动 Claude Code 即可生效。"
            )
        else:
            QMessageBox.information(
                window, "Hook 已存在",
                f"宠物 Hook 已存在, 文件:\n{path}\n\n请直接编辑修改 Hook 路径。"
            )

    window.hook_config_requested.connect(on_hook_config)

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
