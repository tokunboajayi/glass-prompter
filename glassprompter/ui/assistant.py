"""AI assistant window on the computer: chat with Claude, optionally showing it your screen, plus one-click screenshots.

The window is hidden from screen capture (like every Glass Prompter window), so the screenshot Claude sees is what's
underneath it. Requests run on a worker thread; the UI never blocks.
"""
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import ai
from .theme import T

_BUBBLE = {
    "user": "background: rgba(64,232,208,0.16); border: 1px solid rgba(64,232,208,0.45);",
    "assistant": "background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14);",
    "error": "background: rgba(255,92,122,0.10); border: 1px solid rgba(255,92,122,0.45); color: #FF8DA3;",
    "note": "background: transparent; border: 0; color: #A0A8BC; font-style: italic;",
}


class _Relay(QObject):
    """Carries worker-thread results back to the UI thread (queued signal)."""
    done = Signal(object, object)            # (reply text | None, error text | None)


class _Composer(QPlainTextEdit):
    send = Signal()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.send.emit()
            return
        super().keyPressEvent(e)


def _small(text, fn):
    b = QPushButton(text)
    b.setProperty("compact", True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(fn)
    return b


def make_assistant(controller):
    from .dialogs import BaseDialog, button, label

    class Assistant(BaseDialog):
        def __init__(self):
            super().__init__(None, "AI assistant", resizable=True)
            self.c = controller
            self.history = []
            self.busy = False
            self.relay = _Relay()
            self.relay.done.connect(self._answered)
            self.resize(560, 680)
            self.setMinimumSize(420, 460)

            root = QVBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(10)

            top = QHBoxLayout()
            self.info = label("", "muted", True)
            top.addWidget(self.info, 1)
            top.addWidget(_small("Screenshot", self.screenshot))
            top.addWidget(_small("Clear", self.clear))
            root.addLayout(top)

            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            self.log = QWidget()
            self.log_lay = QVBoxLayout(self.log)
            self.log_lay.setContentsMargins(0, 4, 6, 4)
            self.log_lay.setSpacing(10)
            self.log_lay.addStretch(1)
            self.scroll.setWidget(self.log)
            root.addWidget(self.scroll, 1)
            self.empty = self._bubble("note", "Ask anything: \"what does this error mean?\", \"solve the question on my "
                                              "screen\", \"summarise this page\", \"write a 30-second intro\".")

            self.text = _Composer()
            self.text.setPlaceholderText("Ask anything" + "…" + "   (Enter to send, Shift+Enter for a new line)")
            self.text.setFixedHeight(84)
            self.text.send.connect(self.send)
            root.addWidget(self.text)

            row = QHBoxLayout()
            self.use_screen = QCheckBox("Include my screen")
            self.use_screen.setChecked(True)
            self.use_screen.setToolTip("Claude sees a screenshot of your screen with this question. "
                                       "Glass Prompter windows never appear in it.")
            row.addWidget(self.use_screen)
            row.addStretch(1)
            self.send_btn = button("Send", self.send, primary=True)
            row.addWidget(self.send_btn)
            root.addLayout(row)
            self.refresh_info()

        # ---------------------------------------------------------------- state
        def refresh_info(self):
            key = ai.load_key()
            model = ai.MODELS.get(self.c.cfg.s.ai_model, self.c.cfg.s.ai_model).split(" · ")[0]
            if key:
                self.info.setText("Claude %s · answers anything, can search the web and see your screen" % model)
            else:
                self.info.setText("Add your Anthropic API key in Settings › AI assistant to start.")
            self.send_btn.setEnabled(bool(key) and not self.busy)

        def _bubble(self, role, text, reply=False):
            wrap = QWidget()
            h = QHBoxLayout(wrap)
            h.setContentsMargins(0, 0, 0, 0)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setTextFormat(Qt.TextFormat.PlainText)
            lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            lab.setStyleSheet("QLabel { %s border-radius: 14px; padding: 10px 13px; font-size: 14px; }"
                              % _BUBBLE[role])
            v.addWidget(lab)
            if reply:
                tools = QHBoxLayout()
                tools.setSpacing(6)
                tools.addWidget(_small("Copy", lambda: (QGuiApplication.clipboard().setText(text),
                                                        self.c.prompter.toast("Copied", T.ok))))
                tools.addWidget(_small("Send to prompter", lambda: self.to_prompter(text)))
                tools.addStretch(1)
                v.addLayout(tools)
            if role == "user":
                h.addStretch(1)
                h.addWidget(box, 5)
            else:
                h.addWidget(box, 6)
                h.addStretch(1)
            self.log_lay.insertWidget(self.log_lay.count() - 1, wrap)
            QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))
            return wrap

        # ---------------------------------------------------------------- actions
        def _grab_jpeg(self):
            from ..app import grab_screen_jpeg
            hide = sys.platform != "win32"            # Windows already keeps this window out of captures
            if hide:
                self.setWindowOpacity(0.0)
                QApplication.processEvents()
                time.sleep(0.15)
            try:
                return grab_screen_jpeg(self.c.prompter)
            finally:
                if hide:
                    self.setWindowOpacity(1.0)

        def send(self):
            q = self.text.toPlainText().strip()
            if not q or self.busy:
                return
            key = ai.load_key()
            if not key:
                self.refresh_info()
                return
            jpeg = None
            if self.use_screen.isChecked():
                try:
                    jpeg = self._grab_jpeg()
                except Exception as e:                # noqa: BLE001 - answer without the screen
                    self._bubble("note", "Couldn't capture the screen (%s). Answering without it." % e)
            if self.empty is not None:
                self.empty.deleteLater()
                self.empty = None
            self.text.clear()
            self.history.append({"role": "user", "content": q})
            self._bubble("user", q)
            self.waiting = self._bubble("note", "Looking at your screen…" if jpeg else "Thinking…")
            self.busy = True
            self.refresh_info()
            msgs = list(self.history[-ai.MAX_TURNS:])
            title, script = self.c.prompter.script_title, self.c.prompter.script_text
            model = self.c.cfg.s.ai_model

            def work():
                try:
                    self.relay.done.emit(ai.chat(key, msgs, model, jpeg, title, script), None)
                except ai.AIError as e:
                    self.relay.done.emit(None, str(e))
                except Exception as e:                # noqa: BLE001
                    self.relay.done.emit(None, "Something went wrong: %s" % e)
            threading.Thread(target=work, name="ai-chat", daemon=True).start()

        def _answered(self, reply, error):
            self.busy = False
            if getattr(self, "waiting", None) is not None:
                self.waiting.deleteLater()
                self.waiting = None
            if reply:
                self.history.append({"role": "assistant", "content": reply})
                self._bubble("assistant", reply, reply=True)
            else:
                self.history.pop()                    # let them retry the same question
                self._bubble("error", error or "No answer.")
            self.refresh_info()
            self.text.setFocus()

        def clear(self):
            self.history = []
            while self.log_lay.count() > 1:
                it = self.log_lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.empty = self._bubble("note", "New chat. Ask anything.")

        def screenshot(self):
            from ..app import save_screenshot
            try:
                hide = sys.platform != "win32"
                if hide:
                    self.setWindowOpacity(0.0)
                    QApplication.processEvents()
                    time.sleep(0.15)
                try:
                    path = save_screenshot(self.c.prompter)
                finally:
                    if hide:
                        self.setWindowOpacity(1.0)
            except Exception as e:                    # noqa: BLE001
                self._bubble("error", "Screenshot failed: %s" % e)
                return
            note = self._bubble("note", "Screenshot saved and copied: %s" % path)
            note.setCursor(Qt.CursorShape.PointingHandCursor)
            note.mousePressEvent = lambda _e: QDesktopServices.openUrl(QUrl.fromLocalFile(path))

        def to_prompter(self, text):
            first = next((m["content"] for m in reversed(self.history) if m["role"] == "user"), "")
            s = self.c.store.create("AI: " + first[:60], text)
            self.c.load_script(s["id"], "the AI assistant")

        def done(self, r):
            self.c.assistant = None
            super().done(r)

    return Assistant()
