"""One API over the OS-specific bits (Windows and macOS; a no-op fallback elsewhere).

Everything here degrades gracefully: if a native call fails the app keeps running and the UI tells
the user honestly what does and doesn't work (for example screen-share hiding on macOS 15+).

Functions every backend provides:
    OS, MOD, MOD_KEYS, TRAY, prepare_window(w), set_capture_excluded(w, on), exclude_all_windows(skip), is_capture_excluded(w),
    capture_support() -> (level, note), set_click_through(w, on), backdrop_supported(),
    apply_backdrop(w, kind) -> str, set_autostart(on), is_autostart(), network_note(),
    documents_dir(), data_base(), tts_command(path, wpm), mic_error(msg), open_mic_settings(),
    make_hotkeys(app, callback, widget) -> HotkeyManager, set_app_id()
"""
import sys

if sys.platform == "win32":
    from .windows import *          # noqa: F401,F403
elif sys.platform == "darwin":
    from .macos import *            # noqa: F401,F403
else:
    from .generic import *          # noqa: F401,F403

from .common import HOTKEY_KEYS, hotkey_label, launch_args   # noqa: F401,E402
