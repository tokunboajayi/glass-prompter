import json
import os

from glassprompter import config, paths


def test_defaults_and_pin_generated():
    c = config.Config()
    s = c.load()
    assert s.wpm == 140 and s.hide_from_capture is True
    assert len(s.pin) == 6 and s.pin.isdigit()
    assert s.drop_dir


def test_round_trip_is_atomic(tmp_path):
    c = config.Config()
    c.load()
    c.s.wpm = 180
    c.s.geometry = [10, 20, 640, 220]
    c.save()
    assert not os.path.exists(c.path + ".tmp")
    c2 = config.Config()
    s2 = c2.load()
    assert s2.wpm == 180 and s2.geometry == [10, 20, 640, 220] and s2.pin == c.s.pin


def test_garbage_values_are_clamped():
    path = paths.settings_path()
    with open(path, "w") as f:
        json.dump({"schema": 1, "wpm": 99999, "font_px": "huge", "panel_alpha": -4, "pin": "12",
                   "geometry": [1, 2], "remote_port": 80, "unknown_key": 1}, f)
    s = config.Config().load()
    assert s.wpm == 400
    assert s.font_px == 34              # unparseable -> default
    assert s.panel_alpha == 0.2
    assert len(s.pin) == 6
    assert s.geometry == []
    assert s.remote_port == 1024


def test_corrupt_file_is_backed_up_not_fatal():
    path = paths.settings_path()
    with open(path, "w") as f:
        f.write("{not json")
    s = config.Config().load()
    assert s.wpm == 140
    assert os.path.exists(path + ".corrupt")


def test_pre_1_0_settings_json_is_migrated_not_misread(monkeypatch, tmp_path):
    """A schema-less settings.json (first version) must not mask the newer settings_v3.json."""
    with open(paths.settings_path(), "w") as f:
        json.dump({"font_size": 26, "speed": 45, "opacity": 0.8, "hide_from_capture": True}, f)
    legacy = tmp_path / "v3.json"
    legacy.write_text(json.dumps({"wpm": 155, "font_px": 40, "pin": "654321"}))
    monkeypatch.setattr(paths, "legacy_settings_path", lambda: str(legacy))
    s = config.Config().load()
    assert (s.wpm, s.font_px, s.pin) == (155, 40, "654321")
    assert os.path.exists(paths.settings_path() + ".pre-1.0.bak")


def test_pre_1_0_without_v3_keeps_what_it_can(monkeypatch, tmp_path):
    with open(paths.settings_path(), "w") as f:
        json.dump({"opacity": 0.7, "clear_mode": True}, f)
    monkeypatch.setattr(paths, "legacy_settings_path", lambda: str(tmp_path / "missing.json"))
    s = config.Config().load()
    assert s.panel_alpha == 0.7 and s.clear_mode is True and s.wpm == 140


def test_legacy_settings_are_migrated(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy_settings_v3.json"
    legacy.write_text(json.dumps({"wpm": 170, "port": 9000, "remote": False, "x": 5, "y": 6, "w": 700, "h": 230,
                                  "pin": "123456"}))
    monkeypatch.setattr(paths, "legacy_settings_path", lambda: str(legacy))
    s = config.Config().load()
    assert (s.wpm, s.remote_port, s.remote_enabled, s.pin) == (170, 9000, False, "123456")
    assert s.geometry == [5, 6, 700, 230]
    assert s.first_run_done is True
