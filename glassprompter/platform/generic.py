"""Fallback backend (Linux and anything else): everything works except the OS-specific extras."""
import os
import shutil
import subprocess

from .common import HotkeyManagerBase

OS = "linux"
MOD = "Ctrl+Alt"
CMD = "Ctrl"
TRAY = "system tray"


def set_app_id():
    pass


def prepare_window(w):
    return True


def capture_support():
    return "none", "This system can't hide windows from screen sharing. Share a single window instead."


def set_capture_excluded(w, excluded=True):
    return False


def exclude_all_windows(skip=()):
    return 0


def is_capture_excluded(w):
    return False


def set_click_through(w, on):
    try:
        from PySide6.QtCore import Qt
        w.setWindowFlag(Qt.WindowType.WindowTransparentForInput, bool(on))
        w.show()
        return True
    except Exception:
        return False


def backdrop_supported():
    return False


def apply_backdrop(w, kind="acrylic"):
    return ""


def make_hotkeys(app, callback, widget):
    return HotkeyManagerBase(app, callback)


def set_autostart(enabled):
    return False


def is_autostart():
    return False


def documents_dir():
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_base():
    return os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def network_note():
    return ""


def tts_command(path, wpm):
    exe = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak"
    return exe, ["-s", str(int(wpm)), "-f", path]


def mic_error(msg):
    if "Error querying device" in msg or "Invalid device" in msg:
        return "No microphone found. Plug one in or pick another in Settings."
    return msg


def open_mic_settings():
    try:
        subprocess.Popen(["xdg-open", "settings://sound"])
    except Exception:
        pass
