"""Filesystem locations. No Qt imports here so tests and the server can use it headless."""
import ctypes
import os
import sys

from . import APP_ID, APP_NAME


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def package_dir():
    """Read-only resources (static web files). Works from source and from a PyInstaller bundle."""
    if is_frozen():
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "glassprompter")
    return os.path.dirname(os.path.abspath(__file__))


def static_dir():
    return os.path.join(package_dir(), "server", "static")


def ensure(path):
    os.makedirs(path, exist_ok=True)
    return path


def data_dir():
    """Per-user writable data. GLASSPROMPTER_HOME overrides it (used by tests)."""
    override = os.environ.get("GLASSPROMPTER_HOME")
    if override:
        return ensure(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return ensure(os.path.join(base, APP_ID))


def log_dir():
    return ensure(os.path.join(data_dir(), "logs"))


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def legacy_settings_path():
    """Settings file written by the pre-1.0 single-file version."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_ID, "settings_v3.json")


def database_path():
    return os.path.join(data_dir(), "library.db")


def documents_dir():
    """The user's real Documents folder (follows OneDrive folder redirection)."""
    try:
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL = 5, SHGFP_TYPE_CURRENT = 0
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def default_drop_dir():
    return os.path.join(documents_dir(), APP_NAME)
