"""The prompter overlay: a frameless, always-on-top, per-pixel translucent window."""
import time

from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

from .. import coach as coachlib, engine, tracking
from .. import platform as native
from . import icons
from .glass import RADIUS, GlassMenu, GlassTip, TipFilter, keys_width, paint_glass, paint_keys
from .theme import DASH, DOT, ELLIPSIS, T, aurora_line, bar_qss, font, fonts

COUNTDOWN_STEP = 0.7


class ControlBar(QFrame):
    """Floating control strip: four groups, everything else one click away in the overflow menu."""

    ICON = "#E9ECF5"

    def __init__(self, owner):
        super().__init__(owner)
        self.setObjectName("bar")
        self.setStyleSheet(bar_qss())
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        self.tips = TipFilter(self)
        self.owner = owner
        M, C = native.MOD, native.CMD

        def btn(glyph, tip, keys, fn, name=None):
            b = QToolButton(self)
            b.setIcon(icons.icon(glyph, "#0A0C14" if name == "play" else self.ICON, 18))
            b.setIconSize(QSize(18, 18))
            b.setProperty("tip", tip)
            b.setProperty("keys", keys)
            b.setAccessibleName(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)         # every action has a key; no stray focus rings
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.installEventFilter(self.tips)
            if name:
                b.setObjectName(name)
            if fn:
                b.clicked.connect(fn)
            lay.addWidget(b)
            return b

        def sep():
            s = QFrame(self)
            s.setObjectName("sep")
            lay.addWidget(s)

        self.play = btn("play", "Play / pause", "Space", owner.toggle_play, "play")
        btn("restart", "Back to the top", "Home", owner.restart)
        sep()
        self.voice = btn("mic", "Voice Follow", "V", owner.toggle_voice, "voice")
        self.speak = btn("speaker", "Read aloud", "L", owner.toggle_read_aloud, "speak")
        sep()
        btn("minus", "Slower", "Down", lambda: owner.change_wpm(-10))
        self.wpm = QLabel(self)
        self.wpm.setObjectName("wpm")
        self.wpm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wpm.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.wpm)
        btn("plus", "Faster", "Up", lambda: owner.change_wpm(+10))
        sep()
        btn("library", "Scripts", "E", owner.requestLibrary.emit)
        self.more = btn("more", "More", "", self.open_menu, "more")
        cfg = owner.cfg
        self.menu = GlassMenu([
            {"kind": "header", "text": "View"},
            {"kind": "stepper", "icon": "text_bigger", "text": "Text size",
             "value": lambda: "%d" % cfg.font_px, "dec": lambda: owner.change_font(-2),
             "inc": lambda: owner.change_font(+2)},
            {"kind": "toggle", "icon": "mirror", "text": "Mirror text", "keys": "M",
             "state": lambda: cfg.mirror, "fn": owner.toggle_mirror},
            {"kind": "toggle", "icon": "shield", "text": "Hide from screen share", "keys": "C",
             "state": lambda: cfg.hide_from_capture, "fn": owner.toggle_capture},
            {"kind": "sep"},
            {"kind": "header", "text": "Ghost"},
            {"kind": "action", "icon": "ghost", "text": "Ghost mode", "keys": M + "+G", "fn": owner.toggle_ghost},
            {"kind": "stepper", "icon": None, "text": "See-through",
             "value": lambda: "%d%%" % round(cfg.ghost_opacity * 100),
             "dec": lambda: owner.change_ghost_opacity(-0.05), "inc": lambda: owner.change_ghost_opacity(+0.05)},
            {"kind": "sep"},
            {"kind": "action", "icon": "phone", "text": "Phone remote" + ELLIPSIS, "keys": "P",
             "fn": owner.requestPhone.emit},
            {"kind": "action", "icon": "keyboard", "text": "Keyboard shortcuts", "keys": "F1",
             "fn": owner.toggle_help},
            {"kind": "action", "icon": "settings", "text": "Settings" + ELLIPSIS, "keys": C + "+,",
             "fn": owner.requestSettings.emit},
            {"kind": "sep"},
            {"kind": "action", "icon": "eye_off", "text": "Hide prompter", "keys": M + "+H",
             "fn": owner.hide_window, "quiet": True},
        ], self)
        self.menu.closed.connect(self.menu_closed)

        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(1.0)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.finished.connect(self._finished)
        self.target = 1.0

    def open_menu(self):
        GlassTip.get().cancel()
        if time.monotonic() - getattr(self, "_menu_closed_at", 0) < 0.25:
            return                                   # the click that closed the popup shouldn't reopen it
        self.more.setProperty("on", True)
        self.more.style().unpolish(self.more)
        self.more.style().polish(self.more)
        self.menu.popup_under(self.more, self.owner.cfg.reduce_motion)

    def menu_closed(self):
        self._menu_closed_at = time.monotonic()
        self.more.setProperty("on", False)
        self.more.style().unpolish(self.more)
        self.more.style().polish(self.more)

    def set_wpm(self, text, unit):
        self.wpm.setText('<span style="font-weight:600">%s</span>'
                         '<span style="color:#8C95AB">&nbsp;%s</span>' % (text, unit))


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
        self.anim.setDuration(180 if show else 120)          # exits ~65% of enters
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
        self.badge_font = font("ui", 11, QFont.Weight.DemiBold)
        self.toast_font = font("ui", 13, QFont.Weight.Medium)
        self.count_font = font("display", 60, QFont.Weight.DemiBold)
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
        self.tts_word, self.tts_follow, self.tts_preparing = -1, False, False
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
        elif self.listening or self.tts_follow:
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
                            ("H", "Show / hide"), ("G", "Ghost mode"), ("[", "More see-through"),
                            ("]", "More solid")]),
        ("On the prompter", False, [("Space", "Play / pause"), ("L", "Read aloud"), ("E", "Scripts"),
                                    ("+", "Bigger text"), ("PgDn", "Next section"), ("C", "Share privacy"),
                                    ("M", "Mirror text"), ("F1", "This sheet")]),
    )

    def paint_help(self, p, w, h, panel):
        """Shortcut sheet: two columns, label left / keys right, global modifier shown once per column."""
        p.fillPath(panel, QColor(T.surface))
        pad, gap = 28.0, 40.0
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
        colw = (w - 2 * pad - gap) / 2
        rows = max(len(r) for _, _, r in self.HELP)
        if h < 270:                                           # short prompter: drop the footer, keep every row
            foot = 0.0
        rh = min(24.0, (h - top - 30 - foot - 10) / rows)
        for ci, (title, glob, items) in enumerate(self.HELP):
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

    # ------------------------------------------------------------ feedback
    def toast(self, msg, color=None, dur=2.4):
        self.toast_msg, self.toast_color = msg, color or T.on_surface
        self.toast_t0, self.toast_dur = self.now(), dur
        self.kick()

    def sync_ui(self):
        if self.reading_aloud:
            running = True
        elif self.cfg.voice_follow:
            running = self.listening
        else:
            running = self.playing or self.counting
        if running != getattr(self, "_shown_running", None):
            self._shown_running = running
            self.bar.play.setIcon(icons.icon("pause" if running else "play", "#0A0C14", 18))
        if self.cfg.voice_follow:
            self.bar.set_wpm("Voice", "follow")
        else:
            self.bar.set_wpm(str(self.cfg.wpm), "wpm")
        self.bar.speak.setProperty("on", self.reading_aloud)
        self.bar.speak.style().unpolish(self.bar.speak)
        self.bar.speak.style().polish(self.bar.speak)
        self.bar.voice.setProperty("on", self.cfg.voice_follow)
        self.bar.voice.style().unpolish(self.bar.voice)
        self.bar.voice.style().polish(self.bar.voice)
        active = self.playing or self.counting or self.listening or self.reading_aloud
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
        self.tts_word, self.tts_follow, self.tts_preparing = -1, False, True
        self.playing = True                                     # system voice: scroll at wpm
        self.last = self.now()
        self.readAloudRequested.emit(True)
        self.sync_ui()

    def read_start_word(self):
        """First word on the line at the reading band, so Read Aloud starts where you are."""
        if self.pos <= 0.5 or not self.vline:
            return 0
        cur = engine.line_index(self.pos, self.lh)
        return next((k for k, ln in enumerate(self.vline) if ln >= cur), 0)

    def set_tts_follow(self, natural):
        """Natural voice: the band follows the spoken word instead of a fixed wpm."""
        self.tts_follow = bool(natural)
        if natural:
            self.playing = False
            self.v_target, self.v_vel = self.pos, 0.0
        self.kick()

    def on_tts_progress(self, word):
        if not self.reading_aloud:
            return
        self.tts_preparing = False
        self.tts_word = word
        if self.vline:
            self.v_target = min(self.maxpos(), engine.voice_target(self.vline, word) * self.lh)
        self.kick()

    def on_tts_status(self, status):
        self.tts_preparing = status == "preparing"
        self.update()

    def stop_read_aloud(self):
        self.reading_aloud = False
        self.tts_follow = False
        self.playing = False
        self.readAloudRequested.emit(False)
        self.sync_ui()

    def on_read_aloud_done(self):
        if self.reading_aloud:
            self.reading_aloud = False
            self.tts_follow = False
            self.playing = False
            self.toast("Finished reading", T.ok)
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
    def ghost_op(self):
        return self.cfg.ghost_opacity if self.ghost else 1.0

    def set_ghost(self, on):
        self.ghost = bool(on) and native.set_click_through(self, True)
        if not on:
            native.set_click_through(self, False)
        # the frosted backdrop is drawn by the OS and would stay opaque: drop it while ghosted
        if self.ghost and not self.cfg.clear_mode:
            native.apply_backdrop(self, "none")
            self.frosted = ""
        else:
            self.apply_backdrop()
        if self.ghost:
            self.toast("Ghost %d%%  %s  clicks pass through  %s  %s+[ ]  adjust  %s  %s+G  exit"
                       % (round(self.cfg.ghost_opacity * 100), DOT, DOT, native.MOD, DOT, native.MOD), T.aqua, 4)
        else:
            self.toast("Ghost mode off")
        self.sync_ui()

    def change_ghost_opacity(self, d):
        self.cfg.ghost_opacity = round(min(1.0, max(0.15, self.cfg.ghost_opacity + d)), 2)
        self.settingsChanged.emit()
        if self.ghost:
            self.toast("Ghost %d%%" % round(self.cfg.ghost_opacity * 100), T.aqua, 1.4)
        else:
            self.toast("Ghost level %d%%  %s  turn on with %s+G" % (round(self.cfg.ghost_opacity * 100), DOT,
                                                                   native.MOD))
        self.update()

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
