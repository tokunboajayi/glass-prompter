"""Vector icon set drawn in code: crisp at any DPI and identical on Windows and macOS (no icon fonts)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import font


def _pen(p, color, w=1.6):
    p.setPen(QPen(color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)


def draw(p, name, r, color):
    """Draw icon `name` inside rect r (any size; designed on a 20x20 grid)."""
    p.save()
    p.translate(r.x(), r.y())
    p.scale(r.width() / 20.0, r.height() / 20.0)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    if name == "play":
        path = QPainterPath()
        path.moveTo(7, 4.6)
        path.lineTo(15.6, 10)
        path.lineTo(7, 15.4)
        path.closeSubpath()
        p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(c)
        p.drawPath(path)
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(5.5, 4.5, 3.4, 11), 1.4, 1.4)
        p.drawRoundedRect(QRectF(11.1, 4.5, 3.4, 11), 1.4, 1.4)
    elif name == "restart":
        _pen(p, c)
        p.drawArc(QRectF(4, 4, 12, 12), 100 * 16, 290 * 16)
        p.drawLine(QPointF(8.2, 2.6), QPointF(10.6, 4.2))
        p.drawLine(QPointF(10.6, 4.2), QPointF(8.6, 6.2))
    elif name == "mic":
        _pen(p, c)
        p.drawRoundedRect(QRectF(7.3, 2.8, 5.4, 9.2), 2.7, 2.7)
        p.drawArc(QRectF(4.6, 5.6, 10.8, 9.4), 200 * 16, 140 * 16)
        p.drawLine(QPointF(10, 15), QPointF(10, 17.4))
        p.drawLine(QPointF(7.4, 17.4), QPointF(12.6, 17.4))
    elif name == "speaker":
        _pen(p, c)
        body = QPainterPath()
        body.moveTo(3.5, 8)
        body.lineTo(6.5, 8)
        body.lineTo(10, 4.8)
        body.lineTo(10, 15.2)
        body.lineTo(6.5, 12)
        body.lineTo(3.5, 12)
        body.closeSubpath()
        p.drawPath(body)
        p.drawArc(QRectF(9.5, 6.5, 5, 7), -55 * 16, 110 * 16)
        p.drawArc(QRectF(9.8, 4, 8, 12), -55 * 16, 110 * 16)
    elif name in ("minus", "plus"):
        _pen(p, c, 1.8)
        p.drawLine(QPointF(5, 10), QPointF(15, 10))
        if name == "plus":
            p.drawLine(QPointF(10, 5), QPointF(10, 15))
    elif name in ("text_smaller", "text_bigger"):
        big = name == "text_bigger"
        p.setPen(c)
        p.setFont(font("display", 15 if big else 11, font_weight()))
        p.drawText(QRectF(0, 1, 14 if big else 12, 18), Qt.AlignmentFlag.AlignCenter, "A")
        _pen(p, c, 1.5)
        p.drawLine(QPointF(13.5, 6), QPointF(18, 6))
        if big:
            p.drawLine(QPointF(15.75, 3.75), QPointF(15.75, 8.25))
    elif name == "library":
        _pen(p, c)
        p.drawRoundedRect(QRectF(4.5, 3, 11, 14), 2.2, 2.2)
        for y in (7, 10, 13):
            p.drawLine(QPointF(7.3, y), QPointF(12.7 if y != 13 else 10.6, y))
    elif name == "phone":
        _pen(p, c)
        p.drawRoundedRect(QRectF(6, 2.6, 8, 14.8), 2.2, 2.2)
        p.drawLine(QPointF(9, 14.6), QPointF(11, 14.6))
    elif name == "settings":
        _pen(p, c)
        for y, kx in ((6, 12.5), (14, 7.5)):
            p.drawLine(QPointF(3.5, y), QPointF(16.5, y))
            p.setBrush(QColor(14, 16, 28))
            p.drawEllipse(QPointF(kx, y), 2.3, 2.3)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif name == "close":
        _pen(p, c, 1.7)
        p.drawLine(QPointF(6, 6), QPointF(14, 14))
        p.drawLine(QPointF(14, 6), QPointF(6, 14))
    elif name == "ghost":
        _pen(p, c)
        g = QPainterPath()
        g.moveTo(4.5, 16.5)
        g.lineTo(4.5, 9)
        g.arcTo(QRectF(4.5, 3, 11, 11), 180, -180)
        g.lineTo(15.5, 16.5)
        for i in range(4):
            x = 15.5 - (i + 1) * 2.75
            g.lineTo(x + 1.375, 14.8 if i % 2 == 0 else 16.5)
            g.lineTo(x, 16.5 if i % 2 == 0 else 14.8)
        p.drawPath(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(8.2, 9), 1.1, 1.1)
        p.drawEllipse(QPointF(11.8, 9), 1.1, 1.1)
    elif name == "help":
        _pen(p, c)
        p.drawEllipse(QRectF(3, 3, 14, 14))
        p.setPen(c)
        p.setFont(font("display", 11, font_weight()))
        p.drawText(QRectF(3, 3, 14, 14), Qt.AlignmentFlag.AlignCenter, "?")
    elif name == "more":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for x in (5, 10, 15):
            p.drawEllipse(QPointF(x, 10), 1.5, 1.5)
    elif name == "mirror":
        _pen(p, c)
        p.drawLine(QPointF(10, 3), QPointF(10, 4.6))
        p.drawLine(QPointF(10, 7.2), QPointF(10, 8.8))
        p.drawLine(QPointF(10, 11.4), QPointF(10, 13))
        p.drawLine(QPointF(10, 15.4), QPointF(10, 17))
        for sx in (-1, 1):
            t = QPainterPath()
            t.moveTo(10 + sx * 2.4, 5.5)
            t.lineTo(10 + sx * 7, 14.5)
            t.lineTo(10 + sx * 2.4, 14.5)
            t.closeSubpath()
            p.drawPath(t)
    elif name == "shield":
        _pen(p, c)
        sh = QPainterPath()
        sh.moveTo(10, 2.8)
        sh.lineTo(15.8, 5.2)
        sh.lineTo(15.8, 9.4)
        sh.cubicTo(15.8, 13.2, 13.3, 16, 10, 17.4)
        sh.cubicTo(6.7, 16, 4.2, 13.2, 4.2, 9.4)
        sh.lineTo(4.2, 5.2)
        sh.closeSubpath()
        p.drawPath(sh)
        p.drawLine(QPointF(7.6, 10), QPointF(9.4, 11.8))
        p.drawLine(QPointF(9.4, 11.8), QPointF(12.6, 8.4))
    elif name == "keyboard":
        _pen(p, c)
        p.drawRoundedRect(QRectF(2.8, 5, 14.4, 10), 2.2, 2.2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for row, y in enumerate((8, 10.4)):
            for k in range(5 - row):
                p.drawEllipse(QPointF(5.6 + k * 2.2 + row * 1.1, y), 0.75, 0.75)
        _pen(p, c)
        p.drawLine(QPointF(7.4, 12.8), QPointF(12.6, 12.8))
    elif name == "eye_off":
        _pen(p, c)
        e = QPainterPath()
        e.moveTo(2.8, 10)
        e.quadTo(10, 2.6, 17.2, 10)
        e.quadTo(10, 17.4, 2.8, 10)
        p.drawPath(e)
        p.drawEllipse(QPointF(10, 10), 2.4, 2.4)
        p.drawLine(QPointF(4, 16), QPointF(16, 4))
    elif name == "camera":
        body = QPainterPath()
        body.addRoundedRect(QRectF(2.5, 6, 15, 10.5), 2.4, 2.4)
        p.drawPath(body)
        p.drawLine(QPointF(7, 6), QPointF(8.2, 3.8))
        p.drawLine(QPointF(8.2, 3.8), QPointF(11.8, 3.8))
        p.drawLine(QPointF(11.8, 3.8), QPointF(13, 6))
        p.drawEllipse(QPointF(10, 11.2), 2.8, 2.8)
    elif name == "spark":                       # brand mark: four-point star
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        s = QPainterPath()
        for i in range(8):
            a = math.pi / 4 * i - math.pi / 2
            rad = 8.5 if i % 2 == 0 else 2.6
            pt = QPointF(10 + rad * math.cos(a), 10 + rad * math.sin(a))
            s.moveTo(pt) if i == 0 else s.lineTo(pt)
        s.closeSubpath()
        p.drawPath(s)
    p.restore()


def font_weight():
    from PySide6.QtGui import QFont
    return QFont.Weight.Bold


def icon(name, color="#F5F7FF", size=20):
    ic = QIcon()
    for dpr in (1.0, 1.5, 2.0, 3.0):
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        draw(p, name, QRectF(0, 0, size, size), color)
        p.end()
        ic.addPixmap(pm)
    return ic
