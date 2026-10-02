"""Render every screen to PNG (any OS, works headless with QT_QPA_PLATFORM=offscreen).

    python tools/shots.py out_dir
"""
import os
import sys
import faulthandler
import tempfile

if os.environ.get("GP_SHOTS_DEBUG"):
    faulthandler.dump_traceback_later(15, exit=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("GLASSPROMPTER_HOME", tempfile.mkdtemp(prefix="gp_shots_"))
os.environ["GLASSPROMPTER_ALLOW_CAPTURE"] = "1"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from glassprompter import app as gpapp  # noqa: E402
from glassprompter.ui import dialogs, theme  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "shots")
os.makedirs(out, exist_ok=True)

DEMO = """# Opening
Good morning everyone, and thanks for joining the quarterly review.
Today I want to walk you through three wins, one miss, and what we do next.
[SMILE]
# The numbers
Revenue grew eighteen percent, and churn fell for the third quarter in a row.
[PAUSE]
"""

app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
app.setStyleSheet(theme.app_qss())


class Args:
    background = True
    file = None


from glassprompter import config  # noqa: E402
_c = config.Config()
_c.load()
_c.s.first_run_done = True             # no welcome dialog popping up modally mid-capture
_c.save()
ctl = gpapp.Controller(app, Args())
p = ctl.prompter
p.resize(980, 300)
p.set_script(DEMO, 0, "Quarterly review")


def grab(w, name):
    w.grab().save(os.path.join(out, name))
    print("saved", name)


def run():
    p.show()
    if os.environ.get("GP_SHOTS_PRIVATE"):          # marketing renders: show the real Windows/Mac "Private" state
        app.processEvents()                          # let the queued apply_capture() run first, then override
        p.guard = p.apply_capture = lambda *a: None
        p.cap_level, p.cap_state = "full", True
    p.hovered = True
    p.sync_ui()
    app.processEvents()
    grab(p, "1_prompter.png")
    # voice follow mid-script
    p.cfg.voice_follow = True
    p.listening, p.voice_loading, p.mic_level, p.live_wpm, p.voice_latency = True, False, 0.7, 148, 64
    p.aligner.cursor = 18
    p.pos = p.v_target = __import__("glassprompter.engine", fromlist=["x"]).voice_target(p.vline, 18) * p.lh
    p.hovered = False
    p.sync_ui()
    p.bar.fade(False, instant=True)
    app.processEvents()
    grab(p, "2_voice.png")
    p.listening = False
    p.ghost, p.cfg.ghost_opacity, p.frosted = True, 0.35, ""
    p.update()
    app.processEvents()
    grab(p, "2b_ghost.png")
    p.ghost = False
    p.cfg.voice_follow = False
    p.counting, p.count_t0 = True, p.now() - 0.25
    app.processEvents()
    grab(p, "3_countdown.png")
    p.counting = False
    p.show_help = True
    p.update()
    app.processEvents()
    grab(p, "4_help.png")
    p.show_help = False
    p.hovered = True
    p.sync_ui()
    app.processEvents()
    m = p.bar.menu
    m.popup_under(p.bar.more, True)
    m.hover = 2
    app.processEvents()
    grab(m, "4b_menu.png")
    m.close()
    from glassprompter.ui.glass import GlassTip
    tip = GlassTip.get()
    tip.request(p.bar.voice, "Voice Follow", "V")
    tip._show_now()
    app.processEvents()
    grab(tip, "4c_tip.png")
    tip.cancel()
    for cls, args, name, size in [
        (dialogs.SettingsDialog, (None, ctl), "5_settings.png", None),
        (dialogs.LibraryDialog, (None, ctl.store, 0, lambda s: None), "6_library.png", (940, 600)),
        (dialogs.WelcomeDialog, (None, ctl.cfg.s.drop_dir), "7_welcome.png", None),
        (dialogs.PhoneDialog, (None, ctl), "8_phone.png", None),
        (dialogs.ReportDialog, (None, {"score": 88, "wpm": 146, "seconds": 74, "fillers": {"um": 2, "like": 1},
                                       "filler_count": 3, "long_pauses": 1, "longest_pause": 3.4, "skipped": 4,
                                       "coverage": 0.96, "tip": "Great pace. Cut the two 'um's in the opener.",
                                       "title": "Quarterly review", "trend": 6},
                                [{"score": s} for s in (88, 82, 75, 70)]), "9_report.png", None),
    ]:
        d = cls(*args)
        if size:
            d.resize(*size)
        d.show()
        app.processEvents()
        grab(d, name)
        d.close()
    ctl.quit()


QTimer.singleShot(300, run)
app.exec()
