"""The floating control strip."""
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QToolButton

from .. import platform as native
from . import icons
from .glass import GlassMenu, GlassTip, TipFilter
from .theme import ELLIPSIS, bar_qss


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
        self.copilot = btn("wave", "Meeting copilot", "K", owner.requestCopilot.emit, "copilot")
        self.more = btn("more", "More", "", self.open_menu, "more")
        self.quit = btn("close", "Quit Glass Prompter", C + "+Q", owner.requestQuit.emit, "quit")
        cfg = owner.cfg
        self.menu = GlassMenu([
            {"kind": "header", "text": "View"},
            {"kind": "stepper", "icon": "text_bigger", "text": "Text size",
             "value": lambda: "%d" % cfg.font_px, "dec": lambda: owner.change_font(-2),
             "inc": lambda: owner.change_font(+2)},
            {"kind": "stepper", "icon": None, "text": "Panel",
             "value": lambda: "%d%%" % round(cfg.panel_alpha * 100),
             "dec": lambda: owner.change_glass(-0.1), "inc": lambda: owner.change_glass(+0.1)},
            {"kind": "stepper", "icon": None, "text": "Windows",
             "value": lambda: owner.window_glass_name(),
             "dec": lambda: owner.step_window_glass(-1), "inc": lambda: owner.step_window_glass(+1)},
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
            {"kind": "header", "text": "AI"},
            {"kind": "action", "icon": "wave", "text": "Meeting copilot" + ELLIPSIS, "keys": "K",
             "fn": owner.requestCopilot.emit},
            {"kind": "action", "icon": "history", "text": "Meeting history" + ELLIPSIS,
             "fn": owner.requestMeetings.emit},
            {"kind": "action", "icon": "spark", "text": "AI assistant" + ELLIPSIS, "keys": "A",
             "fn": owner.requestAI.emit},
            {"kind": "sep"},
            {"kind": "action", "icon": "camera", "text": "Take screenshot", "keys": "S",
             "fn": owner.requestScreenshot.emit},
            {"kind": "action", "icon": "phone", "text": "Phone remote" + ELLIPSIS, "keys": "P",
             "fn": owner.requestPhone.emit},
            {"kind": "action", "icon": "keyboard", "text": "Keyboard shortcuts", "keys": "F1",
             "fn": owner.toggle_help},
            {"kind": "action", "icon": "settings", "text": "Settings" + ELLIPSIS, "keys": C + "+,",
             "fn": owner.requestSettings.emit},
            {"kind": "sep"},
            {"kind": "action", "icon": "eye_off", "text": "Hide prompter", "keys": M + "+H",
             "fn": owner.hide_window, "quiet": True},
            {"kind": "action", "icon": "close", "text": "Quit Glass Prompter", "keys": C + "+Q",
             "fn": owner.requestQuit.emit, "quiet": True},
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
