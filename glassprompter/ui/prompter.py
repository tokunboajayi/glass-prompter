"""The prompter overlay: a frameless, always-on-top, per-pixel translucent window."""
import time

from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QToolButton, QWidget

from .. import coach as coachlib, engine, tracking
from .. import platform as native
from . import icons
from .glass import RADIUS, paint_glass
from .theme import DASH, DOT, ELLIPSIS, T, aurora_line, bar_qss, font, fonts

COUNTDOWN_STEP = 0.7


class ControlBar(QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self.setObjectName("bar")
        self.setStyleSheet(bar_qss())
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        def btn(glyph, tip, fn, name=None):
            b = QToolButton(self)
            b.setIcon(icons.icon(glyph, "#070910" if name == "play" else "#F5F7FF", 20))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setAccessibleName(tip.split("  (")[0])
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)        # clicking never steals keyboard focus
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            lay.addWidget(b)
            return b

        def sep():
            s = QFrame(self)
            s.setObjectName("sep")
            lay.addWidget(s)

        self.play = btn("play", "Play / pause  (Space, %s+Space)" % native.MOD, owner.toggle_play, "play")
        btn("restart", "Restart  (Home)", owner.restart)
        self.voice = btn("mic", "Voice Follow + Rehearsal Coach: scroll as you speak  (V, %s+V)" % native.MOD,
                         owner.toggle_voice, "voice")
        self.speak = btn("speaker", "Read aloud: hear your script at your pace  (L)", owner.toggle_read_aloud, "speak")
        sep()
        btn("minus", "Slower  (Down)", lambda: owner.change_wpm(-10))
        self.wpm = QLabel("140 wpm", self)
        self.wpm.setObjectName("wpm")
        self.wpm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.wpm)
        btn("plus", "Faster  (Up)", lambda: owner.change_wpm(+10))
        sep()
        btn("text_smaller", "Smaller text  (-)", lambda: owner.change_font(-2))
        btn("text_bigger", "Bigger text  (+)", lambda: owner.change_font(+2))
        sep()
        btn("library", "Scripts  (E)", owner.requestLibrary.emit)
        btn("phone", "Phone remote  (P)", owner.requestPhone.emit)
        btn("settings", "Settings  (%s+,)" % native.CMD, owner.requestSettings.emit)
        btn("close", "Hide  (%s+H)  %s  quit from the %s icon" % (native.MOD, DOT, native.TRAY.split(" (")[0]),
            owner.hide_window)

        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(1.0)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.finished.connect(self._finished)
        self.target = 1.0

    def fade(self, show, instant=False):
        target = 1.0 if show else 0.0
        if target == self.target and self.isVisible() == show:
            return
        self.target = target
        self.anim.stop()
        if show:
            self.show()
            self.raise_()
        if instant:
            self.effect.setOpacity(target)
            self._finished()
            return
        self.anim.setDuration(160 if show else 200)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic if show else QEasingCurve.Type.InCubic)
        self.anim.setStartValue(self.effect.opacity())
        self.anim.setEndValue(target)
        self.anim.start()

    def _finished(self):
        if self.target == 0.0:
            self.hide()


class Prompter(QWidget):
    requestLibrary = Signal()
    requestPhone = Signal()
    requestSettings = Signal()
    requestHelp = Signal()
    stateChanged = Signal()
    settingsChanged = Signal()
    pendingConsumed = Signal()
    listenRequested = Signal(bool)
    readAloudRequested = Signal(bool)
    rehearsalFinished = Signal(dict)

    def __init__(self, settings):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.cfg = settings
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)     # stay visible when Zoom is focused
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("Glass Prompter")
        self.setAccessibleName("Glass Prompter teleprompter")
        self.setMinimumSize(360, 160)
        self._place()

        self.text_font = QFont()
        self.text_font.setFamilies([f for f in (self.cfg.font_family, fonts()["display"]) if f])
        self.text_font.setPixelSize(self.cfg.font_px)
        self.text_font.setWeight(QFont.Weight.DemiBold)
        self.fm = QFontMetricsF(self.text_font)
        self.cap_font = font("ui", T.caption)
        self.badge_font = font("ui", T.caption, QFont.Weight.DemiBold)
        self.toast_font = font("ui", 13, QFont.Weight.DemiBold)
        self.count_font = font("display", 84, QFont.Weight.DemiBold)
        self.help_font = font("ui", 13)

        self.script_text, self.script_id, self.script_title = "", 0, ""
        self.lines, self.lh, self.wpl, self.pos = [], 40.0, 6.0, 0.0
        self.playing = self.counting = False
        self.count_t0 = 0.0
        self.pending = None                       # (text, id, title, source) waiting for a pause
        self.toast_msg, self.toast_color, self.toast_t0, self.toast_dur = "", T.on_surface, -10.0, 2.4
        self.cap_state = False
        self.show_help = False
        self.hovered = False
        self.remote_connected = False
        # Voice Follow
        self.listening = False
        self.voice_loading = False
        self.mic_level = 0.0
        self.vwords, self.vline, self.vtokens = [], [], {}
        self.aligner = None
        self.v_target = 0.0
        self.v_vel = 0.0
        self.v_t0 = None
        self.v_count = 0
        self.live_wpm = 0
        self.ghost = False
        self.coach = None
        self.reading_aloud = False
        self.frosted = ""
        self.cap_level, self.cap_note = native.capture_support()
        self.voice_latency = 0

        self.clock = QElapsedTimer()
        self.clock.start()
        self.last = self.now()
        self.bar = ControlBar(self)
        self.frame_timer = QTimer(self, interval=16, timeout=self.on_frame)
        self.guard_timer = QTimer(self, interval=1500, timeout=self.guard)
        self.guard_timer.start()
        self.sync_ui()

    # ------------------------------------------------------------ geometry
    def _place(self):
        g = self.cfg.geometry
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if g:
            x, y, w, h = g
            visible = any(s.availableGeometry().intersects(QRectF(x, y, w, h).toRect())
                          for s in QGuiApplication.screens())
            if visible:
                self.setGeometry(x, y, w, h)
                return
        w, h = int(scr.width() * 0.50), int(scr.height() * 0.27)
        self.setGeometry(scr.x() + (scr.width() - w) // 2, scr.y() + 6, w, h)

    def reset_position(self):
        self.cfg.geometry = []
        self._place()
        self.settingsChanged.emit()

    def hwnd(self):
        return int(self.winId())

    # ------------------------------------------------------------ basics
    def now(self):
        return self.clock.elapsed() / 1000.0

    def kick(self):
        """Run the frame loop only while something animates - zero CPU when idle."""
        if not self.frame_timer.isActive():
            self.last = self.now()
            self.frame_timer.start()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        native.prepare_window(self)
        QTimer.singleShot(0, self.apply_capture)
        QTimer.singleShot(0, self.apply_backdrop)
        self.stateChanged.emit()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.stateChanged.emit()

    def apply_backdrop(self):
        """Real frosted blur behind the panel (Windows 11 acrylic, macOS vibrancy); none in text-only mode."""
        if self.cfg.clear_mode:
            native.apply_backdrop(self, "none")
            self.frosted = ""
        else:
            self.frosted = native.apply_backdrop(self, "acrylic")
        self.update()

    # ------------------------------------------------------------ screen-share protection
    def apply_capture(self):
        native.set_capture_excluded(self, self.cfg.hide_from_capture)
        st = native.is_capture_excluded(self)
        if st != self.cap_state:
            self.cap_state = st
            self.stateChanged.emit()
        self.update()

    def guard(self):
        """Every 1.5 s ask the OS for the real state and re-apply if anything reset it."""
        if not self.isVisible():
            return
        st = native.is_capture_excluded(self)
        if st != self.cfg.hide_from_capture and self.cap_level != "none":
            native.set_capture_excluded(self, self.cfg.hide_from_capture)
            st = native.is_capture_excluded(self)
        if st != self.cap_state:
            self.cap_state = st
            self.stateChanged.emit()
            self.update()

    # ------------------------------------------------------------ text
    def pad(self):
        return max(32.0, self.width() * 0.07)

    def read_y(self):
        return self.height() * self.cfg.read_line

    def maxpos(self):
        return engine.max_pos(self.lines, self.lh)

    def relayout(self, keep=True):
        mp = self.maxpos()
        frac = self.pos / mp if (keep and mp > 0) else 0.0
        self.fm = QFontMetricsF(self.text_font)
        self.lh = self.fm.lineSpacing() * 1.12
        self.lines = engine.wrap(self.script_text, max(60.0, self.width() - 2 * self.pad()),
                                 self.fm.horizontalAdvance)
        self.wpl = engine.words_per_line(self.lines)
        cursor = self.aligner.cursor if self.aligner else -1
        self.vwords, self.vline, self.vtokens = engine.word_map(self.lines)
        self.aligner = tracking.Aligner(self.vwords)
        self.aligner.reset(min(cursor, len(self.vwords) - 1))
        self.pos = frac * self.maxpos()
        if self.listening:
            self._retarget()
        self.update()

    def set_script(self, text, script_id=0, title=""):
        self.script_text = engine.normalize(text)
        self.script_id, self.script_title = script_id, title or engine.title_from(text)
        self.playing = self.counting = False
        self.aligner = None
        if self.listening:
            self.stop_listening(summary=False)
        self.pos = 0.0
        self.relayout(keep=False)
        self.sync_ui()

    def offer_script(self, text, script_id, title, source):
        """Load now, or hold it until the reader pauses so nothing jumps mid-sentence."""
        if self.playing or self.counting:
            self.pending = (text, script_id, title, source)
            self.toast("New script from %s  %s  pause to load it" % (source, DOT), T.accent, 4)
            self.stateChanged.emit()
            return False
        self.set_script(text, script_id, title)
        self.toast("Loaded: " + self.script_title, T.ok)
        return True

    def _take_pending(self):
        text, sid, title, source = self.pending
        self.pending = None
        self.set_script(text, sid, title)
        self.toast("Loaded: " + self.script_title, T.ok)
        self.pendingConsumed.emit()

    def px_per_sec(self):
        return engine.px_per_sec(self.cfg.wpm, self.wpl, self.lh)

    def time_left(self):
        return (self.maxpos() - self.pos) / self.px_per_sec()

    def progress(self):
        mp = self.maxpos()
        return self.pos / mp if mp else 0.0

    def set_pos(self, p):
        self.pos = min(max(0.0, p), self.maxpos())
        self.update()
        self.stateChanged.emit()

    # ------------------------------------------------------------ frame loop
    def on_frame(self):
        now = self.now()
        dt, self.last = min(0.1, now - self.last), now
        busy = False
        if self.counting:
            busy = True
            if now - self.count_t0 >= 3 * COUNTDOWN_STEP:
                self.counting = False
                self.playing = True
                self.sync_ui()
        elif self.listening:
            busy = True
            # critically damped spring: glides to the voice target with no overshoot and no velocity jumps
            w0 = 9.0
            acc = w0 * w0 * (self.v_target - self.pos) - 2 * w0 * self.v_vel
            self.v_vel += acc * dt
            self.pos += self.v_vel * dt
        elif self.playing and self.lines:
            busy = True
            newp = self.pos + self.px_per_sec() * dt
            stop = engine.find_pause(self.lines, self.pos, newp, self.lh)
            if stop is not None:
                newp = stop * self.lh
                self.playing = False
                self.toast("Paused at [PAUSE]  %s  Space to continue" % DOT, T.accent, 3.0)
                self.sync_ui()
            elif newp >= self.maxpos():
                newp = self.maxpos()
                self.playing = False
                self.toast("End of script", T.on_surface)
                self.sync_ui()
            self.pos = newp
        if now - self.toast_t0 < self.toast_dur + 0.3:
            busy = True
        self.update()
        if not busy:
            self.frame_timer.stop()

    # ------------------------------------------------------------ painting
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
        phase = 0.0 if self.cfg.reduce_motion else (t * 28.0) % 360.0 if active else 210.0
        rim = 0.42 + (0.38 if active else 0.0) + (0.25 * self.mic_level if self.listening else 0.0)

        if clear:
            p.fillPath(panel, QColor(0, 0, 0, 3))              # keeps the window clickable
            if self.hovered:
                p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DashLine))
                p.drawPath(panel)
        else:
            # frosted: lighter tint so the blur shows through; plain: deeper ink glass
            tint = int(255 * self.cfg.panel_alpha * (0.62 if self.frosted else 1.0))
            paint_glass(p, QRectF(0.5, 0.5, w - 1, h - 1), tint, bool(self.frosted), rad, phase, rim,
                        glow=0.9 if active else 0.5)

        ry, lh = self.read_y(), self.lh
        if not clear:
            band = QRectF(12, ry - lh / 2, w - 24, lh)
            g = aurora_line(band.left(), band.right(), alpha=30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(band, 12, 12)
        # reading-line markers: two glowing capsules at the edges
        for x in (5.0, w - 8.0):
            glow = QColor(T.aqua)
            glow.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(QRectF(x - 2, ry - lh * 0.34 - 2, 7, lh * 0.68 + 4), 3.5, 3.5)
            p.setBrush(T.aqua)
            p.drawRoundedRect(QRectF(x, ry - lh * 0.34, 3, lh * 0.68), 1.5, 1.5)

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
        spoken_upto = self.aligner.cursor + 1 if (self.cfg.voice_follow and self.aligner) else 0
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
            alpha = 1.0 if d < 0.5 else max(0.22, 1.0 - (d - 0.5) * 0.75)
            col = QColor(T.cue if ln.kind in ("cue", "pause") else T.section if ln.kind == "section"
                         else (T.muted if ln.kind == "end" else T.on_surface))
            col.setAlphaF(alpha)
            tw = self.fm.horizontalAdvance(ln.text)
            x = (w - tw) / 2
            if ln.kind == "pause":
                pill = QRectF(x - 18, y + lh * 0.12, tw + 36, lh * 0.76)
                tp.setPen(QPen(col, 2))
                tp.setBrush(Qt.BrushStyle.NoBrush)
                tp.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            parts = [(ln.text, col)]
            ends = self.vtokens.get(i)
            if spoken_upto and ends:
                n = sum(1 for e in ends if e <= spoken_upto)
                if n:
                    toks = ln.text.split(" ")
                    said = QColor(col)
                    said.setAlphaF(alpha * 0.42)
                    head = " ".join(toks[:n])
                    parts = [(head + (" " if n < len(toks) else ""), said), (" ".join(toks[n:]), col)]
            px = x
            for seg, c in parts:
                if not seg:
                    continue
                if clear:
                    path = QPainterPath()
                    path.addText(QPointF(px, y + base_off), self.text_font, seg)
                    outline_pen.setColor(QColor(0, 0, 0, int(210 * c.alphaF())))
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
            p.setBrush(aurora_line(0, w, alpha=230))
            p.drawRoundedRect(QRectF(rad * 0.6, h - 3.5, max(3.0, (w - rad * 1.2) * self.progress()), 2.5),
                              1.25, 1.25)
        p.restore()

        self.paint_chrome(p, w, h, clear)
        if self.counting:
            self.paint_countdown(p, w, h, panel)
        if self.show_help:
            self.paint_help(p, w, h, panel)
        p.end()

    def pill(self, p, x, y, text, color, clear):
        p.setFont(self.badge_font)
        tw = QFontMetricsF(self.badge_font).horizontalAdvance(text)
        r = QRectF(x, y, tw + 26, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 14, 24, 220 if clear else 150))
        p.drawRoundedRect(r, 11, 11)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10.5, 10.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(r.x() + 11, r.center().y()), 3.5, 3.5)
        p.setPen(color)
        p.drawText(QRectF(r.x() + 19, r.y(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
        return r.right()

    def paint_chrome(self, p, w, h, clear):
        by = h - 30
        if not self.cfg.hide_from_capture:
            right = self.pill(p, 12, by, "VISIBLE in screen share  (C)", T.bad, clear)
        elif self.cap_state and self.cap_level == "full":
            right = self.pill(p, 12, by, "Hidden from screen share", T.ok, clear)
        elif self.cap_state and self.cap_level == "partial":
            right = self.pill(p, 12, by, "Share a window, not your screen", T.warn, clear)
        else:
            right = self.pill(p, 12, by, "VISIBLE " + DASH + " this system can't hide it", T.bad, clear)
        if self.remote_connected:
            right = self.pill(p, right + 6, by, "Phone connected", T.accent, clear)
        if self.ghost:
            right = self.pill(p, right + 6, by, "Ghost mode  " + DOT + "  " + native.MOD + "+G", T.muted, clear)
        if self.cfg.voice_follow:
            if self.voice_loading:
                right = self.pill(p, right + 6, by, "Loading voice" + ELLIPSIS, T.accent, clear)
            elif self.listening:
                right = self.pill(p, right + 6, by, "Listening", T.accent, clear)
                # live microphone level: five bars
                for k in range(5):
                    on = self.mic_level * 5 > k + 0.3
                    bh = 4 + k * 2.2
                    c = QColor(T.accent if on else T.outline)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(c)
                    p.drawRoundedRect(QRectF(right + 8 + k * 5, by + 17 - bh, 3, bh), 1.5, 1.5)
                right += 34
                pace = coachlib.pace_label(self.live_wpm)
                if pace:
                    col = {"good": T.ok, "fast": T.bad, "slow": T.accent}[pace]
                    right = self.pill(p, right + 4, by, {"good": "Pace good", "fast": "Slow down",
                                                         "slow": "Pick it up"}[pace], col, clear)
                if self.coach and self.coach.fillers:
                    right = self.pill(p, right + 6, by, "%d filler%s" % (sum(self.coach.fillers.values()),
                                      "" if sum(self.coach.fillers.values()) == 1 else "s"), T.muted, clear)
        if self.reading_aloud:
            right = self.pill(p, right + 6, by, "Reading aloud", T.accent, clear)
        p.setFont(self.cap_font)
        if not self.playing and not self.counting and not self.listening:
            p.setPen(T.muted)
            left = "Space to start listening" if self.cfg.voice_follow else "F1 shortcuts"
            if self.pending:
                left = "New script from %s waiting  %s  press Space to load" % (self.pending[3], DOT)
                p.setPen(T.accent)
            room = w * 0.62 - right - 12
            if QFontMetricsF(self.cap_font).horizontalAdvance(left) <= room:      # never cut words in half
                p.drawText(QRectF(right + 12, by, room, 22), Qt.AlignmentFlag.AlignVCenter, left)
        p.setPen(T.muted)
        right_txt = "%s left" % engine.fmt_secs(self.time_left())
        if self.cfg.voice_follow and self.live_wpm:
            right_txt = "You: %d wpm  %s  %s" % (self.live_wpm, DOT, right_txt)
        if self.listening and self.voice_latency:
            right_txt = "%d ms  %s  %s" % (self.voice_latency, DOT, right_txt)
        p.drawText(QRectF(w * 0.4, by, w * 0.6 - 16, 22),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right_txt)

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
            tw = min(tw, w - 60)
            r = QRectF((w - tw) / 2 - 14, h - 64 + (1 - a) * 6, tw + 28, 30)
            p.setOpacity(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(14, 16, 28, 245))
            p.drawRoundedRect(r, 15, 15)
            p.setPen(QPen(aurora_line(r.left(), r.right(), alpha=120), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14.5, 14.5)
            p.setPen(self.toast_color)
            elided = QFontMetricsF(self.toast_font).elidedText(self.toast_msg, Qt.TextElideMode.ElideRight, tw)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, elided)
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
        ring = min(h * 0.62, 132.0)
        p.setPen(QPen(QColor(255, 255, 255, 26), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-ring / 2, -ring / 2, ring, ring))
        p.setPen(QPen(aurora_line(-ring / 2, ring / 2), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(-ring / 2, -ring / 2, ring, ring), 90 * 16, int(-360 * 16 * (1 - f)))
        p.scale(scale, scale)
        p.setOpacity(alpha)
        p.setFont(self.count_font)
        p.setPen(T.on_surface)
        p.drawText(QRectF(-100, -70, 200, 140), Qt.AlignmentFlag.AlignCenter, str(n))
        p.restore()

    def paint_help(self, p, w, h, panel):
        p.fillPath(panel, QColor(T.surface))
        m = native.MOD
        cols = [
            ("From any app", [(m + "+Space", "Play / pause"), (m + "+Up / Down", "Faster / slower"),
                              (m + "+Left / Right", "Back / ahead"), (m + "+R", "Restart"),
                              ("%s+V  %s  G" % (m, DOT), "Voice Follow  %s  ghost" % DOT),
                              (m + "+PgUp / PgDn", "Previous / next section")]),
            ("On the prompter", [("Space  %s  Up / Down" % DOT, "Play  %s  speed" % DOT),
                                 ("+ / -   %s  [ / ]" % DOT, "Text size  %s  glass" % DOT),
                                 ("E  %s  %s+O  %s  %s+V" % (DOT, native.CMD, DOT, native.CMD), "Scripts  %s  open  %s  paste" % (DOT, DOT)),
                                 ("P  %s  %s+," % (DOT, native.CMD), "Phone  %s  settings" % DOT),
                                 ("T  %s  C  %s  L" % (DOT, DOT), "Text only  %s  share hiding  %s  read aloud" % (DOT, DOT)),
                                 ("V  %s  M  %s  PgUp/PgDn" % (DOT, DOT), "Voice  %s  mirror  %s  sections" % (DOT, DOT))]),
        ]
        colw = (w - 48) / 2
        for ci, (title, rows) in enumerate(cols):
            x = 24 + ci * colw
            p.setFont(self.badge_font)
            p.setPen(T.accent)
            p.drawText(QRectF(x, 16, colw, 20), Qt.AlignmentFlag.AlignVCenter, title.upper())
            p.setFont(self.help_font)
            for ri, (keys, what) in enumerate(rows):
                y = 42 + ri * 22
                p.setPen(T.on_surface)
                p.drawText(QRectF(x, y, colw * 0.44, 20), Qt.AlignmentFlag.AlignVCenter, keys)
                p.setPen(T.muted)
                p.drawText(QRectF(x + colw * 0.44, y, colw * 0.56 - 8, 20), Qt.AlignmentFlag.AlignVCenter, what)
        p.setFont(self.cap_font)
        p.setPen(T.muted)
        p.drawText(QRectF(24, h - 28, w - 48, 20), Qt.AlignmentFlag.AlignVCenter,
                   "In your script: # Heading = section  %s  [PAUSE] stops  %s  [CUE] shows in orange  %s  Esc closes"
                   % (DOT, DOT, DOT))

    # ------------------------------------------------------------ feedback
    def toast(self, msg, color=None, dur=2.4):
        self.toast_msg, self.toast_color = msg, color or T.on_surface
        self.toast_t0, self.toast_dur = self.now(), dur
        self.kick()

    def sync_ui(self):
        running = (self.playing or self.counting) if not (self.cfg.voice_follow and not self.reading_aloud) \
            else self.listening
        if running != getattr(self, "_shown_running", None):
            self._shown_running = running
            self.bar.play.setIcon(icons.icon("pause" if running else "play", "#070910", 20))
        self.bar.wpm.setText("Voice" if self.cfg.voice_follow else "%d wpm" % self.cfg.wpm)
        self.bar.speak.setProperty("on", self.reading_aloud)
        self.bar.speak.style().unpolish(self.bar.speak)
        self.bar.speak.style().polish(self.bar.speak)
        self.bar.voice.setProperty("on", self.cfg.voice_follow)
        self.bar.voice.style().unpolish(self.bar.voice)
        self.bar.voice.style().polish(self.bar.voice)
        active = self.playing or self.counting or self.listening
        show = (self.hovered or not active) and not self.show_help and not self.ghost
        self.bar.fade(show, instant=self.cfg.reduce_motion)
        if self.playing or self.counting:
            self.kick()
        self.update()
        self.stateChanged.emit()

    # ------------------------------------------------------------ actions (also called by hotkeys/remote)
    def toggle_play(self):
        if self.reading_aloud:
            return self.stop_read_aloud()
        if self.cfg.voice_follow:
            if self.pending and not self.listening:
                self._take_pending()
            if self.listening:
                self.stop_listening()
            else:
                self.start_listening()
            self.sync_ui()
            return
        if self.counting:
            self.counting = False
        elif self.playing:
            self.playing = False
            if self.pending:
                self._take_pending()
        else:
            if self.pending:
                self._take_pending()
                self.sync_ui()
                return
            if self.pos >= self.maxpos() - 1:
                self.pos = 0.0
            if self.pos <= 0.5 and self.cfg.countdown:
                self.counting = True
                self.count_t0 = self.now()
            else:
                self.playing = True
            self.last = self.now()
        self.sync_ui()

    # ---- Voice Follow
    def toggle_voice(self):
        self.cfg.voice_follow = not self.cfg.voice_follow
        if not self.cfg.voice_follow and self.listening:
            self.stop_listening(summary=False)
        if self.cfg.voice_follow:
            self.playing = self.counting = False
            self.toast("Voice Follow on  %s  press Space and start talking" % DOT, T.accent, 3)
        else:
            self.toast("Voice Follow off  %s  auto-scroll at %d wpm" % (DOT, self.cfg.wpm))
        self.settingsChanged.emit()
        self.sync_ui()

    def start_listening(self):
        if not self.vwords:
            return self.toast("This script has no words to follow", T.bad)
        if self.aligner.done:
            self.aligner.reset(-1)
            self.set_pos(0)
        if self.aligner.cursor < 0:
            # start from whatever line is on the reading line right now
            cur_line = engine.line_index(self.pos, self.lh)
            first = next((k for k, ln in enumerate(self.vline) if ln >= cur_line), 0)
            self.aligner.reset(first - 1)
        if self.reading_aloud:
            self.stop_read_aloud()
        self.listening = True
        self.voice_loading = True
        self.v_t0, self.v_count, self.live_wpm = None, 0, 0
        self.coach = coachlib.Coach(self.vwords)
        self.coach.start(time.monotonic(), self.aligner.cursor)
        self.v_target = self.pos
        self.listenRequested.emit(True)
        self.kick()
        self.sync_ui()

    def stop_listening(self, summary=True):
        was = self.listening
        self.listening = False
        self.voice_loading = False
        self.mic_level = 0.0
        self.listenRequested.emit(False)
        if was and summary and self.coach and self.v_count > 5:
            report = self.coach.report(time.monotonic())
            report["script_id"], report["title"] = self.script_id, self.script_title
            if self.cfg.coach:
                self.rehearsalFinished.emit(report)
            else:
                self.toast("Nice.  %s  %s  %d wpm" % (engine.fmt_secs(report["seconds"]), DOT, report["wpm"]), T.ok, 4)
        self.coach = None
        self.sync_ui()

    def on_utterance(self, words):
        if self.listening and self.coach:
            self.coach.on_utterance(words, time.monotonic())
            self.update()

    # ---- read aloud (text-to-speech rehearsal)
    def toggle_read_aloud(self):
        if self.reading_aloud:
            return self.stop_read_aloud()
        if self.listening:
            self.stop_listening(summary=False)
        self.reading_aloud = True
        self.counting = False
        self.playing = True                                     # scroll along with the voice
        self.last = self.now()
        self.readAloudRequested.emit(True)
        self.toast("Reading aloud at %d wpm  %s  L to stop" % (self.cfg.wpm, DOT), T.accent, 3)
        self.sync_ui()

    def stop_read_aloud(self):
        self.reading_aloud = False
        self.playing = False
        self.readAloudRequested.emit(False)
        self.sync_ui()

    def on_read_aloud_done(self):
        if self.reading_aloud:
            self.reading_aloud = False
            self.playing = False
            self.toast("Finished reading aloud", T.ok)
            self.sync_ui()

    def on_voice_status(self, status):
        self.voice_loading = status == "loading"
        if status == "stopped" and self.listening:
            self.listening = False
            self.sync_ui()
        self.update()

    def on_level(self, level):
        self.mic_level = level
        if self.listening:
            self.update()

    def on_heard(self, words):
        if not self.listening or not self.aligner:
            return
        self.voice_loading = False
        before = self.aligner.cursor
        c = self.aligner.update(words)
        if c > before and self.coach:
            self.coach.on_cursor(before, c)
        if c > before:
            now = time.monotonic()
            if self.v_t0 is None:
                self.v_t0 = now
            self.v_count += c - before
            mins = max(1e-6, (now - self.v_t0) / 60.0)
            if now - self.v_t0 > 4:
                self.live_wpm = int(round(self.v_count / mins))
        if c != before:
            self._retarget()
            self.stateChanged.emit()
        if self.aligner.done and not getattr(self, "_finishing", False):
            # wait a moment so the recognizer's final phrase (and any last filler) reaches the coach
            self._finishing = True
            QTimer.singleShot(1300, self._finish_run)

    def _finish_run(self):
        self._finishing = False
        if self.listening:
            self.stop_listening()
            if not self.cfg.coach:
                self.toast("End of script  %s  %d wpm average" % (DOT, self.live_wpm) if self.live_wpm
                           else "End of script", T.ok, 4)

    def _retarget(self):
        if self.vline:
            self.v_target = min(self.maxpos(), engine.voice_target(self.vline, self.aligner.cursor) * self.lh)
        self.kick()

    def on_voice_stats(self, stats):
        self.voice_latency = int(stats.get("latency_ms", 0))

    # ---- sections
    def jump_section(self, direction):
        secs = engine.sections(self.lines)
        if not secs:
            return self.nudge(4 * direction)
        cur = engine.line_index(self.pos, self.lh)
        if direction > 0:
            target = next((i for i, _ in secs if i > cur), None)
        else:
            target = next((i for i, _ in reversed(secs) if i < cur), None)
        if target is None:
            return self.toast("No more sections")
        self.set_pos(target * self.lh)
        if self.aligner:
            first = next((k for k, ln in enumerate(self.vline) if ln > target), len(self.vwords))
            self.aligner.reset(first - 1)
            self.v_target = self.pos
        self.toast(self.lines[target].text.title())

    # ---- ghost (click-through) & mirror
    def set_ghost(self, on):
        self.ghost = bool(on) and native.set_click_through(self, True)
        if not on:
            native.set_click_through(self, False)
        self.toast("Ghost mode: clicks pass through  %s  %s+G to undo" % (DOT, native.MOD) if self.ghost
                   else "Ghost mode off", T.accent if self.ghost else None, 3.5)
        self.sync_ui()

    def toggle_ghost(self):
        self.set_ghost(not self.ghost)

    def toggle_mirror(self):
        self.cfg.mirror = not self.cfg.mirror
        self.toast("Mirrored text" if self.cfg.mirror else "Normal text")
        self.settingsChanged.emit()
        self.update()

    def restart(self):
        self.playing = self.counting = False
        if self.aligner:
            self.aligner.reset(-1)
        self.v_target = 0.0
        self.set_pos(0)
        self.sync_ui()

    def nudge(self, n):
        self.set_pos(self.pos + n * self.lh)
        if self.listening and self.aligner and self.vline:
            cur_line = engine.line_index(self.pos, self.lh)
            first = next((k for k, ln in enumerate(self.vline) if ln >= cur_line), len(self.vwords))
            self.aligner.reset(first - 1)
            self.v_target = self.pos

    def change_wpm(self, d):
        lo, hi = 40, 400
        self.cfg.wpm = int(min(hi, max(lo, self.cfg.wpm + d)))
        self.toast("%d words per minute" % self.cfg.wpm)
        self.sync_ui()
        self.settingsChanged.emit()

    def change_font(self, d):
        self.cfg.font_px = int(min(96, max(14, self.cfg.font_px + d)))
        self.text_font.setPixelSize(self.cfg.font_px)
        self.relayout(keep=True)
        self.toast("Text size %d px" % self.cfg.font_px)
        self.settingsChanged.emit()
        self.stateChanged.emit()

    def change_glass(self, d):
        if self.cfg.clear_mode:
            return self.toast("Glass level applies to panel mode  %s  press T" % DOT)
        self.cfg.panel_alpha = round(min(1.0, max(0.2, self.cfg.panel_alpha + d)), 2)
        self.toast("Glass %d%%" % int(self.cfg.panel_alpha * 100))
        self.settingsChanged.emit()

    def toggle_clear(self):
        self.cfg.clear_mode = not self.cfg.clear_mode
        self.apply_backdrop()
        self.toast("Text-only mode" if self.cfg.clear_mode else "Glass panel mode")
        self.settingsChanged.emit()

    def toggle_capture(self):
        self.cfg.hide_from_capture = not self.cfg.hide_from_capture
        self.apply_capture()
        if self.cap_state:
            self.toast("Hidden from screen share", T.ok)
        else:
            self.toast("Viewers can now see the prompter", T.bad, 3.5)
        self.settingsChanged.emit()

    def apply_settings(self):
        """Re-read every visual setting (called after the settings dialog changes something)."""
        self.text_font.setPixelSize(self.cfg.font_px)
        self.apply_capture()
        self.apply_backdrop()
        self.relayout(keep=True)
        self.sync_ui()

    def hide_window(self):
        self.playing = self.counting = False
        self.sync_ui()
        self.hide()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def toggle_window(self):
        self.hide_window() if self.isVisible() else self.show_window()

    def toggle_help(self):
        self.show_help = not self.show_help
        self.sync_ui()

    # ------------------------------------------------------------ mouse
    def edges_at(self, pt):
        m = 8
        e = Qt.Edge(0)
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
            return
        self.setFocus()
        if self.show_help:
            self.show_help = False
            self.sync_ui()
        edges = self.edges_at(ev.position().toPoint())
        wh = self.windowHandle()
        if edges != Qt.Edge(0):
            wh.startSystemResize(edges)
        else:
            wh.startSystemMove()

    def mouseDoubleClickEvent(self, ev):
        self.toggle_play()

    def mouseMoveEvent(self, ev):
        e = self.edges_at(ev.position().toPoint())
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
            self.setCursor(Qt.CursorShape.ArrowCursor if self.playing else Qt.CursorShape.SizeAllCursor)

    def wheelEvent(self, ev):
        self.nudge(-ev.angleDelta().y() / 120.0)

    def enterEvent(self, ev):
        self.hovered = True
        self.sync_ui()

    def leaveEvent(self, ev):
        self.hovered = False
        self.sync_ui()

    def resizeEvent(self, ev):
        self.bar.adjustSize()
        self.bar.move(self.width() - self.bar.width() - 10, 8)
        self.relayout(keep=True)
        self._geometry_changed()

    def moveEvent(self, ev):
        self._geometry_changed()

    def _geometry_changed(self):
        if self.isVisible():
            g = self.geometry()
            self.cfg.geometry = [g.x(), g.y(), g.width(), g.height()]
            self.settingsChanged.emit()

    # ------------------------------------------------------------ keyboard
    def keyPressEvent(self, ev):
        mods = ev.modifiers()
        if (mods & Qt.KeyboardModifier.ControlModifier or mods & Qt.KeyboardModifier.MetaModifier) \
                and mods & Qt.KeyboardModifier.AltModifier:
            return                                      # global hotkeys handle these
        k, K = ev.key(), Qt.Key
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if ctrl:
            fn = {K.Key_O: self.requestLibrary.emit, K.Key_V: self.paste_clipboard,
                  K.Key_Comma: self.requestSettings.emit}.get(k)
            if fn:
                return fn()
        if k == K.Key_Escape:
            if self.show_help:
                self.toggle_help()
            return
        fn = {
            K.Key_Space: self.toggle_play, K.Key_Up: lambda: self.change_wpm(10),
            K.Key_Down: lambda: self.change_wpm(-10), K.Key_Left: lambda: self.nudge(-1),
            K.Key_Right: lambda: self.nudge(1), K.Key_PageUp: lambda: self.jump_section(-1),
            K.Key_PageDown: lambda: self.jump_section(1), K.Key_Home: self.restart, K.Key_R: self.restart,
            K.Key_V: self.toggle_voice, K.Key_G: self.toggle_ghost, K.Key_M: self.toggle_mirror,
            K.Key_L: self.toggle_read_aloud,
            K.Key_Plus: lambda: self.change_font(2), K.Key_Equal: lambda: self.change_font(2),
            K.Key_Minus: lambda: self.change_font(-2), K.Key_BracketLeft: lambda: self.change_glass(-0.05),
            K.Key_BracketRight: lambda: self.change_glass(0.05), K.Key_T: self.toggle_clear,
            K.Key_C: self.toggle_capture, K.Key_E: self.requestLibrary.emit, K.Key_P: self.requestPhone.emit,
            K.Key_F1: self.toggle_help, K.Key_Question: self.toggle_help,
        }.get(k)
        if fn:
            fn()
        else:
            super().keyPressEvent(ev)

    paste_requested = None          # set by the controller

    def paste_clipboard(self):
        if self.paste_requested:
            self.paste_requested(QGuiApplication.clipboard().text())

    # ------------------------------------------------------------ remote state
    def snapshot(self):
        return {
            "playing": self.playing, "counting": self.counting, "wpm": self.cfg.wpm,
            "left": engine.fmt_secs(self.time_left()), "progress": round(self.progress(), 4),
            "queued": self.pending is not None, "capture_hidden": self.cap_state,
            "window_visible": self.isVisible(), "font_px": self.cfg.font_px,
            "voice_follow": self.cfg.voice_follow, "listening": self.listening, "live_wpm": self.live_wpm,
            "ghost": self.ghost, "mirror": self.cfg.mirror, "reading_aloud": self.reading_aloud,
            "fillers": sum(self.coach.fillers.values()) if self.coach else 0,
            "voice_latency_ms": self.voice_latency if self.listening else 0,
            "sections": [t for _, t in engine.sections(self.lines)],
            "script": {"id": self.script_id, "title": self.script_title} if self.script_text else None,
        }
