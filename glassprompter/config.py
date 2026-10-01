"""Versioned, validated settings with crash-safe (atomic) writes."""
import json
import logging
import os
import secrets
from dataclasses import asdict, dataclass, field, fields

from . import paths

log = logging.getLogger(__name__)
SCHEMA = 1


@dataclass
class Settings:
    schema: int = SCHEMA
    # reading
    wpm: int = 140
    countdown: bool = True
    current_script_id: int = 0
    voice_follow: bool = False
    click_through: bool = False
    mirror: bool = False
    coach: bool = True
    # look
    font_px: int = 34
    font_family: str = "Segoe UI Variable Display"
    panel_alpha: float = 0.90
    clear_mode: bool = False
    read_line: float = 0.40
    reduce_motion: bool = False
    geometry: list = field(default_factory=list)      # [x, y, w, h] in logical pixels
    # privacy & remote
    hide_from_capture: bool = True
    remote_enabled: bool = True
    remote_port: int = 8765
    pin: str = ""
    # system
    start_with_windows: bool = False
    drop_dir: str = ""
    first_run_done: bool = False


LIMITS = {
    "wpm": (40, 400),
    "font_px": (14, 96),
    "panel_alpha": (0.2, 1.0),
    "read_line": (0.2, 0.7),
    "remote_port": (1024, 65535),
}


def new_pin():
    return "%06d" % secrets.randbelow(10 ** 6)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate(s):
    """Coerce types and clamp ranges so a hand-edited or corrupted file can never crash the app."""
    defaults = Settings()
    for f in fields(Settings):
        v = getattr(s, f.name)
        d = getattr(defaults, f.name)
        try:
            if isinstance(d, bool):
                v = bool(v)
            elif isinstance(d, int):
                v = int(v)
            elif isinstance(d, float):
                v = float(v)
            elif isinstance(d, str):
                v = str(v)
            elif isinstance(d, list):
                v = list(v) if isinstance(v, (list, tuple)) else []
        except (TypeError, ValueError):
            v = d
        if f.name in LIMITS:
            v = type(d)(_clamp(v, *LIMITS[f.name]))
        setattr(s, f.name, v)
    if not (len(s.pin) == 6 and s.pin.isdigit()):
        s.pin = new_pin()
    if len(s.geometry) != 4 or not all(isinstance(n, (int, float)) for n in s.geometry):
        s.geometry = []
    else:
        s.geometry = [int(n) for n in s.geometry]
        if s.geometry[2] < 200 or s.geometry[3] < 100:
            s.geometry = []
    s.schema = SCHEMA
    return s


def _from_dict(d):
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in d.items() if k in known})


def _migrate_legacy(d):
    """Map the pre-1.0 settings_v3.json keys onto the 1.0 schema."""
    out = {}
    for k in ("wpm", "font_px", "panel_alpha", "clear_mode", "hide_from_capture", "read_line",
              "reduce_motion", "pin", "font_family"):
        if k in d:
            out[k] = d[k]
    if "opacity" in d and "panel_alpha" not in d:          # very first (tkinter) version
        out["panel_alpha"] = d["opacity"]
    if "port" in d:
        out["remote_port"] = d["port"]
    if "remote" in d:
        out["remote_enabled"] = d["remote"]
    if all(d.get(k) is not None for k in ("x", "y", "w", "h")):
        out["geometry"] = [d["x"], d["y"], d["w"], d["h"]]
    out["first_run_done"] = True       # existing user: skip the welcome screen
    return out


class Config:
    def __init__(self, path=None):
        self.path = path or paths.settings_path()
        self.s = Settings()

    def load(self):
        data = None
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("settings root is not an object")
            except Exception as ex:
                bad = self.path + ".corrupt"
                log.warning("Settings file unreadable (%s); backed up to %s and reset", ex, bad)
                try:
                    os.replace(self.path, bad)
                except OSError:
                    pass
                data = None
        elif os.path.exists(paths.legacy_settings_path()) and self.path == paths.settings_path():
            try:
                with open(paths.legacy_settings_path(), encoding="utf-8") as f:
                    data = _migrate_legacy(json.load(f))
                log.info("Migrated legacy settings")
            except Exception as ex:
                log.warning("Legacy settings migration failed: %s", ex)
        if isinstance(data, dict) and "schema" not in data:
            data = self._migrate_pre_1_0(data)
        self.s = validate(_from_dict(data or {}))
        if not self.s.drop_dir:
            self.s.drop_dir = paths.default_drop_dir()
        return self.s

    def _migrate_pre_1_0(self, old):
        """settings.json without a schema was written by a pre-1.0 build. Prefer the newer
        settings_v3.json if it exists, keep a backup of the old file, and map the keys."""
        source = old
        legacy = paths.legacy_settings_path()
        if os.path.exists(legacy):
            try:
                with open(legacy, encoding="utf-8") as f:
                    source = json.load(f)
            except Exception:
                source = old
        try:
            import shutil
            shutil.copyfile(self.path, self.path + ".pre-1.0.bak")
        except OSError:
            pass
        log.info("Migrated pre-1.0 settings")
        return _migrate_legacy(source)

    def save(self):
        validate(self.s)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self.s), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)          # atomic on NTFS: never a half-written file
        except OSError as ex:
            log.error("Could not save settings: %s", ex)
