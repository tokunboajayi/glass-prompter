"""Rehearsal report card."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import engine
from ..theme import DOT
from .common import BaseDialog, button, label


class ScoreRing(QWidget):
    def __init__(self, score):
        super().__init__()
        self.score = score
        self.setFixedSize(150, 150)
        self._shown = 0.0
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=float(score), duration=900,
                                       easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        QTimer.singleShot(150, self._anim.start)

    def _tick(self, v):
        self._shown = float(v)
        self.update()

    def color(self):
        from ..theme import T
        return T.ok if self.score >= 85 else (T.warn if self.score >= 65 else T.bad)

    def paintEvent(self, e):
        from PySide6.QtGui import QPen
        from ..theme import font
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(10, 10, 130, 130)
        p.setPen(QPen(QColor(255, 255, 255, 28), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 225 * 16, -270 * 16)
        from ..theme import aurora_line
        pen = QPen(self.color(), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        if self.score >= 85:
            pen.setBrush(aurora_line(10, 140))
        p.setPen(pen)
        p.drawArc(r, 225 * 16, int(-270 * 16 * self._shown / 100.0))
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font("display", 44, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 30, 150, 64), Qt.AlignmentFlag.AlignCenter, str(int(round(self._shown))))
        p.setPen(QColor("#9A9AA8"))
        p.setFont(font("ui", 12))
        p.drawText(QRectF(0, 88, 150, 20), Qt.AlignmentFlag.AlignCenter, "score")


class HistoryBars(QWidget):
    def __init__(self, scores):
        super().__init__()
        self.scores = list(reversed(scores))[-8:]        # oldest -> newest
        self.setFixedHeight(64)

    def paintEvent(self, e):
        from ..theme import T
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = max(1, len(self.scores))
        bw = min(26.0, (self.width() - 8) / n - 6)
        for i, s in enumerate(self.scores):
            h = max(4.0, (self.height() - 18) * s / 100.0)
            x = 4 + i * (bw + 6)
            last = i == len(self.scores) - 1
            col = QColor(T.accent if last else QColor(255, 255, 255, 60))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, self.height() - 14 - h, bw, h), 4, 4)
            p.setPen(QColor("#9A9AA8") if not last else T.accent)
            from ..theme import font
            p.setFont(font("ui", 10))
            p.drawText(QRectF(x - 4, self.height() - 13, bw + 8, 13), Qt.AlignmentFlag.AlignCenter, str(s))


class ReportDialog(BaseDialog):
    """Peak-end moment after a rehearsal: score, pace, fillers, pauses, skips, one tip, progress over time."""

    def __init__(self, parent, report, history):
        super().__init__(parent, "Rehearsal report")
        self.again = False
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(20)
        head.addWidget(ScoreRing(report["score"]))
        txt = QVBoxLayout()
        txt.addWidget(label(report.get("title", "") or "Your run", "title", True))
        trend = report.get("trend")
        if trend is not None:
            t = label(("+%d" % trend if trend >= 0 else "%d" % trend) + " vs your last run", None)
            t.setStyleSheet("color: %s; font-weight: 600;" % ("#3DDC97" if trend >= 0 else "#FF5C7A"))
            txt.addWidget(t)
        tip = label(report["tip"], None, True)
        tip.setStyleSheet("font-size: 15px;")
        txt.addSpacing(6)
        txt.addWidget(tip)
        txt.addStretch(1)
        head.addLayout(txt, 1)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(10)
        from ...coach import GOOD_PACE, pace_label
        pace = pace_label(report["wpm"]) or "good"
        fill = report["fillers"]
        top = ", ".join("%s %d" % (k, v) for k, v in sorted(fill.items(), key=lambda kv: -kv[1])[:3]) or "none"
        tiles = [
            ("PACE", "%d wpm" % report["wpm"], {"good": "in the zone", "fast": "too fast",
                                                "slow": "a bit slow"}[pace] + "  %s  %d-%d" % ((DOT,) + GOOD_PACE)),
            ("FILLERS", str(report["filler_count"]), top),
            ("PAUSES", str(report["long_pauses"]), "longest %.1fs" % report["longest_pause"]
             if report["long_pauses"] else "no long gaps"),
            ("SKIPPED", "%d words" % report["skipped"], "%d%% covered" % int(report["coverage"] * 100)),
            ("TIME", engine.fmt_secs(report["seconds"]), "spoken"),
        ]
        for i, (k, v, sub) in enumerate(tiles):
            card = QFrame()
            card.setProperty("role", "card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cl.addWidget(label(k, "section"))
            big = label(v)
            big.setStyleSheet("font-size: 21px; font-weight: 600;")
            cl.addWidget(big)
            cl.addWidget(label(sub, "muted"))
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)
        if len(history) > 1:
            lay.addWidget(label("YOUR LAST %d RUNS" % len(history), "section"))
            lay.addWidget(HistoryBars([h["score"] for h in history]))
        foot = QHBoxLayout()
        foot.addWidget(label("Everything stays on this computer.", "muted"))
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept))
        foot.addWidget(button("Practice again", self._again, primary=True))
        lay.addLayout(foot)

    def _again(self):
        self.again = True
        self.accept()
