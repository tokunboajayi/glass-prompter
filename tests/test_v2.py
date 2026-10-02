"""2.0: smooth voice glide, cross-platform layer, backups/export."""
import os
import sqlite3
import sys

from glassprompter import engine, paths, scripts
from glassprompter import platform as native
from glassprompter.platform import common


def test_voice_target_glides_within_a_line_and_never_straddles():
    word_line = [0, 0, 0, 0, 2, 2]                 # line 1 is blank
    assert engine.voice_target(word_line, -1) == 0.0
    ts = [engine.voice_target(word_line, c) for c in range(6)]
    assert ts == sorted(ts)                        # never scrolls backwards while reading forward
    for c, t in enumerate(ts):
        assert abs(t - word_line[c]) <= 0.3 + 1e-9  # current line always inside the reading band
    assert engine.voice_target([], 3) == 0.0
    assert engine.voice_target(word_line, 99) == engine.voice_target(word_line, 5)


def test_platform_backend_matches_os():
    expected = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    assert native.OS == expected
    for name in ("prepare_window", "set_capture_excluded", "is_capture_excluded", "capture_support",
                 "set_click_through", "apply_backdrop", "backdrop_supported", "set_autostart", "is_autostart",
                 "network_note", "documents_dir", "data_base", "tts_command", "mic_error", "make_hotkeys",
                 "MOD", "CMD", "TRAY"):
        assert hasattr(native, name), name
    level, note = native.capture_support()
    assert level in ("full", "partial", "none") and note


def test_tts_command_is_a_program_and_args(tmp_path):
    prog, args = native.tts_command(str(tmp_path / "x.txt"), 150)
    assert isinstance(prog, str) and isinstance(args, list) and all(isinstance(a, str) for a in args)


def test_mic_errors_are_human():
    assert "microphone" in native.mic_error("Error querying device -1").lower()


def test_hotkey_labels_and_launch_args():
    assert common.hotkey_label("Ctrl+Alt", "PGUP") == "Ctrl+Alt+PgUp"
    args = common.launch_args()
    assert args[-1] == "--background" and len(args) >= 2


def test_data_dir_override_and_backup_dir():
    assert paths.data_dir() == os.environ["GLASSPROMPTER_HOME"]
    assert os.path.isdir(paths.backup_dir())


def test_daily_backup_is_a_readable_snapshot(tmp_path):
    store = scripts.ScriptStore(paths.database_path())
    store.create("One", "first script body")
    dest = store.backup(str(tmp_path / "b"))
    assert store.backup(str(tmp_path / "b")) == dest           # once per day
    con = sqlite3.connect(dest)
    assert con.execute("SELECT title FROM scripts").fetchone()[0] == "One"
    con.close()
    for i in range(10):                                       # pruning keeps the newest N
        open(tmp_path / "b" / ("library-2000010%d.db" % i), "w").close()
    store.backup(str(tmp_path / "b"), keep=3)
    assert len([f for f in os.listdir(tmp_path / "b") if f.endswith(".db")]) == 3
    store.close()


def test_export_markdown_writes_every_script_with_safe_unique_names(tmp_path):
    store = scripts.ScriptStore(paths.database_path())
    store.create("Pitch: v2/final?", "Hello there")
    store.create("Pitch: v2/final?", "Second one")
    store.create("Keynote", "# Intro\nWelcome")
    n = scripts.export_markdown(store, str(tmp_path / "out"))
    files = sorted(os.listdir(tmp_path / "out"))
    assert n == 3 and len(files) == 3
    assert all(f.endswith(".md") and "/" not in f and ":" not in f and "?" not in f for f in files)
    bodies = sorted(open(tmp_path / "out" / f, encoding="utf-8").read() for f in files)
    assert "# Intro\nWelcome\n" in bodies
    store.close()


def test_title_from_filename_handles_both_path_styles():
    assert scripts.title_from_filename("/Users/aj/Desktop/my_talk.md") == "my talk"
    assert scripts.title_from_filename(r"C:\Users\aj\my-talk.docx") == "my talk"


def test_ghost_opacity_is_clamped_and_saved():
    from glassprompter import config
    c = config.Config()
    c.load()
    assert 0.15 <= c.s.ghost_opacity <= 1.0
    c.s.ghost_opacity = 0.01
    config.validate(c.s)
    assert c.s.ghost_opacity == 0.15


def test_ghost_hotkeys_and_remote_actions_exist():
    from glassprompter.app import HOTKEYS
    from glassprompter.server import api
    actions = {a for _, a in HOTKEYS.values()}
    assert {"ghost", "ghost_less", "ghost_more"} <= actions
    assert {"ghost_less", "ghost_more"} <= api.CONTROL_ACTIONS
    assert common.hotkey_label("Ctrl+Alt", "LBRACKET") == "Ctrl+Alt+["
