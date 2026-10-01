"""Aurora Glass design tokens and Qt style sheets.

Identity: deep-ink frosted glass with a living aurora rim (aqua -> violet -> ember) that reflects state:
calm when idle, flowing while you read, pulsing with your voice while Voice Follow listens.
Type scale: base 16, perfect fourth -> 12/16/21/28. Same look on Windows and macOS.
"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QConicalGradient, QFont, QFontDatabase, QLinearGradient


class T:
    ink = QColor(9, 11, 20)
    surface = QColor(12, 14, 24)
    surface_2 = QColor(26, 29, 44)
    on_surface = QColor(245, 247, 255)
    muted = QColor(160, 168, 188)
    outline = QColor(255, 255, 255, 30)
    aqua = QColor(64, 232, 208)
    violet = QColor(139, 108, 255)
    ember = QColor(255, 166, 77)
    accent = aqua                   # reading band, focus, "active"
    cue = ember                     # [CUES] and [PAUSE]
    section = violet                # # Headings
    on_accent = QColor(7, 9, 16)
    ok = QColor(61, 220, 151)
    warn = ember
    bad = QColor(255, 92, 122)
    radius = 16
    caption, body, h2, h1 = 12, 16, 21, 28


AQUA, VIOLET, EMBER = "#40E8D0", "#8B6CFF", "#FFA64D"
GRAD = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %s, stop:1 %s)" % (AQUA, VIOLET)
GRAD_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6FF0DD, stop:1 #A48BFF)"


def aurora(center, phase=0.0, alpha=255):
    """Conical aurora gradient; `phase` (degrees) rotates it."""
    g = QConicalGradient(QPointF(center), phase)
    stops = [(0.0, T.aqua), (0.33, T.violet), (0.62, T.ember), (0.82, T.violet), (1.0, T.aqua)]
    for pos, c in stops:
        c = QColor(c)
        c.setAlpha(alpha)
        g.setColorAt(pos, c)
    return g


def aurora_line(x0, x1, y=0.0, alpha=255):
    g = QLinearGradient(x0, y, x1, y)
    a, v = QColor(T.aqua), QColor(T.violet)
    a.setAlpha(alpha)
    v.setAlpha(alpha)
    g.setColorAt(0.0, a)
    g.setColorAt(1.0, v)
    return g


_fonts = {}


def _pick(*families):
    available = set(QFontDatabase.families())
    for f in families:
        if f in available:
            return f
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()


def _load_bundled():
    """Inter (SIL OFL) ships with the app so type looks identical and premium on Windows and macOS."""
    import os
    from .. import paths
    fams = []
    d = os.path.join(paths.package_dir(), "fonts")
    for f in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        fid = QFontDatabase.addApplicationFont(os.path.join(d, f))
        if fid >= 0:
            fams += QFontDatabase.applicationFontFamilies(fid)
    return fams


def fonts():
    """Inter everywhere (bundled), falling back to each OS's own UI font."""
    if not _fonts:
        inter = _load_bundled()
        first = inter[:1]
        _fonts["ui"] = _pick(*(first + ["Segoe UI Variable Text", "SF Pro Text", ".AppleSystemUIFont", "Segoe UI"]))
        _fonts["display"] = _pick(*(first + ["Segoe UI Variable Display", "SF Pro Display", ".AppleSystemUIFont",
                                             "Segoe UI"]))
    return _fonts


def font(role, px, weight=QFont.Weight.Normal):
    f = QFont(fonts()[role])
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


DOT, DASH, ELLIPSIS = chr(0xB7), chr(0x2014), chr(0x2026)


def bar_qss():
    f = fonts()
    return f"""
QFrame#bar {{ background: rgba(16,18,30,214); border: 1px solid rgba(255,255,255,22); border-radius: 12px; }}
QToolButton {{ background: transparent; border: 0; border-radius: 9px; min-width: 32px; min-height: 32px;
              max-width: 32px; max-height: 32px; }}
QToolButton:hover {{ background: rgba(255,255,255,18); }}
QToolButton:pressed {{ background: rgba(255,255,255,8); }}
QToolButton:focus {{ border: 1px solid {AQUA}; }}
QToolButton#play {{ background: #F5F7FF; border-radius: 16px; }}
QToolButton#play:hover {{ background: #FFFFFF; }}
QToolButton[on="true"] {{ background: rgba(64,232,208,30); }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QLabel#wpm {{ color: #F5F7FF; font-family: "{f['ui']}"; font-size: 12px; padding: 0 2px; min-width: 58px; }}
QFrame#sep {{ background: rgba(255,255,255,16); min-width: 1px; max-width: 1px; margin: 9px 4px; }}
"""


def app_qss():
    f = fonts()
    return f"""
QDialog {{ background: #0C0E18; }}
QDialog[glass="true"] {{ background: transparent; }}
QLabel {{ color: #F2F4FA; font-family: "{f['ui']}"; font-size: 13px; }}
QLabel[role="title"] {{ font-family: "{f['display']}"; font-size: 20px; font-weight: 600; }}
QLabel[role="hero"] {{ font-family: "{f['display']}"; font-size: 26px; font-weight: 700; }}
QLabel[role="section"] {{ color: #8C95AB; font-size: 11px; font-weight: 600; }}
QLabel[role="muted"] {{ color: #A0A8BC; font-size: 12px; }}
QLabel[role="warn"] {{ color: {EMBER}; font-size: 12px; }}
QLabel[role="pin"] {{ font-family: "{f['display']}"; font-size: 28px; font-weight: 700; color: #F5F7FF; }}
QLabel[role="rowtitle"] {{ font-size: 13px; color: #F2F4FA; }}
QLabel[role="value"] {{ color: #A0A8BC; font-size: 12px; }}
QFrame[role="card"] {{ background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,16); border-radius: 12px; }}
QFrame[role="hairline"] {{ background: rgba(255,255,255,12); min-height: 1px; max-height: 1px; border: 0; }}
QPlainTextEdit, QLineEdit, QSpinBox, QListWidget, QComboBox {{ background: rgba(255,255,255,8); color: #F2F4FA;
    border: 1px solid rgba(255,255,255,18); border-radius: 9px; padding: 7px 10px; font-family: "{f['ui']}";
    font-size: 13px; selection-background-color: rgba(64,232,208,90); selection-color: #FFFFFF; }}
QPlainTextEdit {{ font-size: 15px; padding: 14px; }}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QListWidget:focus, QComboBox:focus {{
    border: 1px solid rgba(64,232,208,160); }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: #151826; color: #F2F4FA; border: 1px solid #262A3E; padding: 4px;
    selection-background-color: rgba(64,232,208,46); outline: 0; }}
QListWidget {{ padding: 4px; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 8px 10px; margin: 1px 0; color: #F2F4FA; }}
QListWidget::item:selected {{ background: rgba(255,255,255,20); color: #FFFFFF; }}
QListWidget::item:hover:!selected {{ background: rgba(255,255,255,9); }}
QPushButton {{ background: rgba(255,255,255,12); color: #F2F4FA; border: 1px solid rgba(255,255,255,18);
    border-radius: 9px; padding: 7px 14px; min-height: 18px; font-family: "{f['ui']}"; font-size: 13px; }}
QPushButton:hover {{ background: rgba(255,255,255,22); }}
QPushButton:pressed {{ background: rgba(255,255,255,8); }}
QPushButton:focus {{ border: 1px solid rgba(64,232,208,160); }}
QPushButton:disabled {{ color: #5E6478; }}
QPushButton[primary="true"] {{ background: #F5F7FF; color: #0A0C14; border: 1px solid #F5F7FF; font-weight: 600; padding: 7px 16px; }}
QPushButton[primary="true"]:hover {{ background: #FFFFFF; }}
QPushButton[primary="true"]:focus {{ border: 1px solid rgba(64,232,208,220); }}
QPushButton[danger="true"] {{ color: #FF6B88; }}
QPushButton[compact="true"] {{ padding: 5px 10px; font-size: 12px; }}
QPushButton#close {{ background: transparent; border: 0; border-radius: 12px; padding: 0; min-width: 24px;
    min-height: 24px; max-width: 24px; max-height: 24px; }}
QPushButton#close:hover {{ background: rgba(255,255,255,26); }}
QCheckBox {{ color: #F2F4FA; font-family: "{f['ui']}"; font-size: 13px; spacing: 10px; }}
QSlider {{ min-height: 22px; background: transparent; }}
QSlider::groove:horizontal {{ border: 0; height: 22px; background: transparent; }}
QSlider::sub-page:horizontal {{ margin: 9px 0 9px 0; background: {AQUA}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ margin: 9px 0 9px 0; background: rgba(255,255,255,30); border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #FFFFFF; width: 16px; margin: 3px 0; border-radius: 8px; }}
QToolTip {{ background: #151826; color: #F2F4FA; border: 1px solid #262A3E; padding: 5px 8px;
    font-family: "{f['ui']}"; font-size: 12px; }}
QMenu {{ background: #13162A; color: #F2F4FA; border: 1px solid #262A3E; border-radius: 10px; padding: 5px;
    font-family: "{f['ui']}"; font-size: 13px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(255,255,255,16); }}
QMenu::item:disabled {{ color: #5E6478; }}
QMenu::separator {{ height: 1px; background: #262A3E; margin: 4px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,40); border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMessageBox {{ background: #0C0E18; }}
"""
