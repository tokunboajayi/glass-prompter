"""The prompter overlay: a frameless, always-on-top, per-pixel translucent window."""
from PySide6.QtCore import QElapsedTimer, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication
from PySide6.QtWidgets import QWidget

from .. import engine, tracking
from .. import platform as native
from . import icons
from .controlbar import ControlBar
from .prompter_paint import COUNTDOWN_STEP, PrompterPaint
from .prompter_voice import PrompterVoice
from .theme import DOT, T, font, fonts


class Prompter(PrompterPaint, PrompterVoice, QWidget):
    requestLibrary = Signal()
    requestPhone = Signal()
    requestAI = Signal()
    requestCopilot = Signal()
    requestMeetings = Signal()
    requestScreenshot = Signal()
    requestSettings = Signal()
    requestQuit = Signal()
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
        self.copilot_live = False                   # the meeting copilot is transcribing (badge + lit button)
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
        self.tts_engine = ""                           # "natural" | "system" while reading aloud
        self.guard_state = ""                          # crash guard: "pending" | "ok" | "crashed:<parts>"
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
        """Real frosted blur behind the panel (Windows 11 acrylic, macOS vibrancy); none in text-only mode.
        None in ghost mode either: the OS draws it opaque, which would undo the see-through level."""
        if self.cfg.clear_mode or self.ghost:
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
        self.apply_backdrop()                      # drops the backdrop while ghosted
        if self.ghost:
            self.toast("Ghost %d%%  %s  clicks pass through  %s  %s+[ ]  adjust  %s  %s+G  exit"
                       % (round(self.cfg.ghost_opacity * 100), DOT, DOT, native.MOD, DOT, native.MOD), T.aqua, 4)
        else:
            self.toast("Ghost mode off")
        self.sync_ui()

    def change_ghost_opacity(self, d):
        """More see-through / more solid. Adjusting it switches Ghost mode on, so the change is always visible."""
        self.cfg.ghost_opacity = round(min(1.0, max(0.15, self.cfg.ghost_opacity + d)), 2)
        self.settingsChanged.emit()
        if not self.ghost:
            self.set_ghost(True)                   # shows its own toast, including how to leave Ghost mode
            if not self.ghost:                     # this OS can't pass clicks through: still show the level
                self.toast("See-through %d%%" % round(self.cfg.ghost_opacity * 100), T.aqua, 1.4)
        else:
            self.toast("See-through %d%%" % round(self.cfg.ghost_opacity * 100), T.aqua, 1.4)
        self.update()
        self.stateChanged.emit()

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

    def window_glass_name(self):
        from .glass import GlassDialog, _level_name
        return _level_name(GlassDialog.level())

    def step_window_glass(self, d):
        """Every window's see-through level: d=-1 more see-through, +1 more solid."""
        from .glass import GlassDialog, step_level
        GlassDialog.set_level(step_level(GlassDialog.level(), d))
        self.toast("Windows: %s" % self.window_glass_name())

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

    def key_toggle_capture(self):
        """The C key. Hiding is one press; SHOWING the prompter to viewers needs a second press within 3 s,
        so a stray C (for example typing while the prompter has focus) can never expose it on a call."""
        import time as _t
        if self.cfg.hide_from_capture and _t.monotonic() - getattr(self, "_reveal_armed", 0) > 3:
            self._reveal_armed = _t.monotonic()
            self.toast("Press C again to let viewers see the prompter", T.warn, 3)
            return
        self._reveal_armed = 0
        self.toggle_capture()

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

    def set_copilot_live(self, live):
        """Light the copilot button while a meeting is being transcribed, so you can see it at a glance."""
        self.copilot_live = bool(live)
        self.update()
        b = self.bar.copilot
        b.setProperty("on", bool(live))
        b.setProperty("tip", "Meeting copilot " + DOT + " live" if live else "Meeting copilot")
        b.style().unpolish(b)
        b.style().polish(b)

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
        # macOS: Qt's system move/resize doesn't work for frameless always-on-top tool panels, so drag by hand there
        # (and anywhere the system call is refused).
        ok = False
        if native.OS != "macos" and wh is not None:
            ok = wh.startSystemResize(edges) if edges != Qt.Edge(0) else wh.startSystemMove()
        if not ok:
            self._drag = (edges, ev.globalPosition().toPoint(), self.geometry())

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _manual_drag(self, gp):
        edges, start, g0 = self._drag
        d = gp - start
        if edges == Qt.Edge(0):
            self.move(g0.topLeft() + d)
            return
        g = QRect(g0)
        minw, minh = self.minimumWidth(), self.minimumHeight()
        if edges & Qt.Edge.LeftEdge:
            g.setLeft(min(g0.right() - minw, g0.left() + d.x()))
        if edges & Qt.Edge.RightEdge:
            g.setRight(max(g0.left() + minw, g0.right() + d.x()))
        if edges & Qt.Edge.TopEdge:
            g.setTop(min(g0.bottom() - minh, g0.top() + d.y()))
        if edges & Qt.Edge.BottomEdge:
            g.setBottom(max(g0.top() + minh, g0.bottom() + d.y()))
        self.setGeometry(g)

    def mouseDoubleClickEvent(self, ev):
        self._drag = None
        self.toggle_play()

    def mouseMoveEvent(self, ev):
        if getattr(self, "_drag", None) and ev.buttons() & Qt.MouseButton.LeftButton:
            self._manual_drag(ev.globalPosition().toPoint())
            return
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
                  K.Key_Comma: self.requestSettings.emit, K.Key_Q: self.requestQuit.emit}.get(k)
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
            K.Key_C: self.key_toggle_capture, K.Key_E: self.requestLibrary.emit, K.Key_P: self.requestPhone.emit,
            K.Key_A: self.requestAI.emit, K.Key_S: self.requestScreenshot.emit, K.Key_K: self.requestCopilot.emit,
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
            "ghost": self.ghost, "ghost_opacity": self.cfg.ghost_opacity, "mirror": self.cfg.mirror,
            "reading_aloud": self.reading_aloud, "tts_word": self.tts_word, "tts_engine": self.tts_engine,
            "tts_preparing": self.tts_preparing, "pos": round(self.pos, 1), "guard": self.guard_state,
            "fillers": sum(self.coach.fillers.values()) if self.coach else 0,
            "voice_latency_ms": self.voice_latency if self.listening else 0,
            "sections": [t for _, t in engine.sections(self.lines)],
            "script": {"id": self.script_id, "title": self.script_title} if self.script_text else None,
        }
