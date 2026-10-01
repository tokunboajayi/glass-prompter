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
    muted = QColor(154, 163, 184)
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


def fonts():
    """Native UI fonts on each OS: Segoe UI Variable (Windows 11), SF Pro (macOS), Inter or system elsewhere."""
    if not _fonts:
        _fonts["ui"] = _pick("Segoe UI Variable Text", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue",
                             "Inter", "Segoe UI")
        _fonts["display"] = _pick("Segoe UI Variable Display", "SF Pro Display", ".AppleSystemUIFont",
                                  "Helvetica Neue", "Inter", "Segoe UI Semibold", "Segoe UI")
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
QFrame#bar {{ background: rgba(14,16,28,190); border: 1px solid rgba(255,255,255,34); border-radius: 14px; }}
QToolButton {{ color: #F5F7FF; background: transparent; border: 0; border-radius: 10px;
              min-width: 34px; min-height: 34px; }}
QToolButton:hover {{ background: rgba(255,255,255,22); }}
QToolButton:pressed {{ background: rgba(255,255,255,10); }}
QToolButton:focus {{ border: 1px solid {AQUA}; }}
QToolButton#play {{ background: {GRAD}; border-radius: 17px; }}
QToolButton#play:hover {{ background: {GRAD_HOVER}; }}
QToolButton[on="true"] {{ background: rgba(64,232,208,38); }}
QLabel#wpm {{ color: #C9D0E0; font-family: "{f['ui']}"; font-size: 12px; font-weight: 600; padding: 0 2px;
             min-width: 54px; }}
QFrame#sep {{ background: rgba(255,255,255,20); min-width: 1px; max-width: 1px; margin: 8px 3px; }}
"""


def app_qss():
    f = fonts()
    return f"""
QDialog {{ background: #0C0E18; }}
QDialog[glass="true"] {{ background: transparent; }}
QLabel {{ color: #F5F7FF; font-family: "{f['ui']}"; font-size: 14px; }}
QLabel[role="title"] {{ font-family: "{f['display']}"; font-size: 21px; font-weight: 600; }}
QLabel[role="hero"] {{ font-family: "{f['display']}"; font-size: 28px; font-weight: 700; }}
QLabel[role="section"] {{ color: {AQUA}; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }}
QLabel[role="muted"] {{ color: #9AA3B8; font-size: 12px; }}
QLabel[role="warn"] {{ color: {EMBER}; font-size: 12px; }}
QLabel[role="pin"] {{ font-family: "{f['display']}"; font-size: 28px; font-weight: 700; letter-spacing: 6px;
                      color: {AQUA}; }}
QLabel[role="dialogtitle"] {{ color: #C9D0E0; font-size: 12px; font-weight: 600; letter-spacing: 0.5px; }}
QFrame[role="card"] {{ background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,22); border-radius: 14px; }}
QPlainTextEdit, QLineEdit, QSpinBox, QListWidget, QComboBox {{ background: rgba(255,255,255,12); color: #F5F7FF;
    border: 1px solid rgba(255,255,255,24); border-radius: 10px; padding: 8px 10px; font-family: "{f['ui']}";
    font-size: 14px; selection-background-color: {AQUA}; selection-color: #070910; }}
QPlainTextEdit {{ font-size: 16px; padding: 12px; }}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QListWidget:focus, QComboBox:focus {{
    border: 1px solid {AQUA}; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox QAbstractItemView {{ background: #151826; color: #F5F7FF; border: 1px solid #2A2E44;
    selection-background-color: rgba(64,232,208,60); outline: 0; }}
QListWidget {{ padding: 4px; outline: 0; }}
QListWidget::item {{ border-radius: 10px; padding: 8px; margin: 1px 0; color: #F5F7FF; }}
QListWidget::item:selected {{ background: rgba(64,232,208,34); color: #F5F7FF; }}
QListWidget::item:hover:!selected {{ background: rgba(255,255,255,12); }}
QPushButton {{ background: rgba(255,255,255,16); color: #F5F7FF; border: 1px solid rgba(255,255,255,28);
    border-radius: 10px; padding: 8px 16px; font-family: "{f['ui']}"; font-size: 14px; }}
QPushButton:hover {{ background: rgba(255,255,255,28); }}
QPushButton:pressed {{ background: rgba(255,255,255,10); }}
QPushButton:focus {{ border: 1px solid {AQUA}; }}
QPushButton:disabled {{ color: #5E6478; }}
QPushButton[primary="true"] {{ background: {GRAD}; color: #070910; border: 0; font-weight: 700; }}
QPushButton[primary="true"]:hover {{ background: {GRAD_HOVER}; }}
QPushButton[primary="true"]:focus {{ border: 1px solid #F5F7FF; }}
QPushButton[danger="true"] {{ color: #FF5C7A; }}
QPushButton[compact="true"] {{ padding: 6px 10px; font-size: 13px; }}
QPushButton#close {{ background: transparent; border: 0; border-radius: 14px; padding: 0; min-width: 28px;
    min-height: 28px; max-width: 28px; max-height: 28px; }}
QPushButton#close:hover {{ background: rgba(255,92,122,200); }}
QCheckBox {{ color: #F5F7FF; font-family: "{f['ui']}"; font-size: 14px; spacing: 10px; }}
QSlider {{ min-height: 24px; background: transparent; }}
QSlider::groove:horizontal {{ border: 0; height: 24px; background: transparent; }}
QSlider::sub-page:horizontal {{ margin: 10px 0 10px 0; background: {GRAD}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ margin: 10px 0 10px 0; background: #262A3E; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #F5F7FF; width: 16px; margin: 4px 0; border-radius: 8px; }}
QSlider::handle:horizontal:focus {{ background: {AQUA}; }}
QToolTip {{ background: #151826; color: #F5F7FF; border: 1px solid #2A2E44; padding: 5px 9px;
    font-family: "{f['ui']}"; font-size: 12px; }}
QMenu {{ background: #121522; color: #F5F7FF; border: 1px solid #2A2E44; border-radius: 10px; padding: 5px;
    font-family: "{f['ui']}"; font-size: 13px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 7px; }}
QMenu::item:selected {{ background: rgba(64,232,208,40); }}
QMenu::item:disabled {{ color: #5E6478; }}
QMenu::separator {{ height: 1px; background: #2A2E44; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #343A54; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMessageBox {{ background: #0C0E18; }}
"""
