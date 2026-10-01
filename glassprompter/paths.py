"""Filesystem locations. No Qt imports here so tests and the server can use it headless."""
import os
import sys

from . import APP_ID, APP_NAME
from . import platform as native


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
    return ensure(os.path.join(native.data_base(), APP_ID))


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
    """The user's real Documents folder (follows OneDrive redirection on Windows)."""
    return native.documents_dir()


MODEL_NAME = "vosk-model-small-en-us-0.15"


def build_dir():
    """Where the build scripts keep downloads and PyInstaller output (outside OneDrive / iCloud)."""
    if os.environ.get("LOCALAPPDATA"):
        base = os.environ["LOCALAPPDATA"]
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Caches")
    else:
        base = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "GlassPrompter-build")


def model_dir():
    """Offline speech model for Voice Follow: bundled with the app, or a dev copy."""
    candidates = [
        os.environ.get("GLASSPROMPTER_MODEL", ""),
        os.path.join(package_dir(), "models", MODEL_NAME),
        os.path.join(data_dir(), "models", MODEL_NAME),
        os.path.join(build_dir(), "models", MODEL_NAME),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "am", "final.mdl")):
            return c
    return None


def default_drop_dir():
    return os.path.join(documents_dir(), APP_NAME)


def backup_dir():
    return ensure(os.path.join(data_dir(), "backups"))


def voices_dir():
    """Downloaded natural (neural) voices for Read Aloud."""
    return ensure(os.path.join(data_dir(), "voices"))
