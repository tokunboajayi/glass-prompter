"""Screenshot the glass UI (real compositor blur) - prompter, library, settings, welcome."""
import os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".glassshots")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
os.environ["GLASSPROMPTER_HOME"] = os.path.join(OUT, "home")
os.environ["GLASSPROMPTER_ALLOW_CAPTURE"] = "1"
from glassprompter import config
c = config.Config(); c.load(); c.s.remote_port = 8793; c.s.drop_dir = os.path.join(OUT, "drop")
c.s.first_run_done = True; c.s.geometry = [320, 6, 640, 216]; c.save()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from glassprompter import app as gapp
from glassprompter.ui import theme
from glassprompter.ui.dialogs import LibraryDialog, SettingsDialog, WelcomeDialog

def shot(n):
    subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "tools", "shot.ps1"),
                      "-out", os.path.join(OUT, n)], creationflags=0x08000000)

qa = QApplication([]); qa.setStyle("Fusion"); qa.setStyleSheet(theme.app_qss()); qa.setQuitOnLastWindowClosed(False)
class A: background = False; file = None
ctl = gapp.Controller(qa, A())
p = ctl.prompter
s = ctl.store.create("Investor pitch", "# Opening\nGood morning everyone and thank you for joining. Today I want to walk you "
                     "through our quarterly results and the plan for next year.\n[SMILE]\nRevenue grew eighteen percent.")
ctl.load_script(s["id"])
dialogs = []
def show(d, x, y):
    d.move(x, y); d.show(); dialogs.append(d)

def stage1():
    p.hovered = True; p.lights_hover = True; p.sync_ui(); p.update()
    QTimer.singleShot(900, lambda: shot("1_prompter.png"))
def stage2():
    show(LibraryDialog(None, ctl.store, s["id"], lambda sid: None), 260, 250)
    QTimer.singleShot(1200, lambda: shot("2_library.png"))
def stage3():
    for d in dialogs: d.close()
    show(SettingsDialog(None, ctl), 220, 200)
    QTimer.singleShot(1200, lambda: shot("3_settings.png"))
def stage4():
    for d in dialogs: d.close()
    show(WelcomeDialog(None, "x"), 380, 220)
    QTimer.singleShot(1200, lambda: shot("4_welcome.png"))
def done():
    for d in dialogs: d.close()
    print("frosted:", repr(p.frosted), "dialog frosted:", dialogs[-1].frosted)
    ctl.quit()
for t, fn in ((500, stage1), (2500, stage2), (5000, stage3), (7500, stage4), (10500, done)):
    QTimer.singleShot(t, fn)
qa.exec()
