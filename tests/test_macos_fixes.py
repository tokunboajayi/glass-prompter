"""Regressions found testing the macOS 2.4.2 build: long install paths, the crash guard, ghost mode, port reuse."""
import http.client
import os
import shutil
import socket
import sys
import tempfile

import pytest

from glassprompter import config, paths, scripts, tts
from glassprompter import platform as native
from glassprompter.server import api


# ---------------------------------------------------------------- espeak-ng data path
@pytest.fixture
def short_dir():
    """pytest's tmp_path is itself ~130 characters on macOS: link targets need a genuinely short folder."""
    d = tempfile.mkdtemp(prefix="gp")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _espeak_src(root, length):
    """A fake espeak-ng-data folder whose path is exactly `length` characters (like a translocated app)."""
    base = os.path.join(str(root), "app")
    src = os.path.join(base, "x" * max(1, length - len(base) - len("/espeak-ng-data") - 1), "espeak-ng-data")
    os.makedirs(src)
    open(os.path.join(src, "phontab"), "w").close()
    assert len(src) == length
    return src


def test_short_espeak_path_is_used_as_is(short_dir):
    src = _espeak_src(short_dir, len(short_dir) + 40)
    assert tts.espeak_data_dir(src, bases=[short_dir]) == src


def test_long_espeak_path_gets_a_short_link(tmp_path, short_dir):
    src = _espeak_src(tmp_path, 180)                      # App Translocation paths are ~165-180 characters
    got = tts.espeak_data_dir(src, bases=[short_dir])
    assert len(got) <= tts.ESPEAK_PATH_MAX
    assert os.path.realpath(got) == os.path.realpath(src)
    assert os.path.isfile(os.path.join(got, "phontab"))


def test_short_link_follows_the_app_when_it_moves(tmp_path, short_dir):
    old = _espeak_src(tmp_path / "old", 170)
    tts.espeak_data_dir(old, bases=[short_dir])
    new = _espeak_src(tmp_path / "new", 175)                # next launch: a new translocation folder
    got = tts.espeak_data_dir(new, bases=[short_dir])
    assert os.path.realpath(got) == os.path.realpath(new)


def test_unusable_short_bases_fall_back_to_the_original(tmp_path):
    src = _espeak_src(tmp_path, 180)
    assert tts.espeak_data_dir(src, bases=["/" + "y" * 200, os.path.join(os.sep, "no-such-dir-gp")]) == src


# ---------------------------------------------------------------- crash guard
def test_crash_guard_reruns_when_the_app_moves(monkeypatch):
    from glassprompter import __version__, app
    s = config.Settings()
    s.probe_version, s.probe_exe = __version__, "/private/var/folders/x/T/AppTranslocation/u/d/G.app/Contents/MacOS/G"
    monkeypatch.setattr(sys, "executable", "/Applications/Glass Prompter.app/Contents/MacOS/GlassPrompter")
    assert app.needs_probe(s)
    s.probe_exe = sys.executable
    assert not app.needs_probe(s)
    s.probe_version = "0.0.1"
    assert app.needs_probe(s)


def test_probe_exe_setting_validates():
    s = config.Settings()
    s.probe_exe = 5
    config.validate(s)
    assert s.probe_exe == "5"


# ---------------------------------------------------------------- ghost mode keeps its see-through look
@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_ghost_backdrop_stays_off_after_show_and_settings_change(qapp, monkeypatch):
    from glassprompter.ui.prompter import Prompter
    calls = []
    monkeypatch.setattr(native, "set_click_through", lambda w, on: True)
    monkeypatch.setattr(native, "apply_backdrop", lambda w, kind="acrylic": calls.append(kind) or "")
    p = Prompter(config.Settings())
    p.set_ghost(True)
    assert p.ghost and calls[-1] == "none"
    p.apply_backdrop()                                     # what showEvent runs after hide + show
    assert calls[-1] == "none"
    p.apply_settings()                                     # e.g. bigger text from the phone
    assert calls[-1] == "none"
    p.set_ghost(False)
    assert calls[-1] == "acrylic"
    p.close()


# ---------------------------------------------------------------- phone server port after a restart
@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps exclusive binding on purpose")
def test_phone_server_rebinds_its_port_right_after_a_restart():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    store = scripts.ScriptStore(paths.database_path())
    first = api.RemoteServer(store, None, "246810", port=port, bind="127.0.0.1")
    assert first.start()
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)  # the server closes it: TIME_WAIT on its port
    c.request("GET", "/api/v1/health", headers={"Host": "127.0.0.1:%d" % port})
    c.getresponse().read()
    c.close()
    first.stop()
    second = api.RemoteServer(store, None, "246810", port=port, bind="127.0.0.1")
    try:
        assert second.start(), second.error
    finally:
        second.stop()
        store.close()
