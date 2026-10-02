"""Compose the website images from tools/shots.py renders.

    GP_SHOTS_PRIVATE=1 QT_SCALE_FACTOR=2 QT_QPA_PLATFORM=offscreen python tools/shots.py shots2x
    QT_QPA_PLATFORM=offscreen python tools/marketing_images.py shots2x docs/img
"""
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

src, out = (sys.argv[1:3] + ["shots2x", "docs/img"])[:2] if len(sys.argv) > 1 else ("shots2x", "docs/img")
app = QGuiApplication(sys.argv[:1])
os.makedirs(out, exist_ok=True)


def backdrop(W, H):
    o = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(o)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor(10, 12, 22))
    g.setColorAt(1, QColor(16, 12, 30))
    p.fillRect(0, 0, W, H, g)
    for cx, cy, r, col in ((0.15, 0.1, 0.55, QColor(64, 232, 208, 60)), (0.9, 0.3, 0.5, QColor(139, 108, 255, 70)),
                           (0.5, 1.1, 0.6, QColor(255, 166, 77, 30))):
        rg = QRadialGradient(QPointF(W * cx, H * cy), W * r)
        rg.setColorAt(0, col)
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, W, H, rg)
    return o, p


def shot(name):
    return QImage(os.path.join(src, name))


# hero: a video call with the prompter right under the webcam
W, H = 2400, 1400
o, p = backdrop(W, H)
win = QRectF(200, 150, 2000, 1150)
path = QPainterPath()
path.addRoundedRect(win, 28, 28)
p.fillPath(path, QColor(22, 25, 38))
p.setPen(QPen(QColor(255, 255, 255, 28), 2))
p.drawPath(path)
for k, t in enumerate((QRectF(250, 330, 940, 760), QRectF(1210, 330, 940, 760))):
    tp = QPainterPath()
    tp.addRoundedRect(t, 20, 20)
    tg = QLinearGradient(t.topLeft(), t.bottomRight())
    tg.setColorAt(0, QColor(40, 46, 66) if k == 0 else QColor(46, 40, 64))
    tg.setColorAt(1, QColor(28, 31, 46))
    p.fillPath(tp, tg)
    p.save()
    p.setClipPath(tp)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 38))
    cx = t.center().x()
    p.drawEllipse(QPointF(cx, t.top() + 330), 120, 120)
    p.drawRoundedRect(QRectF(cx - 230, t.top() + 480, 460, 300), 160, 160)
    p.restore()
bar = QPainterPath()
bar.addRoundedRect(QRectF(250, 1130, 1900, 120), 24, 24)
p.fillPath(bar, QColor(16, 18, 28))
p.setPen(Qt.PenStyle.NoPen)
for i, col in enumerate((QColor(60, 66, 88),) * 3 + (QColor(255, 92, 122),)):
    p.setBrush(col)
    p.drawEllipse(QPointF(1035 + i * 110, 1190), 34, 34)
p.setBrush(QColor(5, 6, 10))
p.drawRoundedRect(QRectF(W / 2 - 140, 0, 280, 46), 22, 22)
p.setBrush(QColor(40, 60, 70))
p.drawEllipse(QPointF(W / 2, 22), 9, 9)
pr = shot("2_voice.png").scaledToWidth(1500, Qt.TransformationMode.SmoothTransformation)
p.drawImage(int((W - pr.width()) / 2), 70, pr)
p.end()
o.save(os.path.join(out, "hero.jpg"), "JPG", 88)

# ghost mode over a busy document
W, H = 2100, 760
o, p = backdrop(W, H)
doc = QPainterPath()
doc.addRoundedRect(QRectF(60, 60, W - 120, H - 120), 20, 20)
p.fillPath(doc, QColor(238, 241, 246))
p.setPen(QColor(60, 70, 90))
f = QFont("DejaVu Sans")
f.setPixelSize(26)
p.setFont(f)
rows = ["Q3 planning  -  agenda", "1. Revenue up 18% quarter over quarter", "2. Churn down for the third quarter in a row",
        "3. Hiring plan: two engineers, one designer", "4. Launch checklist and owners", "5. Risks and open questions",
        "Notes: the app behind stays visible and clickable", "Action items: follow up with finance by Friday",
        "Next review: two weeks from today", "Appendix: customer quotes and survey results"]
for i, r in enumerate(rows):
    p.drawText(110, 140 + i * 58, r)
gh = shot("2b_ghost.png").scaledToWidth(1800, Qt.TransformationMode.SmoothTransformation)
p.drawImage(int((W - gh.width()) / 2), 110, gh)
p.end()
o.save(os.path.join(out, "ghost.jpg"), "JPG", 88)

for name, dst, w in (("5_settings.png", "settings.jpg", 1200), ("9_report.png", "report.jpg", 900),
                     ("4_help.png", "shortcuts.jpg", 1400)):
    i = shot(name).scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
    o, p = backdrop(i.width() + 80, i.height() + 80)
    p.drawImage(40, 40, i)
    p.end()
    o.save(os.path.join(out, dst), "JPG", 88)
print("images in", out)
