"""Smoke test: simulated rehearsal -> Rehearsal Coach report card (rendered to PNG); Read Aloud process."""
import os, shutil, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".smokecoach")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
os.environ["GLASSPROMPTER_HOME"] = os.path.join(OUT, "home")
from glassprompter import config
c = config.Config(); c.load(); c.s.remote_port = 8794; c.s.drop_dir = os.path.join(OUT, "drop"); c.s.first_run_done = True
c.save()
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from glassprompter import app as gapp
from glassprompter.tracking import norm_words
from glassprompter.ui import theme

LOG = open(os.path.join(OUT, "log.txt"), "w")
def L(*a): LOG.write(" ".join(str(x) for x in a) + "\n"); LOG.flush()
qa = QApplication([]); qa.setStyle("Fusion"); qa.setStyleSheet(theme.app_qss()); qa.setQuitOnLastWindowClosed(False)
class A: background = False; file = None
ctl = gapp.Controller(qa, A())
p = ctl.prompter
SCRIPT = ("# Opening\nGood morning everyone and thank you for joining. Today I want to walk you through our "
          "quarterly results.\n# Results\nRevenue grew eighteen percent and our customers are happier than ever.")
s = ctl.store.create("Board update", SCRIPT)
ctl.load_script(s["id"])
ctl.store.add_rehearsal(s["id"], {"seconds": 40, "wpm": 190, "filler_count": 6, "score": 64})   # an earlier run

def grab_report():
    from PySide6.QtWidgets import QApplication as QA
    w = QA.activeModalWidget()
    L("modal:", type(w).__name__)
    if w:
        w.grab().save(os.path.join(OUT, "report.png"))
        w.accept()

def run():
    p.cfg.voice_follow = True
    p.start_listening()
    ctl.voice.stop()                       # no real mic needed for this test
    p.voice_loading = False
    t0 = time.monotonic()
    p.coach.started -= 22                  # pretend 22 s have passed for a realistic pace
    phrases = ["good morning everyone um and thank you for joining", "uh today i want to walk you through",
               "like our quarterly results", "revenue grew eighteen percent", "you know our customers are happier than ever"]
    QTimer.singleShot(1500, grab_report)
    heard = []
    for ph in phrases:
        for w in norm_words(ph):
            heard.append(w); p.on_heard(heard)
        p.on_utterance(norm_words(ph)); heard = []
    L("coach fillers:", p.coach.fillers if p.coach else None, "cursor:", p.aligner.cursor, "/", len(p.vwords))
    QTimer.singleShot(1500, grab_report)
    # aligner reaching the end stops listening and fires the report automatically

def read_aloud():
    p.cfg.voice_follow = False
    p.toggle_read_aloud()
    QTimer.singleShot(2500, check_tts)

def check_tts():
    L("read aloud: speaking=%s playing=%s" % (ctl.speaker.speaking, p.playing))
    p.toggle_read_aloud()
    L("after stop: speaking=%s" % ctl.speaker.speaking)
    hist = ctl.store.rehearsals(s["id"])
    L("history scores:", [h["score"] for h in hist])
    L("DONE"); ctl.quit()

QTimer.singleShot(800, run)
QTimer.singleShot(5000, read_aloud)
qa.exec()
