"""App icon drawn in code (no binary assets to lose), plus a .ico writer used by the build."""
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap

from .theme import T

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render(size, playing=False):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 64.0
    p.scale(s, s)
    p.setPen(QPen(T.accent, 3.2))
    p.setBrush(QColor(23, 23, 29))
    p.drawRoundedRect(QRectF(4, 10, 56, 44), 12, 12)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(T.accent)
    p.drawEllipse(QRectF(27, 5, 10, 10))                          # the webcam dot
    p.setBrush(QColor(255, 255, 255))
    p.drawRoundedRect(QRectF(14, 26, 36, 5.5), 2.75, 2.75)        # the reading line
    p.setBrush(QColor(154, 154, 168))
    p.drawRoundedRect(QRectF(18, 36, 28, 4.5), 2.25, 2.25)
    p.setBrush(QColor(85, 85, 95))
    p.drawRoundedRect(QRectF(22, 44.5, 20, 3.5), 1.75, 1.75)
    if playing:
        p.setBrush(T.ok)
        p.drawEllipse(QRectF(46, 40, 16, 16))
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
