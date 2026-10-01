"""UI smoke test: boots the real controller against a throwaway data folder, drives it,
and takes screenshots. Usage: python tools/smoke.py <outdir> [--visible]"""
import ctypes
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.abspath(sys.argv[1])
VISIBLE = "--visible" in sys.argv          # disable capture-exclusion so screenshots can see windows
os.makedirs(OUT, exist_ok=True)
HOME = os.path.join(OUT, "home")
shutil.rmtree(HOME, ignore_errors=True)
os.environ["GLASSPROMPTER_HOME"] = HOME
DROP = os.path.join(OUT, "drop")
shutil.rmtree(DROP, ignore_errors=True)

from glassprompter import config, win32  # noqa: E402

if VISIBLE:
    os.environ["GLASSPROMPTER_ALLOW_CAPTURE"] = "1"
# start from a known config: drop folder in OUT, test port
cfg = config.Config()
cfg.load()
cfg.s.drop_dir = DROP
cfg.s.remote_port = 8790
cfg.s.pin = "112233"
cfg.save()

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from glassprompter import app as gapp, log as logsetup  # noqa: E402
from glassprompter.ui import theme, icon  # noqa: E402

LOG = open(os.path.join(OUT, "smoke.log"), "w")


def L(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def shot(name):
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "tools", "shot.ps1"),
                    "-out", os.path.join(OUT, name)], creationflags=0x08000000)


def http_req(method, path, body=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", 8790, timeout=5)
    h = {"Host": "127.0.0.1"}
    if body is not None:
        body = json.dumps(body)
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = "Bearer " + token
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    d = r.read()
    c.close()
    return r.status, (json.loads(d) if d else {})


logsetup.setup()
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
qapp = QApplication(sys.argv[:1])
qapp.setStyle("Fusion")
qapp.setStyleSheet(theme.app_qss())
qapp.setQuitOnLastWindowClosed(False)
qapp.setWindowIcon(icon.app_icon())


class Args:
    background = False
    file = None


ctl = gapp.Controller(qapp, Args())
p = ctl.prompter
steps = []


def step(delay):
    def deco(fn):
        steps.append((delay, fn))
        return fn
    return deco


def close_modal():
    w = QApplication.activeModalWidget()
    if w:
        w.accept()


@step(900)
def s_welcome():
    L("welcome modal:", type(QApplication.activeModalWidget()).__name__)
    shot("01_welcome.png")
    close_modal()


@step(600)
def s_basics():
    L("hotkeys registered:", sum(ctl.hotkeys_ok), "/", len(gapp.HOTKEYS))
    L("server running:", ctl.server.running, "tray:", ctl.tray.isVisible())
    L("script:", p.script_title, "lines:", len(p.lines))
    L("drop readme:", os.path.exists(os.path.join(DROP, "_How this folder works.txt")))
    p.hovered = True
    p.sync_ui()


@step(500)
def s_paused():
    shot("02_paused.png")
    p.hovered = False
    # simulate the global hotkey Ctrl+Alt+Space (WM_HOTKEY id 1)
    ctypes.windll.user32.PostMessageW(p.hwnd(), win32.WM_HOTKEY, 1, 0)


@step(500)
def s_hotkey():
    L("after WM_HOTKEY play: counting=%s playing=%s" % (p.counting, p.playing))
    L("frame timer active while playing:", p.frame_timer.isActive())


@step(3200)
def s_playing():
    shot("03_playing.png")
    L("playing:", p.playing, "pos:", round(p.pos))
    # remote API end to end
    st, d = http_req("POST", "/api/v1/session", {"pin": "112233"})
    tok = d.get("token")
    L("session:", st)
    st, s = http_req("POST", "/api/v1/scripts", {"title": "From phone", "body": "Phone script line one.\n\nLine two."},
                     tok)
    L("create:", st, s.get("id"))
    st, _ = http_req("POST", "/api/v1/scripts/%d/load" % s["id"], None, tok)
    L("load while playing:", st)
    ctl._smoke = (tok, s["id"])


@step(600)
def s_queued():
    L("pending queued while playing:", p.pending is not None)
    st, state = http_req("GET", "/api/v1/state", None, ctl._smoke[0])
    L("state.queued:", state.get("queued"), "state.playing:", state.get("playing"))
    shot("04_queued.png")
    p.toggle_play()          # pause -> loads the pending script


@step(600)
def s_loaded():
    L("after pause loaded:", p.script_title, "current id ok:", ctl.cfg.s.current_script_id == ctl._smoke[1])
    # drop-folder import
    with open(os.path.join(DROP, "keynote.txt"), "w", encoding="utf-8") as f:
        f.write("Dropped via OneDrive.\n[PAUSE]\nEnd.")


@step(3800)
def s_drop():
    L("after drop:", p.script_title)
    p.toggle_help()


@step(500)
def s_help():
    shot("05_help.png")
    p.toggle_help()
    p.cfg.clear_mode = True
    p.update()


@step(500)
def s_clear():
    shot("06_clear.png")
    p.cfg.clear_mode = False
    p.update()
    QTimer.singleShot(1200, lambda: (shot("07_library.png"), close_modal()))
    ctl.open_library()


@step(400)
def s_settings():
    QTimer.singleShot(1000, lambda: (shot("08_settings.png"), close_modal()))
    ctl.open_settings()


@step(400)
def s_phone():
    QTimer.singleShot(2500, lambda: (shot("09_phone.png"), close_modal()))
    ctl.open_phone()


@step(400)
def s_about():
    QTimer.singleShot(800, lambda: (shot("10_about.png"), close_modal()))
    ctl.open_about()


@step(400)
def s_tray():
    ctl.tray_menu.popup(ctl.tray.geometry().center() if not ctl.tray.geometry().isEmpty() else p.geometry().center())
    QTimer.singleShot(700, lambda: (shot("11_tray.png"), ctl.tray_menu.hide()))


@step(1200)
def s_capture():
    L("capture state flag:", p.cap_state)
    L("library count:", ctl.store.count())
    L("DONE")
    ctl.quit()


def run(i=0):
    if i >= len(steps):
        return
    d, fn = steps[i]

    def go():
        try:
            fn()
        except Exception:
            import traceback
            L("ERR in", fn.__name__, traceback.format_exc())
        run(i + 1)
    QTimer.singleShot(d, go)


run()
qapp.exec()
