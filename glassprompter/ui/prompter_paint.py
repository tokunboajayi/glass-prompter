"""Painting for the prompter window: text, markers, chrome, countdown, help overlay."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from .. import coach as coachlib, engine
from .. import platform as native
from . import icons
from .glass import RADIUS, keys_width, paint_glass, paint_keys
from .theme import DASH, DOT, ELLIPSIS, T, aurora_line, font


COUNTDOWN_STEP = 0.7


class PrompterPaint:
    def paintEvent(self, e):
        w, h = float(self.width()), float(self.height())
        clear = self.cfg.clear_mode
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rad = RADIUS if self.frosted else T.radius
        panel = QPainterPath()
        panel.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), rad, rad)
        active = self.playing or self.counting or self.listening or self.reading_aloud
        t = self.now()
        phase = 0.0 if (self.cfg.reduce_motion or not active) else (t * 18.0) % 360.0
        rim = 0.28 + (0.36 if active else 0.0) + (0.3 * self.mic_level if self.listening else 0.0)
        gop = self.ghost_op()                   # 1.0 normally; the chosen see-through level in ghost mode
        outline = clear or gop < 0.8            # see-through panel: give letters a soft dark edge to stay legible

        if clear:
            p.fillPath(panel, QColor(0, 0, 0, 3))              # keeps the window clickable
            if self.hovered:
                p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DashLine))
                p.drawPath(panel)
        else:
            # frosted: lighter tint so the blur shows through; plain: deeper ink glass
            tint = int(255 * self.cfg.panel_alpha * (0.62 if self.frosted else 1.0) * gop)
            paint_glass(p, QRectF(0.5, 0.5, w - 1, h - 1), max(3, tint), bool(self.frosted), rad, phase,
                        rim * (0.4 + 0.6 * gop), glow=(0.8 if active else 0.0) * gop)

        ry, lh = self.read_y(), self.lh
        if not clear:
            # reading band: a soft lift of light that fades out toward the edges (no hard box)
            band = QRectF(0, ry - lh * 0.56, w, lh * 1.12)
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0, QColor(255, 255, 255, 0))
            g.setColorAt(0.18, QColor(255, 255, 255, int(13 * gop)))
            g.setColorAt(0.82, QColor(255, 255, 255, int(13 * gop)))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(panel)
            p.fillRect(band, g)
            p.restore()
        if self.ghost and gop < 0.9:
            # local scrim: a soft shadow only where you read, so text holds up over any busy app
            sc = QRectF(0, ry - lh * 1.6, w, lh * 3.2)
            sg = QLinearGradient(0, sc.top(), 0, sc.bottom())
            k = int(120 * (1.0 - gop))
            sg.setColorAt(0.0, QColor(0, 0, 0, 0))
            sg.setColorAt(0.3, QColor(0, 0, 0, k))
            sg.setColorAt(0.7, QColor(0, 0, 0, k))
            sg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.save()
            p.setClipPath(panel)
            p.fillRect(sc, sg)
            p.restore()
        # reading-line markers: two slim accent ticks
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.aqua)
        for x in (7.0, w - 9.5):
            p.drawRoundedRect(QRectF(x, ry - lh * 0.22, 2.5, lh * 0.44), 1.25, 1.25)

        # script layer off-screen so the edges can fade smoothly
        dpr = self.devicePixelRatioF()
        pm = QPixmap(QSize(int(w * dpr), int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        tp = QPainter(pm)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        tp.setFont(self.text_font)
        if self.cfg.mirror:                                   # for beam-splitter teleprompter glass
            tp.translate(w, 0)
            tp.scale(-1, 1)
        top0 = ry - lh / 2
        spoken_upto = 0
        if self.tts_follow and self.tts_word >= 0:
            spoken_upto = self.tts_word + 1
        elif self.cfg.voice_follow and self.aligner and not self.reading_aloud:
            spoken_upto = self.aligner.cursor + 1
        first = max(0, int((self.pos - ry) / lh) - 1)
        last = min(len(self.lines), first + int(h / lh) + 4)
        base_off = (lh - self.fm.height()) / 2 + self.fm.ascent()
        outline_pen = QPen(QColor(0, 0, 0, 210), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                           Qt.PenJoinStyle.RoundJoin)
        for i in range(first, last):
            ln = self.lines[i]
            if not ln.text:
                continue
            y = top0 + i * lh - self.pos
            d = abs(y + lh / 2 - ry) / lh
            alpha = 1.0 if d < 0.5 else max(0.30, 1.0 - (d - 0.5) * 0.6)
            if ln.kind in ("cue", "pause", "section", "end"):
                self._paint_marker(tp, ln, w, y, lh, alpha, clear)
                continue
            col = QColor(T.on_surface)
            col.setAlphaF(alpha * (0.8 + 0.2 * gop))   # the panel goes see-through, the words stay legible
            tw = self.fm.horizontalAdvance(ln.text)
            x = (w - tw) / 2
            parts = [(ln.text, col)]
            ends = self.vtokens.get(i)
            if spoken_upto and ends:
                n = sum(1 for e in ends if e <= spoken_upto)
                if n:
                    toks = ln.text.split(" ")
                    said = QColor(col)
                    if gop >= 0.8:
                        said.setAlphaF(alpha * 0.36)
                    else:                                   # see-through: dim by colour, not alpha
                        said = QColor(150, 156, 172)
                        said.setAlphaF(col.alphaF())
                    head = " ".join(toks[:n])
                    parts = [(head + (" " if n < len(toks) else ""), said), (" ".join(toks[n:]), col)]
            px = x
            for seg, c in parts:
                if not seg:
                    continue
                if outline:
                    path = QPainterPath()
                    path.addText(QPointF(px, y + base_off), self.text_font, seg)
                    outline_pen.setColor(QColor(0, 0, 0, int(235 * min(1.0, c.alphaF() * 1.3))))
                    tp.strokePath(path, outline_pen)
                    tp.fillPath(path, c)
                else:
                    tp.setPen(c)
                    tp.drawText(QPointF(px, y + base_off), seg)
                px += self.fm.horizontalAdvance(seg)
        tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        g = QLinearGradient(0, 0, 0, h)
        top_stop = min(0.5, max(0.06, (ry - lh * 1.4) / h))
        bottom = max(top_stop + 0.05, (h - 34) / h)
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(top_stop, QColor(0, 0, 0, 255))
        g.setColorAt(max(top_stop + 0.01, bottom - 0.20), QColor(0, 0, 0, 255))
        g.setColorAt(bottom, QColor(0, 0, 0, 0))
        tp.fillRect(QRectF(0, 0, w, h), QBrush(g))
        tp.end()
        p.save()
        p.setClipPath(panel)
        p.drawPixmap(0, 0, pm)
        if self.progress() > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(aurora_line(0, w, alpha=210))
            p.drawRect(QRectF(0, h - 2, w * self.progress(), 2))
        p.restore()

        p.setOpacity(max(0.45, gop))
        self.paint_chrome(p, w, h, clear or gop < 0.8)
        p.setOpacity(1.0)
        if self.counting:
            self.paint_countdown(p, w, h, panel)
        if self.show_help:
            self.paint_help(p, w, h, panel)
        p.end()

    def _paint_marker(self, tp, ln, w, y, lh, alpha, clear):
        """Sections read as editorial headings; cues and [PAUSE] as small chips - never confused with lines
        you're meant to say."""
        if ln.kind == "section":
            f = QFont(self.text_font)
            f.setPixelSize(max(11, int(self.cfg.font_px * 0.40)))
            f.setWeight(QFont.Weight.Bold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(1.5, self.cfg.font_px * 0.06))
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(ln.text)
            cy = y + lh / 2
            col = QColor(T.violet).lighter(125)
            col.setAlphaF(alpha)
            tp.setFont(f)
            tp.setPen(col)
            tp.drawText(QRectF(0, y, w, lh), Qt.AlignmentFlag.AlignCenter, ln.text)
            rule = QColor(col)
            rule.setAlphaF(alpha * 0.35)
            tp.setPen(QPen(rule, 1))
            gap, span = 14.0, min(64.0, w * 0.08)
            tp.drawLine(QPointF((w - tw) / 2 - gap - span, cy), QPointF((w - tw) / 2 - gap, cy))
            tp.drawLine(QPointF((w + tw) / 2 + gap, cy), QPointF((w + tw) / 2 + gap + span, cy))
            tp.setFont(self.text_font)
            return
        f = QFont(self.text_font)
        f.setPixelSize(max(11, int(self.cfg.font_px * 0.38)))
        f.setWeight(QFont.Weight.DemiBold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        fm = QFontMetricsF(f)
        label = ("PAUSE  " + chr(0x2016)) if ln.kind == "pause" else ln.text
        col = QColor(T.muted if ln.kind == "end" else T.ember)
        col.setAlphaF(alpha)
        tw = fm.horizontalAdvance(label)
        chip = QRectF((w - tw) / 2 - 12, y + lh / 2 - fm.height() / 2 - 5, tw + 24, fm.height() + 10)
        if ln.kind != "end":
            bg = QColor(col)
            bg.setAlphaF(alpha * 0.14)
            tp.setPen(Qt.PenStyle.NoPen)
            tp.setBrush(bg)
            tp.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
        tp.setFont(f)
        tp.setPen(col)
        tp.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
        tp.setFont(self.text_font)

    def status_chip(self, p, x, y, segments, clear):
        """One quiet capsule holding every live state: [(dot_color|None, text, text_color), ...].
        Segments are separated by hairlines - one element instead of a row of competing badges."""
        fm = QFontMetricsF(self.badge_font)
        pad, gap = 10.0, 9.0
        widths = []
        for dot, text, _ in segments:
            tw = 21.0 if text == "<level>" else fm.horizontalAdvance(text)
            widths.append(tw + (11 if dot is not None else 0))
        total = sum(widths) + gap * 2 * (len(segments) - 1) + pad * 2
        r = QRectF(x, y, total, 22)
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(QColor(8, 10, 18, 215 if clear else 120))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10.5, 10.5)
        p.setFont(self.badge_font)
        cx = r.x() + pad
        for i, ((dot, text, col), wd) in enumerate(zip(segments, widths)):
            if i:
                p.setPen(QPen(QColor(255, 255, 255, 26), 1))
                p.drawLine(QPointF(cx - gap, r.y() + 6), QPointF(cx - gap, r.bottom() - 6))
            tx = cx
            if dot is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(dot)
                p.drawEllipse(QPointF(cx + 3, r.center().y()), 3, 3)
                tx += 11
            if text == "<level>":
                for k in range(5):
                    on = self.mic_level * 5 > k + 0.3
                    bh = 3 + k * 1.8
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(T.aqua if on else QColor(255, 255, 255, 40))
                    p.drawRoundedRect(QRectF(tx + k * 4.5, r.center().y() + 5 - bh, 2.5, bh), 1.2, 1.2)
            else:
                p.setPen(col)
                p.drawText(QRectF(tx, r.y(), wd, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
            cx += wd + gap * 2
        return r.right()

    def paint_chrome(self, p, w, h, clear):
        by = h - 32
        on, mute = T.on_surface, T.muted
        if not self.cfg.hide_from_capture:
            segs = [(T.bad, "Visible to viewers", on)]
        elif self.cap_state and self.cap_level == "full":
            segs = [(T.ok, "Private", on)]
        elif self.cap_state and self.cap_level == "partial":
            segs = [(T.warn, "Share a window, not your screen", on)]
        else:
            segs = [(T.bad, "Visible " + DASH + " can't hide here", on)]
        if self.cfg.voice_follow and (self.listening or self.voice_loading):
            if self.voice_loading:
                segs.append((None, "Starting mic" + ELLIPSIS, mute))
            else:
                segs.append((T.aqua, "Listening", on))
                segs.append((None, "<level>", on))
                pace = coachlib.pace_label(self.live_wpm)
                if pace:
                    segs.append((None, {"good": "Good pace", "fast": "Slow down", "slow": "Pick it up"}[pace],
                                 {"good": T.ok, "fast": T.bad, "slow": T.warn}[pace]))
                n = sum(self.coach.fillers.values()) if self.coach else 0
                if n:
                    segs.append((None, "%d filler%s" % (n, "" if n == 1 else "s"), mute))
        if self.reading_aloud:
            segs.append((T.violet, "Preparing voice" + ELLIPSIS if self.tts_preparing else "Reading aloud", on))
        if self.ghost:
            segs.append((None, "Ghost  " + native.MOD + "+G", mute))
        if self.copilot_live:
            segs.append((T.violet, "Meeting", on))
        if self.remote_connected:
            segs.append((T.aqua, "Phone", on))
        right = self.status_chip(p, 12, by, segs, clear)

        p.setFont(self.cap_font)
        if not (self.playing or self.counting or self.listening or self.reading_aloud):
            p.setPen(mute)
            room = w * 0.66 - right - 14
            if self.pending:
                hint = "New script from %s  %s  Space to load" % (self.pending[3], DOT)
                p.setPen(T.aqua)
                if QFontMetricsF(self.cap_font).horizontalAdvance(hint) <= room:  # never cut words in half
                    p.drawText(QRectF(right + 14, by, room, 22), Qt.AlignmentFlag.AlignVCenter, hint)
            else:
                parts = ([("k", "Space"), ("t", "and start talking")] if self.cfg.voice_follow else
                         [("k", "Space"), ("t", "start"), ("t", DOT), ("k", "F1"), ("t", "shortcuts")])
                self._inline_hint(p, right + 14, by + 11, room, parts, mute)
        meta = ["%s left" % engine.fmt_secs(self.time_left())]
        if self.cfg.voice_follow and self.live_wpm:
            meta.insert(0, "%d wpm" % self.live_wpm)
        if self.listening and self.voice_latency:
            meta.insert(0, "%d ms" % self.voice_latency)
        p.setPen(mute)
        p.drawText(QRectF(w * 0.4, by, w * 0.6 - 16, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   ("  %s  " % DOT).join(meta))

        el = self.now() - self.toast_t0
        if self.toast_msg and el < self.toast_dur + 0.3:
            if self.cfg.reduce_motion:
                a = 1.0 if el < self.toast_dur else 0.0
            elif el < 0.16:
                a = el / 0.16
            elif el < self.toast_dur:
                a = 1.0
            else:
                a = max(0.0, 1 - (el - self.toast_dur) / 0.3)
            p.setFont(self.toast_font)
            tw = QFontMetricsF(self.toast_font).horizontalAdvance(self.toast_msg)
            tw = min(tw, w - 80)
            r = QRectF((w - tw) / 2 - 24, h - 70 + (1 - a) * 6, tw + 42, 30)
            p.setOpacity(a)
            p.setPen(QPen(QColor(255, 255, 255, 26), 1))
            p.setBrush(QColor(18, 20, 32, 240))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14.5, 14.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.toast_color if self.toast_color != T.on_surface else T.aqua)
            p.drawEllipse(QPointF(r.x() + 15, r.center().y()), 3, 3)
            p.setPen(T.on_surface)
            elided = QFontMetricsF(self.toast_font).elidedText(self.toast_msg, Qt.TextElideMode.ElideRight, tw)
            p.drawText(QRectF(r.x() + 26, r.y(), tw + 4, r.height()), Qt.AlignmentFlag.AlignVCenter, elided)
            p.setOpacity(1.0)

    def paint_countdown(self, p, w, h, panel):
        el = self.now() - self.count_t0
        n = 3 - int(el / COUNTDOWN_STEP)
        if n < 1:
            return
        f = (el % COUNTDOWN_STEP) / COUNTDOWN_STEP
        shade = QColor(T.surface)
        shade.setAlphaF(0.82)
        p.fillPath(panel, shade)
        rm = self.cfg.reduce_motion
        scale = 1.0 if rm else 1.0 + 0.22 * (1 - f) ** 3
        alpha = 1.0 if rm else min(1.0, (1 - f) * 1.8 + 0.15)
        p.save()
        p.translate(w / 2, h / 2)
        ring = min(h * 0.56, 120.0)
        p.setPen(QPen(QColor(255, 255, 255, 22), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-ring / 2, -ring / 2, ring, ring))
        p.setPen(QPen(T.aqua, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(-ring / 2, -ring / 2, ring, ring), 90 * 16, int(-360 * 16 * (1 - f)))
        p.scale(scale, scale)
        p.setOpacity(alpha)
        p.setFont(self.count_font)
        p.setPen(T.on_surface)
        p.drawText(QRectF(-100, -70, 200, 140), Qt.AlignmentFlag.AlignCenter, str(n))
        p.restore()

    def _inline_hint(self, p, x, cy, room, parts, color):
        """Status-row hint with real keycaps; skipped entirely when it doesn't fit."""
        kf = font("ui", 10, QFont.Weight.DemiBold)
        fm = QFontMetricsF(self.cap_font)
        widths = [keys_width(v, kf) if k == "k" else fm.horizontalAdvance(v) for k, v in parts]
        if sum(widths) + 6 * (len(parts) - 1) > room:
            return
        p.setFont(self.cap_font)
        for (kind, v), wdt in zip(parts, widths):
            if kind == "k":
                paint_keys(p, x, cy, v, kf, h=17, dim=True)
            else:
                p.setPen(color)
                p.setFont(self.cap_font)
                p.drawText(QRectF(x, cy - 10, wdt + 2, 20), Qt.AlignmentFlag.AlignVCenter, v)
            x += wdt + 6

    HELP = (
        ("Anywhere", True, [("Space", "Play / pause"), ("Up", "Faster"), ("Down", "Slower"), ("V", "Voice Follow"),
                            ("H", "Show / hide"), ("G", "Ghost mode"), ("Enter", "Assist me now"),
                            ("M", "Start / end meeting")]),
        ("On the prompter", False, [("Space", "Play / pause"), ("L", "Read aloud"), ("E", "Scripts"),
                                    ("+", "Bigger text"), ("PgDn", "Next section"), ("C", "Share privacy"),
                                    ("M", "Mirror text"), ("F1", "This sheet")]),
        ("Tools", False, [("K", "Meeting copilot"), ("A", "AI assistant"), ("S", "Screenshot"),
                          ("P", "Phone remote"), (native.CMD + "+,", "Settings"), (native.CMD + "+Q", "Quit")]),
    )

    def paint_help(self, p, w, h, panel):
        """Shortcut sheet: up to three columns, label left / keys right, global modifier shown once per column.
        A narrow prompter drops the Tools column (its keys are also in the menu)."""
        p.fillPath(panel, QColor(T.surface))
        pad, gap = 28.0, 36.0
        cols = self.HELP if w >= 760 else self.HELP[:2]
        kf = font("ui", 11, QFont.Weight.DemiBold)
        hf = font("ui", 14, QFont.Weight.DemiBold)
        # header
        icons.draw(p, "keyboard", QRectF(pad, 15, 18, 18), T.aqua)
        p.setFont(hf)
        p.setPen(T.on_surface)
        p.drawText(QRectF(pad + 26, 12, 300, 24), Qt.AlignmentFlag.AlignVCenter, "Keyboard shortcuts")
        p.setFont(self.cap_font)
        p.setPen(T.muted)
        esc_left = w - pad - keys_width("Esc", kf)
        paint_keys(p, esc_left, 24, "Esc", kf, dim=True)
        p.drawText(QRectF(esc_left - 106, 14, 100, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Close")
        top, foot = 48.0, 36.0
        colw = (w - 2 * pad - gap * (len(cols) - 1)) / len(cols)
        rows = max(len(r) for _, _, r in cols)
        if h < 270:                                           # short prompter: drop the footer, keep every row
            foot = 0.0
        rh = min(26.0, (h - top - 30 - foot - 10) / rows)
        for ci, (title, glob, items) in enumerate(cols):
            x = pad + ci * (colw + gap)
            p.setFont(self.badge_font)
            p.setPen(T.muted)
            p.drawText(QRectF(x, top, colw, 16), Qt.AlignmentFlag.AlignVCenter, title.upper())
            if glob:                                          # "hold Ctrl Alt" once instead of on every row
                tw = QFontMetricsF(self.badge_font).horizontalAdvance(title.upper())
                p.setFont(self.cap_font)
                p.drawText(QRectF(x + tw + 10, top, 40, 16), Qt.AlignmentFlag.AlignVCenter, "hold")
                hx = x + tw + 10 + QFontMetricsF(self.cap_font).horizontalAdvance("hold") + 6
                paint_keys(p, hx, top + 8, native.MOD, kf, h=17)
            p.setPen(QPen(QColor(255, 255, 255, 14), 1))
            p.drawLine(QPointF(x, top + 22), QPointF(x + colw, top + 22))
            for ri, (keys, what) in enumerate(items):
                cy = top + 30 + ri * rh + rh / 2
                if ri % 2 == 1:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 5))
                    p.drawRoundedRect(QRectF(x - 8, cy - rh / 2, colw + 16, rh), 6, 6)
                p.setFont(self.help_font)
                p.setPen(T.on_surface)
                p.drawText(QRectF(x, cy - rh / 2, colw - 80, rh), Qt.AlignmentFlag.AlignVCenter, what)
                paint_keys(p, x + colw, cy, keys, kf, right=True, h=min(19.0, rh - 3))
        if not foot:
            return
        # footer: script syntax as coloured tokens
        y = h - foot / 2 - 4
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        p.drawLine(QPointF(pad, h - foot - 4), QPointF(w - pad, h - foot - 4))
        x = pad
        p.setFont(self.cap_font)
        fm = QFontMetricsF(self.cap_font)
        for tok, color, what in (("In scripts", None, ""), ("# Heading", T.section, "section"),
                                 ("[PAUSE]", T.cue, "stops"), ("[Smile]", T.cue, "cue")):
            if color is None:
                p.setPen(T.muted)
                p.drawText(QRectF(x, y - 10, 200, 20), Qt.AlignmentFlag.AlignVCenter, tok)
                x += fm.horizontalAdvance(tok) + 16
                continue
            tw = fm.horizontalAdvance(tok) + 12
            chip = QRectF(x, y - 9, tw, 18)
            bg = QColor(color)
            bg.setAlpha(28)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(chip, 5, 5)
            p.setPen(color)
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, tok)
            p.setPen(T.muted)
            p.drawText(QRectF(chip.right() + 6, y - 10, 100, 20), Qt.AlignmentFlag.AlignVCenter, what)
            x = chip.right() + 6 + fm.horizontalAdvance(what) + 18
