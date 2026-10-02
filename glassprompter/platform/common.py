"""Shared, Qt-free helpers for the platform backends."""
import os
import sys

# Global shortcut keys (same letters on every OS; the modifier differs: Ctrl+Alt / Control+Option).
HOTKEY_KEYS = ("SPACE", "UP", "DOWN", "LEFT", "RIGHT", "R", "H", "E", "V", "G", "PGUP", "PGDN",
               "LBRACKET", "RBRACKET")
KEY_NAMES = {"SPACE": "Space", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
             "PGUP": "PgUp", "PGDN": "PgDn", "LBRACKET": "[", "RBRACKET": "]"}


def hotkey_label(mod, key):
    return "%s+%s" % (mod, KEY_NAMES.get(key, key))


def launch_args(background=True):
    """Command line that starts this app again (frozen bundle or source checkout)."""
    extra = ["--background"] if background else []
    if getattr(sys, "frozen", False):
        return [sys.executable] + extra
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"
    return [exe, os.path.abspath(sys.argv[0])] + extra


class HotkeyManagerBase:
    """register(hid, key) -> bool; unregister_all(); taken() -> list of keys that fell back or failed."""

    def __init__(self, app, callback):
        self.app, self.callback = app, callback
        self.ok = {}

    def register(self, hid, key):
        self.ok[hid] = False
        return False

    def unregister_all(self):
        self.ok.clear()

    def failed(self):
        return [h for h, ok in self.ok.items() if not ok]
