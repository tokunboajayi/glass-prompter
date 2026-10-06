"""Aurora Glass toolkit: frosted panel painting, toggle switches and frameless glass dialogs."""
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)
from PySide6.QtWidgets import QCheckBox, QDialog, QPushButton, QWidget

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
        native.prepare_window(self, above_prompter=True)
        # Qt can re-apply its own window level right after showing; re-assert ours once it has settled (macOS)
        QTimer.singleShot(0, self, lambda: native.prepare_window(self, above_prompter=True))
        QTimer.singleShot(120, self, lambda: self.isVisible() and native.prepare_window(self, above_prompter=True))
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
        if edges == Qt.Edge(0) and pt.y() >= HEADER + 8:
            return                                       # only the header works like a title bar
        wh, ok = self.windowHandle(), False
        if native.OS != "macos" and wh is not None:      # macOS: drag by hand (system move is a no-op there)
            ok = wh.startSystemResize(edges) if edges != Qt.Edge(0) else wh.startSystemMove()
        if not ok:
            self._drag = (edges, ev.globalPosition().toPoint(), self.geometry())

    def mouseReleaseEvent(self, ev):
        self._drag = None
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev):
        drag = getattr(self, "_drag", None)
        if drag and ev.buttons() & Qt.MouseButton.LeftButton:
            edges, start, g0 = drag
            d = ev.globalPosition().toPoint() - start
            if edges == Qt.Edge(0):
                self.move(g0.topLeft() + d)
            else:
                from PySide6.QtCore import QRect
                g = QRect(g0)
                mw, mh = self.minimumSizeHint().width(), self.minimumSizeHint().height()
                if edges & Qt.Edge.LeftEdge:
                    g.setLeft(min(g0.right() - mw, g0.left() + d.x()))
                if edges & Qt.Edge.RightEdge:
                    g.setRight(max(g0.left() + mw, g0.right() + d.x()))
                if edges & Qt.Edge.TopEdge:
                    g.setTop(min(g0.bottom() - mh, g0.top() + d.y()))
                if edges & Qt.Edge.BottomEdge:
                    g.setBottom(max(g0.top() + mh, g0.bottom() + d.y()))
                self.setGeometry(g)
            return
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


# ---------------------------------------------------------------- keycaps (shared by menu, tips, help sheet)
_MAC_GLYPHS = {"Ctrl": "⌃", "Option": "⌥", "Cmd": "⌘", "Shift": "⇧"}
_ARROWS = {"Up": "↑", "Down": "↓", "Left": "←", "Right": "→"}


def split_keys(combo):
    """'Ctrl+Alt+Up' -> ['Ctrl', 'Alt', '↑'] (Mac modifiers become ⌃ ⌥ ⌘). '+' alone stays a key."""
    if combo in ("+", "-"):
        return [combo]
    out = []
    for k in combo.replace("++", "+Plus").split("+"):
        k = "+" if k == "Plus" else k
        if native.CMD == "Cmd":
            k = _MAC_GLYPHS.get(k, k)
        out.append(_ARROWS.get(k, k))
    return out


def keys_width(combo, font_, gap=3.0):
    fm = QFontMetricsF(font_)
    keys = split_keys(combo)
    return sum(max(18.0, fm.horizontalAdvance(k) + 10) for k in keys) + gap * (len(keys) - 1)


def paint_keys(p, x, cy, combo, font_, right=False, gap=3.0, h=18.0, dim=False):
    """Keycaps for a shortcut. x is the left edge (or right edge when right=True). Returns the far edge."""
    fm = QFontMetricsF(font_)
    keys = split_keys(combo)
    if right:
        x -= keys_width(combo, font_, gap)
    p.save()
    p.setFont(font_)
    for i, k in enumerate(keys):
        kw = max(18.0, fm.horizontalAdvance(k) + 10)
        r = QRectF(x, cy - h / 2, kw, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 10 if dim else 16))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))                    # bottom lip reads as a physical key
        p.drawLine(QPointF(r.left() + 3, r.bottom() - 0.5), QPointF(r.right() - 3, r.bottom() - 0.5))
        p.setPen(T.muted if dim else QColor(222, 227, 240))
        p.drawText(r.adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, k)
        x += kw + gap
    p.restore()
    return x - gap


# ---------------------------------------------------------------- glass tooltip
class GlassTip(QWidget):
    """One shared tooltip: label + keycaps on frosted ink. Replaces the OS tooltip so it matches the app."""

    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            cls._inst = GlassTip()
        return cls._inst

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text, self.keys = "", ""
        self.f = font("ui", 12, QFont.Weight.Medium)
        self.kf = font("ui", 10, QFont.Weight.DemiBold)
        self.timer = QTimer(self, singleShot=True, interval=420, timeout=self._show_now)
        self._anchor = None

    def request(self, widget, text, keys=""):
        self.text, self.keys, self._anchor = text, keys, widget
        if self.isVisible():                          # moving across buttons: no second delay
            self._show_now()
        else:
            self.timer.start()

    def cancel(self):
        self.timer.stop()
        self.hide()

    def _show_now(self):
        w = self._anchor
        if w is None or not w.isVisible():
            return
        fm = QFontMetricsF(self.f)
        kw = keys_width(self.keys, self.kf) + 10 if self.keys else 0
        width, height = int(fm.horizontalAdvance(self.text) + kw + 22), 30
        self.resize(width, height)
        g = w.mapToGlobal(QPoint(w.width() // 2, w.height() + 8))
        scr = (w.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(scr.left() + 4, min(g.x() - width // 2, scr.right() - width - 4))
        y = g.y() if g.y() + height < scr.bottom() else w.mapToGlobal(QPoint(0, -height - 8)).y()
        self.move(x, y)
        native.set_capture_excluded(self, True)
        self.show()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_glass(p, QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 245, False, radius=8, rim=0)
        p.setFont(self.f)
        p.setPen(T.on_surface)
        p.drawText(QRectF(11, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignVCenter, self.text)
        if self.keys:
            paint_keys(p, self.width() - 9, self.height() / 2, self.keys, self.kf, right=True, h=17)


class TipFilter(QObject):
    """Installs GlassTip on any widget: set widget.setProperty('tip', text) and ('keys', 'Ctrl+Alt+V')."""

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter and obj.property("tip"):
            GlassTip.get().request(obj, obj.property("tip"), obj.property("keys") or "")
        elif t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Hide) and \
                (obj.property("tip") or obj is GlassTip.get()._anchor):
            GlassTip.get().cancel()
        elif t == QEvent.Type.ToolTip and isinstance(obj, QWidget):
            if obj.property("tip"):
                return True                           # already shown on hover
            text = obj.toolTip()
            if text and len(text) <= 64 and "\n" not in text:  # any short plain tooltip in the app: "Close  (Esc)" -> label + keys
                label, _, keys = text.partition("  (")
                keys = keys.rstrip(")") if keys and len(keys) < 24 and "," not in keys else ""
                tip = GlassTip.get()
                tip.text, tip.keys, tip._anchor = (label if keys else text), keys, obj
                tip._show_now()
                return True
        return False


# ---------------------------------------------------------------- glass menu
class GlassMenu(QWidget):
    """Painted popup menu: icon, label, right-aligned keycaps, inline switches and steppers.

    items: dicts with kind in {"action", "toggle", "stepper", "sep", "header"}
      action:  icon, text, keys, fn                   (closes the menu, then runs fn)
      toggle:  icon, text, keys, fn, state()          (stays open; shows a switch)
      stepper: icon, text, value() -> str, dec, inc   (stays open; [-] value [+], Left/Right keys)
    """

    ROW, SEP, HEAD, PAD, W = 34, 9, 26, 6, 288
    closed = Signal()

    def __init__(self, items, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Menu")
        self.items = items
        self.hover = -1
        self.f = font("ui", 13)
        self.hf = font("ui", 11, QFont.Weight.DemiBold)
        self.kf = font("ui", 10, QFont.Weight.DemiBold)
        self.vf = font("ui", 12, QFont.Weight.DemiBold)
        self.rects = []
        y = self.PAD
        for it in items:
            h = {"sep": self.SEP, "header": self.HEAD}.get(it["kind"], self.ROW)
            self.rects.append(QRectF(self.PAD, y, self.W - 2 * self.PAD, h))
            y += h
        self.resize(self.W, int(y + self.PAD))
        # fade-in is painted (window opacity is unreliable on translucent popups on Windows)
        self._t0, self._fade = 0.0, 0.14
        self._tick = QTimer(self, interval=16, timeout=self._step)

    # geometry ---------------------------------------------------------------
    def popup_under(self, button, reduce_motion=False):
        g = button.mapToGlobal(QPoint(button.width(), button.height() + 6))
        scr = (button.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = max(scr.left() + 6, min(g.x() - self.width(), scr.right() - self.width() - 6))
        y = g.y()
        if y + self.height() > scr.bottom():
            y = button.mapToGlobal(QPoint(0, -self.height() - 6)).y()
        self.move(x, y)
        self.hover = -1
        import time as _time
        self._t0 = _time.monotonic() - (self._fade if reduce_motion else 0.0)
        self.show()
        native.set_capture_excluded(self, True)
        self.setFocus()
        if not reduce_motion:
            self._tick.start()

    def _progress(self):
        import time as _time
        return min(1.0, (_time.monotonic() - self._t0) / self._fade)

    def _step(self):
        if self._progress() >= 1.0:
            self._tick.stop()
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()

    def _stepper_hits(self, r):
        plus = QRectF(r.right() - 30, r.center().y() - 13, 26, 26)
        minus = QRectF(plus.left() - 52, plus.top(), 26, 26)
        return minus, plus

    def _index_at(self, pos):
        for i, r in enumerate(self.rects):
            if r.contains(QPointF(pos)) and self.items[i]["kind"] not in ("sep", "header"):
                return i
        return -1

    # input --------------------------------------------------------------------
    def mouseMoveEvent(self, ev):
        i = self._index_at(ev.position())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, ev):
        self.hover = -1
        self.update()

    def mouseReleaseEvent(self, ev):
        if not self.rect().contains(ev.position().toPoint()):
            return self.close()
        i = self._index_at(ev.position())
        if i < 0:
            return
        it = self.items[i]
        if it["kind"] == "stepper":
            minus, plus = self._stepper_hits(self.rects[i])
            if minus.contains(ev.position()):
                it["dec"]()
            elif plus.contains(ev.position()):
                it["inc"]()
            self.update()
        else:
            self._activate(i)

    def _activate(self, i):
        it = self.items[i]
        if it["kind"] == "toggle":
            it["fn"]()
            self.update()
        elif it["kind"] == "action":
            self.close()
            QTimer.singleShot(0, it["fn"])           # let the popup close before dialogs open

    def keyPressEvent(self, ev):
        k = ev.key()
        sel = [i for i, it in enumerate(self.items) if it["kind"] not in ("sep", "header")]
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            step = 1 if k in (Qt.Key.Key_Down, Qt.Key.Key_Tab) else -1
            pos = sel.index(self.hover) if self.hover in sel else (-1 if step > 0 else 0)
            self.hover = sel[(pos + step) % len(sel)]
            self.update()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.hover >= 0:
            self._activate(self.hover)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.hover >= 0 \
                and self.items[self.hover]["kind"] == "stepper":
            self.items[self.hover]["inc" if k == Qt.Key.Key_Right else "dec"]()
            self.update()
        elif k == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(ev)

    # paint --------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self._progress()
        ease = 1 - (1 - k) ** 3
        p.setOpacity(ease)
        p.translate(0, (1 - ease) * -4)                # drops 4px into place
        paint_glass(p, QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 238, False, radius=12, rim=0.18)
        for i, (it, r) in enumerate(zip(self.items, self.rects)):
            kind = it["kind"]
            if kind == "sep":
                p.setPen(QPen(QColor(255, 255, 255, 18), 1))
                y = r.center().y()
                p.drawLine(QPointF(r.left() + 8, y), QPointF(r.right() - 8, y))
                continue
            if kind == "header":
                p.setFont(self.hf)
                p.setPen(T.muted)
                p.drawText(r.adjusted(10, 4, 0, 0), Qt.AlignmentFlag.AlignVCenter, it["text"].upper())
                continue
            hot = i == self.hover
            if hot:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 16))
                p.drawRoundedRect(r, 8, 8)
            on = kind == "toggle" and it["state"]()
            ic = T.aqua if on else (T.on_surface if hot else QColor(196, 202, 218))
            if it.get("icon"):
                icons.draw(p, it["icon"], QRectF(r.left() + 10, r.center().y() - 8, 16, 16), ic)
            p.setFont(self.f)
            p.setPen(T.on_surface if hot or kind != "action" or not it.get("quiet") else T.muted)
            p.drawText(QRectF(r.left() + 36, r.top(), r.width() - 120, r.height()),
                       Qt.AlignmentFlag.AlignVCenter, it["text"])
            right = r.right() - 10
            if kind == "toggle":
                tr = QRectF(right - 30, r.center().y() - 9, 30, 18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.aqua if on else QColor(255, 255, 255, 40))
                p.drawRoundedRect(tr, 9, 9)
                p.setBrush(QColor("#FFFFFF"))
                p.drawEllipse(QRectF(tr.right() - 16 if on else tr.left() + 2, tr.top() + 2, 14, 14))
                right = tr.left() - 10
            elif kind == "stepper":
                minus, plus = self._stepper_hits(r)
                for hit, glyph in ((minus, "minus"), (plus, "plus")):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 22 if hot else 12))
                    p.drawRoundedRect(hit, 7, 7)
                    icons.draw(p, glyph, hit.adjusted(6, 6, -6, -6), T.on_surface)
                p.setFont(self.vf)
                p.setPen(T.on_surface)
                p.drawText(QRectF(minus.right(), r.top(), plus.left() - minus.right(), r.height()),
                           Qt.AlignmentFlag.AlignCenter, it["value"]())
                right = minus.left() - 10
            if it.get("keys") and kind != "stepper":
                paint_keys(p, right, r.center().y(), it["keys"], self.kf, right=True, h=18, dim=not hot)
