"""Shared, Qt-free helpers for the platform backends."""
import os
import sys

# Global shortcut keys (same letters on every OS; the modifier differs: Ctrl+Alt / Control+Option).
HOTKEY_KEYS = ("SPACE", "UP", "DOWN", "LEFT", "RIGHT", "R", "H", "E", "V", "G", "PGUP", "PGDN",
               "LBRACKET", "RBRACKET", "ENTER", "M")
KEY_NAMES = {"SPACE": "Space", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
             "PGUP": "PgUp", "PGDN": "PgDn", "LBRACKET": "[", "RBRACKET": "]", "ENTER": "Enter"}


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


def hard_exit(code=0):
    """End the process now, skipping all library teardown. Call it only after everything is saved and flushed.

    Python's interpreter teardown can destroy Qt objects in an unsafe order, and on Windows even os._exit()
    runs every DLL's shutdown code, which crashed (access violation) while worker threads were still busy.
    TerminateProcess skips that; elsewhere _exit() already does."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream and stream.flush()
        except Exception:                                # noqa: BLE001 - closed or missing console
            pass
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k32.TerminateProcess(k32.GetCurrentProcess(), int(code) & 0xFFFFFFFF)
    os._exit(int(code))


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
