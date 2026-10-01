"""Windows backend: SetWindowDisplayAffinity, RegisterHotKey, DWM acrylic, Run-key autostart, SAPI voice."""
import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes

from .common import HotkeyManagerBase, launch_args

log = logging.getLogger(__name__)

OS = "windows"
MOD = "Ctrl+Alt"
CMD = "Ctrl"
TRAY = "tray (bottom-right of the taskbar)"
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x00, 0x11
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK = {"SPACE": 0x20, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
      "E": 0x45, "H": 0x48, "R": 0x52, "V": 0x56, "G": 0x47, "PGUP": 0x21, "PGDN": 0x22}
VK_CONTROL, VK_MENU = 0x11, 0x12
CREATE_NO_WINDOW = 0x08000000

user32 = ctypes.windll.user32
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetAsyncKeyState.restype = ctypes.c_short


def _hwnd(w):
    """Native window handle, or 0 under a non-Windows Qt plugin (e.g. headless 'offscreen' in CI)."""
    if not hasattr(w, "winId"):
        return int(w)
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != "windows":
            return 0
    except Exception:
        pass
    return int(w.winId())


def set_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GlassPrompter.App")
    except Exception:
        pass


def prepare_window(w):
    """Nothing extra needed on Windows: Qt's Tool + StaysOnTop already does the job."""
    return True


# ------------------------------------------------------------------ screen-capture exclusion
def capture_support():
    try:
        build = sys.getwindowsversion().build
    except Exception:
        build = 0
    if build >= 19041:
        return "full", "Hidden from Zoom, Teams, Meet, OBS and screenshots."
    return "none", "Hiding from screen share needs Windows 10 version 2004 or newer."


def set_capture_excluded(w, excluded=True):
    """Hide a window from screen sharing, recording and screenshots (Windows 10 2004+)."""
    if os.environ.get("GLASSPROMPTER_ALLOW_CAPTURE") == "1":      # developer flag: screenshots for docs/tests
        excluded = False
    return bool(user32.SetWindowDisplayAffinity(_hwnd(w), WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE))


def is_capture_excluded(w):
    d = wintypes.DWORD(0)
    if not user32.GetWindowDisplayAffinity(_hwnd(w), ctypes.byref(d)):
        return False
    return d.value == WDA_EXCLUDEFROMCAPTURE


# ------------------------------------------------------------------ click-through (ghost mode)
GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000


def set_click_through(w, on):
    hwnd = _hwnd(w)
    get, put = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
    get.restype, get.argtypes = ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int]
    put.restype, put.argtypes = ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    style = get(hwnd, GWL_EXSTYLE)
    new = (style | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on else (style & ~WS_EX_TRANSPARENT)
    if new != style:
        put(hwnd, GWL_EXSTYLE, new)
    return bool(get(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT) == on


# ------------------------------------------------------------------ frosted glass
class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class _ACCENT(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


DWMWA_DARK, DWMWA_CORNERS, DWMWA_BORDER, DWMWA_BACKDROP = 20, 33, 34, 38
BACKDROPS = {"none": 1, "mica": 2, "acrylic": 3}


def _dwm_int(hwnd, attr, value):
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))


def backdrop_supported():
    """System backdrops need Windows 11 22H2 (build 22621) or newer."""
    try:
        return sys.getwindowsversion().build >= 22621
    except Exception:
        return False


def apply_backdrop(w, kind="acrylic"):
    """Frosted blur behind a translucent window. Returns 'dwm', 'accent' or '' (unsupported)."""
    hwnd = _hwnd(w)
    try:
        _dwm_int(hwnd, DWMWA_DARK, 1)
        _dwm_int(hwnd, DWMWA_CORNERS, 2)                       # rounded
        _dwm_int(hwnd, DWMWA_BORDER, -2)                       # DWMWA_COLOR_NONE: we paint our own aurora rim
        if kind == "none":
            _dwm_int(hwnd, DWMWA_BACKDROP, 1)
            _accent(hwnd, 0, 0)
            return ""
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(_MARGINS(-1, -1, -1, -1)))
        if backdrop_supported() and _dwm_int(hwnd, DWMWA_BACKDROP, BACKDROPS.get(kind, 3)) == 0:
            return "dwm"
        if _accent(hwnd, 4, 0x30140C0A):                       # Windows 10 acrylic fallback
            return "accent"
    except Exception as ex:
        log.debug("backdrop failed: %s", ex)
    return ""


def _accent(hwnd, state, abgr):
    a = _ACCENT(state, 2, abgr, 0)
    d = _WCAD(19, ctypes.cast(ctypes.pointer(a), ctypes.c_void_p), ctypes.sizeof(a))
    return bool(user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(d)))


# ------------------------------------------------------------------ global hotkeys
def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def parse_hotkey_msg(message_ptr):
    """Return the hotkey id if the native MSG is WM_HOTKEY, else None."""
    try:
        msg = wintypes.MSG.from_address(int(message_ptr))
    except Exception:
        return None
    return int(msg.wParam) if msg.message == WM_HOTKEY else None


def make_hotkeys(app, callback, widget):
    from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

    class _Filter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                hid = parse_hotkey_msg(message)
                if hid is not None:
                    QTimer.singleShot(0, lambda: callback(hid))
                    return True, 0
            return False, 0

    class Manager(HotkeyManagerBase):
        """RegisterHotKey; combos another app already owns fall back to keyboard polling so they still work."""

        def __init__(self):
            super().__init__(app, callback)
            self.hwnd = _hwnd(widget)
            self.filter = _Filter()
            app.installNativeEventFilter(self.filter)
            self.poll = {}
            self.prev = {}
            self.timer = QTimer(interval=30, timeout=self._poll)

        def register(self, hid, key):
            ok = bool(user32.RegisterHotKey(self.hwnd, hid, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK[key]))
            self.ok[hid] = ok
            if not ok:
                log.warning("Ctrl+Alt+%s is taken by another app (error %s); polling instead", key,
                            ctypes.GetLastError())
                self.poll[hid] = VK[key]
                if not self.timer.isActive():
                    self.timer.start()
            return ok

        def _poll(self):
            held = key_down(VK_CONTROL) and key_down(VK_MENU)
            for hid, vk in self.poll.items():
                down = held and key_down(vk)
                if down and not self.prev.get(hid):
                    callback(hid)
                self.prev[hid] = down

        def unregister_all(self):
            for hid in list(self.ok):
                user32.UnregisterHotKey(self.hwnd, hid)
            self.timer.stop()
            self.poll.clear()
            super().unregister_all()

    return Manager()


# ------------------------------------------------------------------ start at login
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GlassPrompter"


def launch_command():
    return " ".join('"%s"' % a if " " in a or a.endswith(".exe") else a for a in launch_args())


def set_autostart(enabled):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as ex:
        log.error("Autostart change failed: %s", ex)
        return False


def is_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ files, network, speech
def documents_dir():
    """The user's real Documents folder (follows OneDrive folder redirection)."""
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_base():
    return os.environ.get("APPDATA") or os.path.expanduser("~")


def network_category():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              "(Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory"],
                             capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW)
        return out.stdout.strip()
    except Exception:
        return ""


def network_note():
    if network_category() == "Public":
        return ("This Wi-Fi is set to Public in Windows. If your phone can't connect, allow Glass Prompter through "
                "the firewall when Windows asks, or set this network to Private: Settings > Network & internet > "
                "Wi-Fi > your network.")
    return ""


def tts_command(path, wpm):
    rate = max(-10, min(10, int(round((wpm - 170) / 14.0))))         # SAPI: 0 is roughly 170 wpm
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | "
          "Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
          "$s.Rate = %d; $s.Speak([IO.File]::ReadAllText('%s')); $s.Dispose()" % (rate, path.replace("'", "''")))
    return "powershell", ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps]


def mic_error(msg):
    if "Error querying device" in msg or "Invalid device" in msg or "-9996" in msg:
        return "No microphone found. Plug one in or pick another in Settings."
    if "-9999" in msg or "Unanticipated host error" in msg:
        return ("Windows blocked the microphone. Allow it in Settings > Privacy & security > Microphone > "
                "Let desktop apps access your microphone.")
    return msg


def open_mic_settings():
    os.startfile("ms-settings:privacy-microphone")
