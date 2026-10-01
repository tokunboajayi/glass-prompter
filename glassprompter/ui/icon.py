"""App icon drawn in code (no binary assets to lose), plus a .ico writer used by the build."""
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap

from .theme import T

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size, playing=False):
    """Ink tile, aurora rim and the four-point 'spark' (same mark as the phone app's icon)."""
    import math
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QLinearGradient, QPainterPath
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64.0
    p.scale(s, s)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0.0, T.aqua)
    g.setColorAt(0.55, T.violet)
    g.setColorAt(1.0, T.ember)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(12, 14, 24))
    p.drawRoundedRect(QRectF(3, 3, 58, 58), 16, 16)
    pen = QPen(g, 3.0)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4.5, 4.5, 55, 55), 14.5, 14.5)
    star = QPainterPath()
    for i in range(8):
        a = math.pi / 4 * i - math.pi / 2
        r = 19.0 if i % 2 == 0 else 4.6
        pt = QPointF(32 + r * math.cos(a), 32 + r * math.sin(a))
        star.moveTo(pt) if i == 0 else star.lineTo(pt)
    star.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(star)
    if playing:
        p.setBrush(T.ok)
        p.drawEllipse(QRectF(44, 44, 14, 14))
    p.end()
    return img


def app_icon(playing=False):
    icon = QIcon()
    for sz in SIZES:
        icon.addPixmap(QPixmap.fromImage(render(sz, playing)))
    return icon


def _png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Multi-resolution .ico with PNG-compressed entries (supported since Windows Vista)."""
    images = [(sz, _png_bytes(render(sz))) for sz in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for sz, data in images:
        dim = 0 if sz >= 256 else sz
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)


def write_iconset(folder):
    """PNG set for macOS `iconutil -c icns` (build_mac.sh turns it into GlassPrompter.icns)."""
    import os
    os.makedirs(folder, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        render(base).save(os.path.join(folder, "icon_%dx%d.png" % (base, base)))
        render(base * 2).save(os.path.join(folder, "icon_%dx%d@2x.png" % (base, base)))
