"""Aurora Glass toolkit: frosted panel painting, toggle switches and frameless glass dialogs."""
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QCheckBox, QDialog, QPushButton

from .. import platform as native
from . import icons
from .theme import T, font

RADIUS = 14
HEADER = 40


def paint_glass(p, rect, tint_alpha, frosted, radius=RADIUS, phase=0.0, rim=0.5, glow=0.0):
    """Ink glass: tint, soft top sheen, 1px light edge, and a quiet accent rim that carries state.

    rim:   0..1 strength of the aqua->violet edge (idle ~0.3, active ~0.7, voice adds its level)
    phase: degrees; slides the rim gradient slowly while something is running
    glow:  0..1 faint accent light pooled under the bottom edge
    """
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    base = QColor(T.ink)
    base.setAlpha(tint_alpha if frosted else min(255, tint_alpha + 40))
    p.fillPath(path, base)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 14))
    sheen.setColorAt(0.22, QColor(255, 255, 255, 3))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    if glow > 0:
        g = QRadialGradient(QPointF(rect.center().x(), rect.bottom() + rect.height() * 0.35),
                            rect.width() * 0.42)
        a = QColor(T.violet)
        a.setAlpha(int(22 * glow))
        g.setColorAt(0.0, a)
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.save()
        p.setClipPath(path)
        p.fillRect(rect, g)
        p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)
    edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())          # light from above
    edge.setColorAt(0.0, QColor(255, 255, 255, 46))
    edge.setColorAt(0.5, QColor(255, 255, 255, 14))
    edge.setColorAt(1.0, QColor(255, 255, 255, 22))
    p.setPen(QPen(edge, 1))
    p.drawPath(path)
    if rim > 0:
        import math
        k = math.radians(phase)
        cx, cy, rw = rect.center().x(), rect.center().y(), rect.width() * 0.6
        acc = QLinearGradient(cx - rw * math.cos(k), cy - rw * math.sin(k) * 0.3,
                              cx + rw * math.cos(k), cy + rw * math.sin(k) * 0.3)
        a, v = QColor(T.aqua), QColor(T.violet)
        alpha = int(200 * max(0.0, min(1.0, rim)))
        a.setAlpha(alpha)
        v.setAlpha(alpha)
        mid = QColor(255, 255, 255, 0)
        acc.setColorAt(0.0, a)
        acc.setColorAt(0.5, mid)
        acc.setColorAt(1.0, v)
        p.setPen(QPen(acc, 1.2))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)
    return path


class Switch(QCheckBox):
    """Animated toggle (keeps QCheckBox semantics, keyboard and accessibility)."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=170, easingCurve=QEasingCurve.Type.OutCubic)
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
        if not self.text():
            return QSize(44, 26)
        fm = QFontMetricsF(self.font())
        return QSize(int(46 + 12 + fm.horizontalAdvance(self.text())), 28)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, (self.height() - 22) / 2, 40, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 34))
        p.drawRoundedRect(track, 11, 11)
        if self._pos > 0:
            on = QColor(T.aqua)
            on.setAlphaF(self._pos)
            p.setBrush(on)
            p.drawRoundedRect(track, 11, 11)
        knob = QRectF(track.x() + 2 + self._pos * 18, track.y() + 2, 18, 18)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(knob.translated(0, 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(knob)
        if self.hasFocus():
            p.setPen(QPen(T.aqua, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2.5, -2.5, 2.5, 2.5), 13, 13)
        p.setPen(T.on_surface)
        p.setFont(self.font())
        p.drawText(QRectF(track.right() + 12, 0, self.width() - track.right() - 12, self.height()),
                   Qt.AlignmentFlag.AlignVCenter, self.text())


class GlassDialog(QDialog):
    """Frameless frosted dialog: brand header, one close button, drag anywhere on the header, edge resize.
    Hidden from screen sharing so scripts and PINs stay private."""

    def __init__(self, parent=None, resizable=False, title=""):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.frosted = native.backdrop_supported()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setProperty("glass", True)
        self.setMouseTracking(True)
        self.resizable = resizable
        self.header_title = title
        self._shifted = False
        self.close_btn = QPushButton(self)
        self.close_btn.setObjectName("close")
        self.close_btn.setIcon(icons.icon("close", "#C9CFDD", 14))
        self.close_btn.setToolTip("Close  (Esc)")
        self.close_btn.setAccessibleName("Close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_btn.clicked.connect(self.reject)

    def showEvent(self, e):
        if not self._shifted and self.layout():
            m = self.layout().contentsMargins()
            self.layout().setContentsMargins(m.left(), m.top() + HEADER - 12, m.right(), m.bottom())
            self._shifted = True
            self.layout().activate()
            if not self.resizable:
                self.resize(self.width(), max(self.height(), self.layout().totalSizeHint().height()))
        super().showEvent(e)
        native.prepare_window(self)
        if self.frosted:
            self.frosted = bool(native.apply_backdrop(self, "acrylic"))
        native.set_capture_excluded(self, True)
        self._place_close()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_close()

    def _place_close(self):
        self.close_btn.move(self.width() - 24 - 12, 10)
        self.close_btn.raise_()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        paint_glass(p, r, 175 if self.frosted else 250, self.frosted, phase=0, rim=0.0, glow=0.0)
        icons.draw(p, "spark", QRectF(18, 15, 14, 14), T.aqua)
        p.setPen(T.on_surface)
        p.setFont(font("ui", 13, font_weight_semibold()))
        p.drawText(QRectF(40, 8, self.width() - 100, 28), Qt.AlignmentFlag.AlignVCenter, self.header_title)

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
        edges = self._edges(pt)
        if edges != Qt.Edge(0):
            self.windowHandle().startSystemResize(edges)
        elif pt.y() < HEADER + 8:                       # the header works like a title bar
            self.windowHandle().startSystemMove()

    def mouseMoveEvent(self, ev):
        e = self._edges(ev.position().toPoint())
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


def font_weight_semibold():
    from PySide6.QtGui import QFont
    return QFont.Weight.DemiBold
