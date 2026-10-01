"""macOS-style glass toolkit: frosted backdrop, traffic-light buttons, toggle switches, glass dialogs."""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QDialog

from .. import win32
from .theme import T, font

RADIUS = 8                    # matches Windows 11's own rounded window corners
LIGHTS = [("close", QColor("#FF5F57")), ("mid", QColor("#FEBC2E")), ("max", QColor("#28C840"))]
L_R, L_GAP, L_X, L_Y = 6.0, 20.0, 16.0, 16.0


def light_rects():
    return [QRectF(L_X + i * L_GAP - L_R, L_Y - L_R, L_R * 2, L_R * 2) for i in range(3)]


def light_at(pt):
    for i, r in enumerate(light_rects()):
        if r.adjusted(-3, -3, 3, 3).contains(QPointF(pt)):
            return LIGHTS[i][0]
    return None


def paint_lights(p, hover_group, glyphs=("x", "-", "+")):
    """Traffic lights; symbols appear when the pointer is over the group, like macOS."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for i, (r, (_, col)) in enumerate(zip(light_rects(), LIGHTS)):
        p.setPen(QPen(col.darker(130), 0.8))
        p.setBrush(col)
        p.drawEllipse(r)
        if hover_group:
            p.setPen(QPen(QColor(0, 0, 0, 150), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            c, k = r.center(), 2.6
            g = glyphs[i]
            if g == "x":
                p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
                p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
            elif g == "-":
                p.drawLine(QPointF(c.x() - k - 0.5, c.y()), QPointF(c.x() + k + 0.5, c.y()))
            else:
                p.drawLine(QPointF(c.x() - k, c.y()), QPointF(c.x() + k, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - k), QPointF(c.x(), c.y() + k))
    p.restore()


def paint_glass(p, rect, tint_alpha, frosted, radius=RADIUS):
    """Tint + top sheen + hairline highlight - the 'vibrancy' look on top of the blurred backdrop."""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    base = QColor(18, 18, 24, tint_alpha if frosted else min(255, tint_alpha + 40))
    p.fillPath(path, base)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 22))
    sheen.setColorAt(0.35, QColor(255, 255, 255, 6))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.setPen(QPen(QColor(255, 255, 255, 34), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    return path


class Switch(QCheckBox):
    """iOS / macOS style toggle (keeps QCheckBox semantics, keyboard and accessibility)."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        self.toggled.connect(self._animate)
        self.setFont(font("ui", 14))

    def _tick(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0

    def sizeHint(self):
        fm = QFontMetricsF(self.font())
        return QSize(int(46 + 12 + fm.horizontalAdvance(self.text())), 28)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, (self.height() - 22) / 2, 40, 22)
        off, on = QColor(255, 255, 255, 46), T.accent
        col = QColor(int(off.red() + (on.red() - off.red()) * self._pos),
                     int(off.green() + (on.green() - off.green()) * self._pos),
                     int(off.blue() + (on.blue() - off.blue()) * self._pos),
                     int(off.alpha() + (255 - off.alpha()) * self._pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, 11, 11)
        knob = QRectF(track.x() + 2 + self._pos * 18, track.y() + 2, 18, 18)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(knob.translated(0, 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(knob)
        if self.hasFocus():
            p.setPen(QPen(T.accent, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), 13, 13)
        p.setPen(QColor("#F4F4F7"))
        p.setFont(self.font())
        p.drawText(QRectF(track.right() + 12, 0, self.width() - track.right() - 12, self.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text())


class GlassDialog(QDialog):
    """Frameless, frosted, rounded dialog with traffic lights and edge resizing."""

    def __init__(self, parent=None, resizable=False):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.frosted = win32.backdrop_supported()
        if self.frosted:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setProperty("glass", True)
        self.setMouseTracking(True)
        self.resizable = resizable
        self._lights_hover = False
        self._shifted = False

    def showEvent(self, e):
        if not self._shifted and self.layout():
            m = self.layout().contentsMargins()
            self.layout().setContentsMargins(m.left(), m.top() + 18, m.right(), m.bottom())
            self._shifted = True
        super().showEvent(e)
        hwnd = int(self.winId())
        if self.frosted:
            self.frosted = bool(win32.apply_backdrop(hwnd, "acrylic"))
        win32.set_capture_excluded(hwnd, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        paint_glass(p, r, 150 if self.frosted else 255, self.frosted)
        paint_lights(p, self._lights_hover, ("x", "-", "+"))

    def _edges(self, pt):
        if not self.resizable:
            return Qt.Edge(0)
        m, e = 6, Qt.Edge(0)
        if pt.x() <= m:
            e |= Qt.Edge.LeftEdge
        if pt.x() >= self.width() - m:
            e |= Qt.Edge.RightEdge
        if pt.y() <= m:
            e |= Qt.Edge.TopEdge
        if pt.y() >= self.height() - m:
            e |= Qt.Edge.BottomEdge
        return e

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        pt = ev.position().toPoint()
        hit = light_at(pt)
        if hit == "close":
            return self.reject()
        if hit == "mid":
            return self.showMinimized()
        if hit == "max":
            return self.showNormal() if self.isMaximized() else (self.showMaximized() if self.resizable else None)
        edges = self._edges(pt)
        if edges != Qt.Edge(0):
            self.windowHandle().startSystemResize(edges)
        elif pt.y() < 56:                       # the top band works like a title bar
            self.windowHandle().startSystemMove()

    def mouseMoveEvent(self, ev):
        pt = ev.position().toPoint()
        hover = light_at(pt) is not None or (QRectF(4, 4, 64, 26).contains(QPointF(pt)))
        if hover != self._lights_hover:
            self._lights_hover = hover
            self.update(0, 0, 80, 34)
        e = self._edges(pt)
        L, R, Tp, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | Tp, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif e in (R | Tp, L | B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e in (L, R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e in (Tp, B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def leaveEvent(self, ev):
        if self._lights_hover:
            self._lights_hover = False
            self.update(0, 0, 80, 34)
