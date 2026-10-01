"""Thin, defensive wrappers over the Windows APIs the app relies on."""
import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x00, 0x11
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK = {"SPACE": 0x20, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
      "E": 0x45, "H": 0x48, "R": 0x52, "V": 0x56, "G": 0x47, "PGUP": 0x21, "PGDN": 0x22}
CREATE_NO_WINDOW = 0x08000000

if IS_WINDOWS:
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


# ------------------------------------------------------------------ screen-capture exclusion
def set_capture_excluded(hwnd, excluded=True):
    """Hide a window from screen sharing, recording and screenshots (Windows 10 2004+)."""
    if not IS_WINDOWS:
        return False
    if os.environ.get("GLASSPROMPTER_ALLOW_CAPTURE") == "1":      # developer flag: screenshots for docs/tests
        excluded = False
    return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE))


def is_capture_excluded(hwnd):
    if not IS_WINDOWS:
        return False
    d = wintypes.DWORD(0)
    if not user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(d)):
        return False
    return d.value == WDA_EXCLUDEFROMCAPTURE


# ------------------------------------------------------------------ global hotkeys
def register_hotkey(hwnd, hotkey_id, vk, mods=MOD_CONTROL | MOD_ALT):
    if not IS_WINDOWS:
        return False
    ok = bool(user32.RegisterHotKey(hwnd, hotkey_id, mods | MOD_NOREPEAT, vk))
    if not ok:
        log.warning("Hotkey %s is taken by another app (error %s)", hotkey_id, ctypes.GetLastError())
    return ok


def unregister_hotkey(hwnd, hotkey_id):
    if IS_WINDOWS:
        user32.UnregisterHotKey(hwnd, hotkey_id)


def parse_hotkey_msg(message_ptr):
    """Return the hotkey id if the native MSG is WM_HOTKEY, else None."""
    try:
        msg = wintypes.MSG.from_address(int(message_ptr))
    except Exception:
        return None
    return int(msg.wParam) if msg.message == WM_HOTKEY else None


GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_LAYERED = -20, 0x20, 0x80000


def set_click_through(hwnd, on):
    """Let mouse clicks pass straight through a window to whatever is behind it."""
    if not IS_WINDOWS:
        return False
    get = user32.GetWindowLongPtrW
    put = user32.SetWindowLongPtrW
    get.restype = ctypes.c_ssize_t
    get.argtypes = [wintypes.HWND, ctypes.c_int]
    put.restype = ctypes.c_ssize_t
    put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    style = get(hwnd, GWL_EXSTYLE)
    new = (style | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on else (style & ~WS_EX_TRANSPARENT)
    if new != style:
        put(hwnd, GWL_EXSTYLE, new)
    return bool(get(hwnd, GWL_EXSTYLE) & WS_EX_TRANSPARENT) == on


# ------------------------------------------------------------------ frosted glass (Windows 11)
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
    if not IS_WINDOWS:
        return False
    try:
        return sys.getwindowsversion().build >= 22621
    except Exception:
        return False


def apply_backdrop(hwnd, kind="acrylic"):
    """Frosted blur behind a translucent window. Returns 'dwm', 'accent' or '' (unsupported)."""
    if not IS_WINDOWS:
        return ""
    try:
        _dwm_int(hwnd, DWMWA_DARK, 1)
        _dwm_int(hwnd, DWMWA_CORNERS, 2)                       # rounded
        _dwm_int(hwnd, DWMWA_BORDER, 0x00403A36)               # subtle hairline (COLORREF, BGR)
        if kind == "none":
            _dwm_int(hwnd, DWMWA_BACKDROP, 1)
            _accent(hwnd, 0, 0)
            return ""
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(_MARGINS(-1, -1, -1, -1)))
        if backdrop_supported() and _dwm_int(hwnd, DWMWA_BACKDROP, BACKDROPS.get(kind, 3)) == 0:
            return "dwm"
        if _accent(hwnd, 4, 0x30181812):                       # Windows 10 acrylic fallback
            return "accent"
    except Exception as ex:
        log.debug("backdrop failed: %s", ex)
    return ""


def _accent(hwnd, state, abgr):
    a = _ACCENT(state, 2, abgr, 0)
    d = _WCAD(19, ctypes.cast(ctypes.pointer(a), ctypes.c_void_p), ctypes.sizeof(a))
    return bool(user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(d)))


def key_down(vk):
    if not IS_WINDOWS:
        return False
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


VK_CONTROL, VK_MENU = 0x11, 0x12


# ------------------------------------------------------------------ start with Windows
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GlassPrompter"


def launch_command():
    if getattr(sys, "frozen", False):
        return '"%s" --background' % sys.executable
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    import os
    script = os.path.abspath(sys.argv[0])
    return '"%s" "%s" --background' % (exe, script)


def set_autostart(enabled):
    if not IS_WINDOWS:
        return False
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
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ network
def network_category():
    """'Public', 'Private', 'DomainAuthenticated' or '' if unknown."""
    if not IS_WINDOWS:
        return ""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              "(Get-NetConnectionProfile | Select-Object -First 1).NetworkCategory"],
                             capture_output=True, text=True, timeout=8, creationflags=CREATE_NO_WINDOW)
        return out.stdout.strip()
    except Exception:
        return ""
