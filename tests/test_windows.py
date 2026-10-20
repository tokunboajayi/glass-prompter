import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GLASSPROMPTER_ALLOW_CAPTURE", "1")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout  # noqa: E402

from glassprompter import config  # noqa: E402
from glassprompter.ui import glass  # noqa: E402


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def prefs(monkeypatch):
    s = config.Settings()
    saved = []
    monkeypatch.setattr(glass.GlassDialog, "prefs", s)
    monkeypatch.setattr(glass.GlassDialog, "save", lambda: saved.append(1))
    return s, saved


def _dialog(title, w=500, h=300, resizable=True):
    d = glass.GlassDialog(None, resizable=resizable, title=title)
    lay = QVBoxLayout(d)
    lay.addWidget(QLabel("hello"))
    d.resize(w, h)
    return d


def test_levels_cycle_solid_glass_clear():
    assert [n for _, n in glass.GLASS_LEVELS] == ["Solid", "Glass", "Clear"]
    assert glass._next_level(1.0) == 0.7 and glass._next_level(0.7) == 0.4 and glass._next_level(0.4) == 1.0


def test_a_too_tall_window_is_shrunk_and_kept_on_screen(qapp, prefs):
    d = _dialog("Tall", 600, 5000)
    d.show()
    area = glass.usable_rect(qapp.primaryScreen())
    g = d.frameGeometry()
    assert area.contains(g.topLeft()) and g.bottom() <= area.bottom() and g.height() < 5000
    d.close()


def test_position_and_size_are_remembered(qapp, prefs):
    s, saved = prefs
    d = _dialog("Remember me", 420, 260)
    d.show()
    d.move(60, 70)
    d.close()
    assert s.window_geometry["Remember me"][:2] == [60, 70] and saved
    d2 = _dialog("Remember me", 300, 200)
    d2.show()
    assert (d2.x(), d2.y(), d2.width(), d2.height()) == (60, 70, 420, 260)
    d2.close()


def test_see_through_level_applies_to_every_window_and_is_saved(qapp, prefs):
    s, saved = prefs
    a, b = _dialog("A"), _dialog("B")
    a.show()
    b.show()
    glass.GlassDialog.set_level(0.4)
    assert s.window_glass == 0.4 and saved
    assert a.effective_level() == 0.4 and b.effective_level() == 0.4
    s.glass_solid_hover = True
    a._hover = True                                       # mouse over it: solid while in use
    assert a.effective_level() == 1.0 and b.effective_level() == 0.4
    s.glass_solid_hover = False
    assert a.effective_level() == 0.4
    a.close()
    b.close()


def test_settings_validation_keeps_new_fields_sane():
    s = config.Settings(window_glass=9, window_geometry="junk", glass_solid_hover=0)
    config.validate(s)
    assert s.window_glass == 1.0 and s.window_geometry == {} and s.glass_solid_hover is False


def test_transcript_html_colours_speakers_and_escapes_text():
    from glassprompter import meeting
    from glassprompter.ui.copilot import transcript_html
    tr = meeting.Transcript(started=0.0)
    tr.add(meeting.THEM, "is <b>this</b> ok", at=5.0)
    tr.add(meeting.ME, "yes", at=12.0)
    html = transcript_html(tr)
    assert "#A48BFF" in html and "#40E8D0" in html and "Them" in html and "You" in html
    assert "&lt;b&gt;this&lt;/b&gt;" in html and "<b>this</b>" not in html
    assert html.index("Them") < html.index("You") and "0:05" in html
