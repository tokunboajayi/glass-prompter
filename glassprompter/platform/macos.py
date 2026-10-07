"""macOS backend: NSWindow sharing/levels via PyObjC, Carbon global hotkeys (no Accessibility permission
needed), NSVisualEffectView vibrancy, LaunchAgent autostart and the built-in `say` voice.

Honesty note: since macOS 15 (Sequoia), ScreenCaptureKit-based capture ignores NSWindow.sharingType, and
Apple offers no workaround. We still set it (older capture paths respect it) but tell the user to share a
window instead of the whole screen, rather than showing a green "hidden" badge that would be a lie.
"""
import ctypes
import logging
import os
import platform as _platform
import plistlib
import struct
import subprocess

from .common import HotkeyManagerBase, launch_args

log = logging.getLogger(__name__)

OS = "macos"
MOD = "Ctrl+Option"
CMD = "Cmd"
TRAY = "menu bar (top-right of the screen)"

try:
    import objc                                    # pyobjc-core
    from AppKit import (NSAppearance, NSVisualEffectView, NSViewHeightSizable, NSViewWidthSizable)
except Exception:                                  # running from a bare Python without PyObjC
    objc = None

NSWindowSharingNone, NSWindowSharingReadOnly = 0, 1
NSStatusWindowLevel = 25
CAN_JOIN_ALL_SPACES, STATIONARY, FULLSCREEN_AUX = 1 << 0, 1 << 4, 1 << 8
NSWindowBelow = -1


def _macos_major():
    try:
        return int(_platform.mac_ver()[0].split(".")[0])
    except Exception:
        return 0


def _native_qpa():
    """Only touch Cocoa when Qt really runs on Cocoa (not the headless 'offscreen' plugin used in CI)."""
    try:
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.platformName() == "cocoa"
    except Exception:
        return False


def _nswindow(w):
    if objc is None or not _native_qpa():
        return None
    try:
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(w.winId())))
        return view.window()
    except Exception as ex:
        log.debug("no NSWindow: %s", ex)
        return None


def set_app_id():
    pass


def prepare_window(w, above_prompter=False):
    """Float above full-screen apps on every Space and never hide when another app is focused.

    Dialogs (Settings, Phone remote, Scripts, the AI window) pass above_prompter=True: they go one level ABOVE the
    prompter and come to the front. On the same level they could open behind it, and because most are modal the
    whole app then looked frozen (nothing clickable)."""
    win = _nswindow(w)
    if win is None:
        return False
    try:
        win.setHidesOnDeactivate_(False)
        win.setCollectionBehavior_(CAN_JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUX)
        win.setLevel_(NSStatusWindowLevel + 1 if above_prompter else NSStatusWindowLevel)
        win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameVibrantDark"))
        if above_prompter:
            win.orderFrontRegardless()
            win.makeKeyWindow()
        return True
    except Exception as ex:
        log.debug("prepare_window: %s", ex)
        return False


NSFloatingWindowLevel = 3


def lower_for_dialogs(w, lowered):
    """While a dialog is open, drop the prompter to the normal floating level, so system windows (message boxes,
    the file picker, permission prompts) can never open behind it and leave the app unclickable."""
    win = _nswindow(w)
    if win is None:
        return False
    try:
        win.setLevel_(NSFloatingWindowLevel if lowered else NSStatusWindowLevel)
        return True
    except Exception as ex:
        log.debug("lower_for_dialogs: %s", ex)
        return False


# ------------------------------------------------------------------ taking screenshots (screen view, AI, S key)
SCREEN_PERMISSION_MSG = ("Allow Glass Prompter in System Settings \u203a Privacy & Security \u203a Screen & System Audio "
                         "Recording, then quit and reopen Glass Prompter.")
SCREEN_BLANK_MSG = ("macOS gave a blank picture. Open System Settings \u203a Privacy & Security \u203a Screen & System "
                    "Audio Recording, switch Glass Prompter off and on again (an update can reset it), then quit "
                    "and reopen Glass Prompter.")
_asked_screen = False


def _coregraphics():
    return ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


def screen_capture_allowed():
    """macOS 10.15+: has the user allowed this app to record the screen? (Without it, captures come back gray or
    show only the wallpaper.)"""
    try:
        f = _coregraphics().CGPreflightScreenCaptureAccess
        f.restype = ctypes.c_bool
        return bool(f())
    except Exception:                                # older macOS / no CoreGraphics symbol: just try
        return True


def request_screen_capture():
    """Ask once per session: macOS shows its permission prompt the first time, after that we open the right
    System Settings page so the user can switch it on."""
    global _asked_screen
    try:
        f = _coregraphics().CGRequestScreenCaptureAccess
        f.restype = ctypes.c_bool
        ok = bool(f())
    except Exception:
        ok = False
    if not ok and not _asked_screen:
        _asked_screen = True
        try:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
        except OSError:
            pass
    return ok


def grab_screen_png(rect=None, timeout=10):
    """PNG bytes of the screen (or the rect x,y,w,h in points) using macOS's own screencapture tool. It works on
    every macOS version, unlike the older capture call Qt uses, which returns a gray image on recent macOS."""
    import tempfile
    fd, path = tempfile.mkstemp(prefix="gp_shot_", suffix=".png")
    os.close(fd)
    args = ["/usr/sbin/screencapture", "-x", "-t", "png"]
    if rect:
        args += ["-R", "%d,%d,%d,%d" % tuple(int(v) for v in rect)]
    try:
        subprocess.run(args + [path], timeout=timeout, capture_output=True, check=False)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ------------------------------------------------------------------ screen-capture exclusion
def capture_support():
    if objc is None:
        return "none", "Screen-share hiding needs the PyObjC framework."
    if _macos_major() >= 15:
        return "partial", ("macOS 15+ lets screen recorders see every window. Share a single window or app "
                           "(not your whole screen) and the prompter stays private.")
    return "full", "Hidden from screen sharing and screenshots."


def set_capture_excluded(w, excluded=True):
    if os.environ.get("GLASSPROMPTER_ALLOW_CAPTURE") == "1":
        excluded = False
    win = _nswindow(w)
    if win is None:
        return False
    try:
        win.setSharingType_(NSWindowSharingNone if excluded else NSWindowSharingReadOnly)
        return True
    except Exception:
        return False


def exclude_all_windows(skip=()):
    """Hide every window of this app from capture (sheets, alerts, open panels, menus). See windows.py."""
    if os.environ.get("GLASSPROMPTER_ALLOW_CAPTURE") == "1" or objc is None or not _native_qpa():
        return 0
    try:
        from AppKit import NSApp
        skip_w = {id(x) for x in (_nswindow(w) for w in skip if w is not None) if x is not None}
        skip_n = [x for x in (_nswindow(w) for w in skip if w is not None) if x is not None]
        n = 0
        for win in NSApp.windows():
            if any(win == k for k in skip_n) or id(win) in skip_w:
                continue
            if win.sharingType() != NSWindowSharingNone:
                win.setSharingType_(NSWindowSharingNone)
                n += 1
        return n
    except Exception as ex:
        log.debug("exclude_all_windows: %s", ex)
        return 0


def is_capture_excluded(w):
    win = _nswindow(w)
    try:
        return win is not None and win.sharingType() == NSWindowSharingNone
    except Exception:
        return False


def set_click_through(w, on):
    win = _nswindow(w)
    if win is None:
        return False
    try:
        win.setIgnoresMouseEvents_(bool(on))
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ vibrancy
def backdrop_supported():
    return objc is not None


def apply_backdrop(w, kind="acrylic"):
    """Put a behind-window NSVisualEffectView under Qt's view. Returns 'vibrancy' or ''."""
    win = _nswindow(w)
    if win is None:
        return ""
    try:
        content = win.contentView()
        frame_view = content.superview()
        old = getattr(w, "_gp_vev", None)
        if kind == "none":
            if old is not None:
                old.removeFromSuperview()
                w._gp_vev = None
            return ""
        if old is None:
            vev = NSVisualEffectView.alloc().initWithFrame_(content.frame())
            vev.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            vev.setMaterial_(13)                   # HUD window: dark, strong blur
            vev.setBlendingMode_(0)                # behind window
            vev.setState_(1)                       # always active, even when the app isn't focused
            vev.setWantsLayer_(True)
            vev.layer().setCornerRadius_(14.0)
            vev.layer().setMasksToBounds_(True)
            frame_view.addSubview_positioned_relativeTo_(vev, NSWindowBelow, content)
            w._gp_vev = vev
        win.setOpaque_(False)
        return "vibrancy"
    except Exception as ex:
        log.debug("vibrancy failed: %s", ex)
        return ""


# ------------------------------------------------------------------ global hotkeys (Carbon)
KEYCODES = {"SPACE": 49, "LEFT": 123, "RIGHT": 124, "DOWN": 125, "UP": 126, "R": 15, "H": 4, "E": 14,
            "V": 9, "G": 5, "PGUP": 116, "PGDN": 121, "LBRACKET": 33, "RBRACKET": 30}
CONTROL_KEY, OPTION_KEY = 0x1000, 0x0800


def _fourcc(s):
    return struct.unpack(">I", s.encode("ascii"))[0]


def make_hotkeys(app, callback, widget):
    from PySide6.QtCore import QTimer

    class Manager(HotkeyManagerBase):
        """RegisterEventHotKey works in Cocoa apps and, unlike key monitors, needs no Accessibility permission."""

        def __init__(self):
            super().__init__(app, callback)
            self.refs = {}
            self.carbon = None
            try:
                c = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

                class HotKeyID(ctypes.Structure):
                    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

                class TypeSpec(ctypes.Structure):
                    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

                self.HotKeyID = HotKeyID
                handler_t = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
                c.GetApplicationEventTarget.restype = ctypes.c_void_p
                c.InstallEventHandler.argtypes = [ctypes.c_void_p, handler_t, ctypes.c_uint32,
                                                  ctypes.POINTER(TypeSpec), ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_void_p)]
                c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, HotKeyID, ctypes.c_void_p,
                                                  ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
                c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
                c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                                ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]

                def on_event(_call, event, _data):
                    hk = HotKeyID()
                    c.GetEventParameter(event, _fourcc("----"), _fourcc("hkid"), None, ctypes.sizeof(hk), None,
                                        ctypes.byref(hk))
                    QTimer.singleShot(0, lambda hid=int(hk.id): callback(hid))
                    return 0

                self._handler = handler_t(on_event)            # keep a reference: ctypes callbacks must live
                spec = TypeSpec(_fourcc("keyb"), 5)            # kEventClassKeyboard / kEventHotKeyPressed
                ref = ctypes.c_void_p()
                st = c.InstallEventHandler(c.GetApplicationEventTarget(), self._handler, 1, ctypes.byref(spec),
                                           None, ctypes.byref(ref))
                if st == 0:
                    self.carbon = c
                else:
                    log.warning("InstallEventHandler failed: %s", st)
            except Exception as ex:
                log.warning("Global shortcuts unavailable: %s", ex)

        def register(self, hid, key):
            ok = False
            if self.carbon is not None:
                ref = ctypes.c_void_p()
                st = self.carbon.RegisterEventHotKey(KEYCODES[key], CONTROL_KEY | OPTION_KEY,
                                                     self.HotKeyID(_fourcc("GlPr"), hid),
                                                     self.carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
                ok = st == 0
                if ok:
                    self.refs[hid] = ref
            self.ok[hid] = ok
            return ok

        def unregister_all(self):
            for ref in self.refs.values():
                try:
                    self.carbon.UnregisterEventHotKey(ref)
                except Exception:
                    pass
            self.refs.clear()
            super().unregister_all()

    return Manager()


# ------------------------------------------------------------------ start at login (LaunchAgent)
AGENT = os.path.expanduser("~/Library/LaunchAgents/app.glassprompter.plist")


def set_autostart(enabled):
    try:
        if enabled:
            os.makedirs(os.path.dirname(AGENT), exist_ok=True)
            with open(AGENT, "wb") as f:
                plistlib.dump({"Label": "app.glassprompter", "ProgramArguments": launch_args(),
                               "RunAtLoad": True, "ProcessType": "Interactive"}, f)
        elif os.path.exists(AGENT):
            os.remove(AGENT)
        return True
    except OSError as ex:
        log.error("Autostart change failed: %s", ex)
        return False


def is_autostart():
    return os.path.exists(AGENT)


# ------------------------------------------------------------------ files, network, speech
def documents_dir():
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_base():
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support")


def network_note():
    return "If macOS asks whether Glass Prompter may accept incoming network connections, click Allow."


def tts_command(path, wpm):
    return "say", ["-r", str(int(max(80, min(400, wpm)))), "-f", path]


def mic_error(msg):
    if "Error querying device" in msg or "Invalid device" in msg or "-9996" in msg:
        return "No microphone found. Plug one in or pick another in Settings."
    if "-9986" in msg or "-9999" in msg or "Internal PortAudio error" in msg:
        return ("macOS blocked the microphone. Allow Glass Prompter in System Settings > Privacy & Security > "
                "Microphone, then try again.")
    return msg


def open_mic_settings():
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"])
