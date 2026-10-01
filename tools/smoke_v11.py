"""Smoke test for 1.1 features: Voice Follow (real mic open + simulated speech), ghost mode, sections, mirror."""
import ctypes, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".smoke11")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
os.environ["GLASSPROMPTER_HOME"] = os.path.join(OUT, "home")
os.environ["GLASSPROMPTER_ALLOW_CAPTURE"] = "1"
from glassprompter import config, win32
c = config.Config(); c.load(); c.s.remote_port = 8792; c.s.drop_dir = os.path.join(OUT, "drop")
c.s.first_run_done = True; c.s.geometry = []; c.save()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from glassprompter import app as gapp
from glassprompter.tracking import norm_words
from glassprompter.ui import theme

LOG = open(os.path.join(OUT, "log.txt"), "w")
def L(*a): LOG.write(" ".join(str(x) for x in a) + "\n"); LOG.flush()
def shot(n): (p.grab().save(os.path.join(OUT, n)), L("geom", p.geometry(), "visible", p.isVisible(), "excluded", win32.is_capture_excluded(p.hwnd())))
def _old_shot(n): subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "tools", "shot.ps1"),
                             "-out", os.path.join(OUT, n)], creationflags=0x08000000)

SCRIPT = """# Opening
Good morning everyone and thank you for joining. Today I want to walk you through our quarterly results.
[PAUSE]
# Results
Revenue grew eighteen percent year over year and our customers are happier than ever before.
# Next steps
Next year we will double down on the products our customers love the most."""

qa = QApplication([]); qa.setStyle("Fusion"); qa.setStyleSheet(theme.app_qss()); qa.setQuitOnLastWindowClosed(False)
class A: background = False; file = None
ctl = gapp.Controller(qa, A())
p = ctl.prompter
s = ctl.store.create("Board update", SCRIPT)
ctl.load_script(s["id"])
steps = []
def step(d):
    def deco(fn): steps.append((d, fn)); return fn
    return deco

@step(800)
def a():
    L("hotkeys", sum(ctl.hotkeys_ok), "/", len(gapp.HOTKEYS), "| sections:", [t for _, t in __import__("glassprompter").engine.sections(p.lines)])
    L("voice available:", ctl.voice.available(), "words:", len(p.vwords))
    p.toggle_voice()
    p.toggle_play()           # start listening -> opens the real microphone

@step(3500)
def b():
    L("after start: listening=%s loading=%s engine.listening=%s level=%.2f" % (p.listening, p.voice_loading, ctl.voice.listening, p.mic_level))
    # simulate speech arriving from the recognizer
    heard = []
    for w in norm_words("good morning everyone and thank you for joining today i want to walk you through"):
        heard.append(w); p.on_heard(heard)
    L("cursor word:", p.vwords[p.aligner.cursor], "line:", p.vline[p.aligner.cursor], "target:", round(p.v_target))

@step(1200)
def c_():
    shot("1_voice_midline.png")
    heard = []
    for w in norm_words("revenue grew eighteen percent year over year"):
        heard.append(w); p.on_heard(heard)
    L("after jump ahead cursor:", p.vwords[p.aligner.cursor])

@step(1200)
def d():
    shot("2_voice_results.png")
    p.stop_listening()
    L("stopped: listening=%s" % p.listening)
    hw = p.hwnd()
    p.set_ghost(True)
    st = ctypes.windll.user32.GetWindowLongW(hw, -20)
    L("ghost on: flag=%s exstyle_transparent=%s hwnd_same=%s" % (p.ghost, bool(st & 0x20), hw == p.hwnd()))

@step(800)
def e():
    shot("3_ghost.png")
    p.set_ghost(False)
    L("ghost off: transparent=%s" % bool(ctypes.windll.user32.GetWindowLongW(p.hwnd(), -20) & 0x20))
    p.restart(); p.jump_section(1)
    L("section jump ->", p.lines[__import__("glassprompter").engine.line_index(p.pos, p.lh)].text)
    p.cfg.mirror = True; p.update()

@step(700)
def f():
    shot("4_mirror.png")
    p.cfg.mirror = False
    p.cfg.voice_follow = False
    L("snapshot keys ok:", all(k in p.snapshot() for k in ("voice_follow", "listening", "sections", "ghost")))
    L("DONE"); ctl.quit()

def run(i=0):
    if i >= len(steps): return
    dly, fn = steps[i]
    def go():
        try: fn()
        except Exception:
            import traceback; L("ERR", fn.__name__, traceback.format_exc())
        run(i + 1)
    QTimer.singleShot(dly, go)
run()
qa.exec()

