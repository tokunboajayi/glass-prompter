"""Try Windows 11 backdrop options on a frameless translucent Qt window; screenshot each."""
import ctypes, os, subprocess, sys
from ctypes import wintypes
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont
from PySide6.QtWidgets import QApplication, QWidget

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".glasslab"); os.makedirs(OUT, exist_ok=True)
dwm = ctypes.windll.dwmapi
user32 = ctypes.windll.user32


class MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def dwm_set(hwnd, attr, val):
    v = ctypes.c_int(val)
    return dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))


class ACCENT(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]


class WCAD(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


def accent_acrylic(hwnd, abgr):
    a = ACCENT(4, 2, abgr, 0)               # ACCENT_ENABLE_ACRYLICBLURBEHIND
    d = WCAD(19, ctypes.cast(ctypes.pointer(a), ctypes.c_void_p), ctypes.sizeof(a))
    return user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(d))


class W(QWidget):
    def __init__(self, label, tint):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.label, self.tint = label, tint
        self.setGeometry(330, 40, 640, 200)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath(); path.addRoundedRect(r, 8, 8)
        p.fillPath(path, QColor(18, 18, 24, self.tint))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1)); p.drawPath(path)
        f = QFont("Segoe UI Variable Display"); f.setPixelSize(34); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f); p.setPen(QColor("white"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.label)


app = QApplication([])
results = []
modes = ["dwm_acrylic", "dwm_mica", "accent_acrylic", "plain"]


def run(i=0):
    if i >= len(modes):
        print("\n".join(results)); app.quit(); return
    m = modes[i]
    w = W("Glass test: " + m, 70 if m != "plain" else 200)
    w.show(); hwnd = int(w.winId())
    ok = None
    if m.startswith("dwm"):
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(MARGINS(-1, -1, -1, -1)))
        dwm_set(hwnd, 20, 1)                      # dark mode
        dwm_set(hwnd, 33, 2)                      # rounded corners
        ok = dwm_set(hwnd, 38, 3 if m == "dwm_acrylic" else 2)
    elif m == "accent_acrylic":
        ok = accent_acrylic(hwnd, 0x40181812)
    results.append("%s -> %s" % (m, ok))

    def snap():
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "tools", "shot.ps1"),
                        "-out", os.path.join(OUT, m + ".png")], creationflags=0x08000000)
        w.close(); w.deleteLater()
        QTimer.singleShot(300, lambda: run(i + 1))
    QTimer.singleShot(1200, snap)


QTimer.singleShot(200, run)
app.exec()
