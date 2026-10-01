"""Design tokens (role based) and Qt style sheets. Type scale: base 16, perfect fourth -> 12/16/21/28."""
from PySide6.QtGui import QColor, QFont, QFontDatabase


class T:
    surface = QColor(14, 14, 18)
    surface_2 = QColor(32, 32, 40)
    on_surface = QColor(255, 255, 255)
    muted = QColor(154, 154, 168)
    outline = QColor(255, 255, 255, 30)
    accent = QColor(255, 176, 32)
    on_accent = QColor(22, 18, 10)
    ok = QColor(61, 220, 132)
    bad = QColor(255, 90, 90)
    radius = 18
    caption, body, h2, h1 = 12, 16, 21, 28


_fonts = {}


def _pick(*families):
    available = set(QFontDatabase.families())
    for f in families:
        if f in available:
            return f
    return families[-1]


def fonts():
    """Resolve font families once (Windows 11 Variable fonts, falling back to Windows 10 ones)."""
    if not _fonts:
        _fonts["ui"] = _pick("Segoe UI Variable Text", "Segoe UI")
        _fonts["display"] = _pick("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI")
        _fonts["icon"] = _pick("Segoe Fluent Icons", "Segoe MDL2 Assets")
    return _fonts


def font(role, px, weight=QFont.Weight.Normal):
    f = QFont(fonts()[role])
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


ICON = dict(play=0xE768, pause=0xE769, edit=0xE70F, phone=0xE8EA, close=0xE8BB, minus=0xE738, plus=0xE710,
            font_down=0xE8E7, font_up=0xE8E8, help=0xE897, restart=0xE72C, settings=0xE713, library=0xE8F1, mic=0xE720)
ICON = {k: chr(v) for k, v in ICON.items()}
DOT, DASH, ELLIPSIS = chr(0xB7), chr(0x2014), chr(0x2026)


def bar_qss():
    f = fonts()
    return f"""
QFrame#bar {{ background: rgba(40,40,50,170); border: 1px solid rgba(255,255,255,38); border-radius: 11px; }}
QToolButton {{ color: #F4F4F7; background: transparent; border: 0; border-radius: 8px;
              min-width: 32px; min-height: 32px; font-family: "{f['icon']}"; font-size: 15px; }}
QToolButton:hover {{ background: rgba(255,255,255,24); }}
QToolButton:pressed {{ background: rgba(255,255,255,12); }}
QToolButton:focus {{ border: 2px solid #FFB020; }}
QToolButton#play {{ background: #FFB020; color: #16120A; }}
QToolButton#play:hover {{ background: #FFC04D; }}
QToolButton#voice[on="true"] {{ color: #FFB020; background: rgba(255,176,32,40); }}
QLabel#wpm {{ color: #C8C8D2; font-family: "{f['ui']}"; font-size: 12px; padding: 0 2px; min-width: 52px; }}
QFrame#sep {{ background: rgba(255,255,255,22); min-width: 1px; max-width: 1px; margin: 6px 3px; }}
"""


def app_qss():
    f = fonts()
    return f"""
QDialog {{ background: #141419; }}
QDialog[glass="true"] {{ background: transparent; }}
QLabel {{ color: #F4F4F7; font-family: "{f['ui']}"; font-size: 14px; }}
QLabel[role="title"] {{ font-family: "{f['display']}"; font-size: 21px; font-weight: 600; }}
QLabel[role="hero"] {{ font-family: "{f['display']}"; font-size: 28px; font-weight: 600; }}
QLabel[role="section"] {{ color: #FFB020; font-size: 12px; font-weight: 600; letter-spacing: 1px; }}
QLabel[role="muted"] {{ color: #9A9AA8; font-size: 12px; }}
QLabel[role="warn"] {{ color: #FFB020; font-size: 12px; }}
QLabel[role="pin"] {{ font-family: "{f['display']}"; font-size: 28px; font-weight: 600; letter-spacing: 6px; }}
QFrame[role="card"] {{ background: rgba(255,255,255,13); border: 1px solid rgba(255,255,255,24); border-radius: 12px; }}
QPlainTextEdit, QLineEdit, QSpinBox, QListWidget {{ background: rgba(255,255,255,14); color: #F4F4F7;
    border: 1px solid rgba(255,255,255,26);
    border-radius: 10px; padding: 8px 10px; font-family: "{f['ui']}"; font-size: 14px;
    selection-background-color: #FFB020; selection-color: #16120A; }}
QPlainTextEdit {{ font-size: 16px; padding: 12px; }}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QListWidget:focus {{ border: 1px solid #FFB020; }}
QListWidget {{ padding: 4px; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 8px; margin: 1px 0; color: #F4F4F7; }}
QListWidget::item:selected {{ background: rgba(255,255,255,30); color: #F4F4F7; }}
QListWidget::item:hover:!selected {{ background: rgba(255,255,255,14); }}
QPushButton {{ background: rgba(255,255,255,20); color: #F4F4F7; border: 1px solid rgba(255,255,255,30);
    border-radius: 7px; padding: 7px 16px; font-family: "{f['ui']}"; font-size: 14px; }}
QPushButton:hover {{ background: rgba(255,255,255,32); }}
QPushButton:pressed {{ background: rgba(255,255,255,12); }}
QPushButton:focus {{ border: 1px solid #FFB020; }}
QPushButton:disabled {{ color: #6A6A78; }}
QPushButton[primary="true"] {{ background: #FFB020; color: #16120A; border: 0; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #FFC04D; }}
QPushButton[primary="true"]:focus {{ border: 2px solid #F4F4F7; }}
QPushButton[danger="true"] {{ color: #FF5A5A; }}
QCheckBox {{ color: #F4F4F7; font-family: "{f['ui']}"; font-size: 14px; spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #4A4A58; background: #1B1B22; }}
QCheckBox::indicator:checked {{ background: #FFB020; border: 1px solid #FFB020; }}
QCheckBox:focus {{ color: #FFB020; }}
QSlider {{ min-height: 24px; background: transparent; }}
QSlider::groove:horizontal {{ border: 0; height: 24px; background: transparent; }}
QSlider::sub-page:horizontal {{ margin: 10px 0 10px 0; background: #FFB020; border-radius: 2px; }}
QSlider::add-page:horizontal {{ margin: 10px 0 10px 0; background: #2E2E3A; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #F4F4F7; width: 16px; margin: 4px 0; border-radius: 8px; }}
QSlider::handle:horizontal:focus {{ background: #FFB020; }}
QToolTip {{ background: #24242D; color: #F4F4F7; border: 1px solid #2E2E3A; padding: 4px 8px;
    font-family: "{f['ui']}"; font-size: 12px; }}
QMenu {{ background: #1B1B22; color: #F4F4F7; border: 1px solid #2E2E3A; border-radius: 8px; padding: 4px;
    font-family: "{f['ui']}"; font-size: 13px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: #2C2C37; }}
QMenu::item:disabled {{ color: #6A6A78; }}
QMenu::separator {{ height: 1px; background: #2E2E3A; margin: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #3A3A46; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMessageBox {{ background: #141419; }}
"""
