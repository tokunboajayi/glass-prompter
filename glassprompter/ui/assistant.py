"""AI assistant window on the computer: chat with any AI, optionally showing it your screen, plus one-click screenshots.

It can also listen to a meeting, through the meeting copilot (one engine, even with the copilot window closed):
  * Listen to meeting starts or joins the copilot's meeting; stopping it ends the meeting, saving the transcript,
    notes and follow-up email to Meeting history;
  * the copilot's Smart answers (an answer when they ask you something, follow-up questions after a long stretch)
    and its Assist / quick actions show up here as suggestion cards;
  * questions you type also see the conversation, your copilot mode, notes and knowledge files.

The window is hidden from screen capture (like every Glass Prompter window), so the screenshot the AI sees is what's
underneath it. Requests run on worker threads; the UI never blocks.
"""
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from .. import ai, meeting
from .glass import Switch
from .theme import ELLIPSIS, T

_BUBBLE = {
    "user": "background: rgba(64,232,208,0.16); border: 1px solid rgba(64,232,208,0.45);",
    "assistant": "background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.14);",
    "suggest": "background: rgba(139,108,255,0.12); border: 1px solid rgba(139,108,255,0.55);",
    "error": "background: rgba(255,92,122,0.10); border: 1px solid rgba(255,92,122,0.45); color: #FF8DA3;",
    "note": "background: transparent; border: 0; color: #A0A8BC; font-style: italic;",
}


class _Relay(QObject):
    """Carries worker-thread results back to the UI thread (queued signal)."""
    done = Signal(object, object)                 # (reply text | None, error text | None)


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
            self.cp = None                    # the copilot whose meeting we're listening through
            self.owns = False                 # we started that meeting, so stopping here ends it
            self.resize(580, 720)
            self.setMinimumSize(460, 520)

            root = QVBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(10)

            top = QHBoxLayout()
            self.info = label("", "muted", True)
            top.addWidget(self.info, 1)
            top.addWidget(_small("Screenshot", self.screenshot))
            top.addWidget(_small("Clear", self.clear))
            root.addLayout(top)

            # live meeting strip: listen + auto-suggest, status, the last thing heard
            strip = QFrame()
            strip.setProperty("role", "card")
            sl = QVBoxLayout(strip)
            sl.setContentsMargins(12, 8, 12, 8)
            sl.setSpacing(4)
            r = QHBoxLayout()
            r.setSpacing(16)
            self.listen_sw = Switch("Listen to meeting")
            self.listen_sw.setToolTip("Transcribe your microphone (You) and the computer's sound (Them) offline, so "
                                      "the AI can follow the conversation.")
            self.listen_sw.toggled.connect(self.set_listening)
            r.addWidget(self.listen_sw)
            self.suggest_sw = Switch("Smart answers")
            self.suggest_sw.setChecked(controller.cfg.s.copilot_smart)
            self.suggest_sw.setToolTip("While listening: an answer when someone asks you a question, and follow-up "
                                       "questions after they've talked for a while. Same switch as the copilot's.")
            self.suggest_sw.toggled.connect(self._suggest_toggled)
            r.addWidget(self.suggest_sw)
            r.addStretch(1)
            self.live_pill = label("", "idle")
            r.addWidget(self.live_pill)
            sl.addLayout(r)
            self.heard_lab = label("", "muted")
            self.heard_lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            sl.addWidget(self.heard_lab)
            # the copilot's actions, shown while listening; answers arrive in the chat below
            from .copilot import CHIPS, _btn
            self.actions = QWidget()
            al = QVBoxLayout(self.actions)
            al.setContentsMargins(0, 4, 0, 0)
            al.setSpacing(6)
            self.assist_btn = _btn("Assist", lambda: self._act("assist"),
                                   "What should I say right now? Reads the conversation and your screen.", accent=True)
            self.assist_btn.setMinimumHeight(34)
            al.addWidget(self.assist_btn)
            chips = QHBoxLayout()
            chips.setSpacing(6)
            self.chip_btns = []
            for aid, name in CHIPS:
                b = _btn(name, lambda _=False, a=aid: self._act(a), meeting.ACTIONS[aid][0], chip=True)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                chips.addWidget(b)
                self.chip_btns.append(b)
            al.addLayout(chips)
            self.actions.setVisible(False)
            sl.addWidget(self.actions)
            root.addWidget(strip)

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
                                              "screen\", \"summarise this page\". Turn on Listen to meeting and it "
                                              "follows the call and suggests answers and questions.")

            self.text = _Composer()
            self.text.setPlaceholderText("Ask anything" + ELLIPSIS + "   (Enter to send, Shift+Enter for a new line)")
            self.text.setFixedHeight(84)
            self.text.send.connect(self.send)
            root.addWidget(self.text)

            row = QHBoxLayout()
            self.use_screen = Switch("Include my screen")
            self.use_screen.setChecked(True)
            self.use_screen.setToolTip("The AI sees a screenshot of your screen with this question. "
                                       "Glass Prompter windows never appear in it.")
            row.addWidget(self.use_screen)
            row.addStretch(1)
            self.send_btn = button("Send", self.send, primary=True)
            row.addWidget(self.send_btn)
            root.addLayout(row)
            self.clock = QTimer(self, interval=1000, timeout=self.refresh_live)
            self.clock.start()
            self.refresh_info()
            self.refresh_live()

        # ---------------------------------------------------------------- state
        def _ready(self):
            return ai.is_ready(self.c.cfg.s.ai_provider)

        def refresh_info(self):
            s = self.c.cfg.s
            key = ai.load_key()
            ready = self._ready()
            if ready:
                name = ai.provider_name(s.ai_provider, key)
                self.info.setText("%s · %s · answers anything and can see your screen"
                                  % (name, s.ai_model or "best model"))
            else:
                self.info.setText("Sign in or add an API key in Settings › AI assistant to start.")
            self.send_btn.setEnabled(ready and not self.busy)

        def refresh_live(self):
            on = self.transcript is not None
            if on:
                t = meeting.fmt_clock(time.time() - self.transcript.started)
                self.live_pill.setText(chr(0x2022) + "  Live  " + t)
            else:
                self.live_pill.setText("Not listening")
            busy = self.cp is not None and self.cp.busy
            ready = self._ready() and not busy
            for b in [self.assist_btn] + self.chip_btns:
                b.setEnabled(ready)
            self.assist_btn.setText("Thinking" + ELLIPSIS if busy else "Assist")
            smart = bool(self.c.cfg.s.copilot_smart)              # the copilot window can change it too
            if self.suggest_sw.isChecked() != smart:
                self.suggest_sw.blockSignals(True)
                self.suggest_sw.setChecked(smart)
                self.suggest_sw.blockSignals(False)
            role = "live" if on else "idle"
            if self.live_pill.property("role") != role:
                self.live_pill.setProperty("role", role)
                self.live_pill.style().unpolish(self.live_pill)
                self.live_pill.style().polish(self.live_pill)
            self.heard_lab.setVisible(on)

        def _bubble(self, role, text, reply=False, header=None, sub=None):
            wrap = QWidget()
            h = QHBoxLayout(wrap)
            h.setContentsMargins(0, 0, 0, 0)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            if header:
                v.addWidget(label(header, "badge"))
            if sub:
                v.addWidget(label(sub, "muted", True))
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
            self.log_lay.addWidget(wrap)                 # stretch sits on top: chat hugs the bottom
            QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
                self.scroll.verticalScrollBar().maximum()))
            return wrap

        def _drop_empty(self):
            if self.empty is not None:
                self.empty.hide()
                self.empty.deleteLater()
                self.empty = None

        # ---------------------------------------------------------------- listening (through the copilot)
        # One meeting engine: Listen to meeting starts (or joins) the meeting copilot's meeting, even with its
        # window closed. So the transcript, mode, notes, Smart answers and the saved notes/follow-up email are the
        # same in both windows, the microphone is opened once, and nothing is asked of the AI twice.
        def following(self, cp=None):
            return self.cp is not None and (cp is None or cp is self.cp)

        @property
        def transcript(self):
            return self.cp.transcript if (self.cp is not None and self.cp.running) else None

        def set_listening(self, on):
            if on:
                self._join()
            else:
                self._leave(end=True)
            self.refresh_live()

        def _join(self):
            cp = self.c.ensure_copilot()
            self.owns = not cp.running
            if not cp.running:
                cp.start_meeting()
                if not cp.running:                       # e.g. the speech model is missing
                    self._bubble("error", cp.answer.toPlainText().strip() or "Couldn't start listening.")
                    self.owns = False
                    self._set_switch(False)
                    return
            self._attach(cp)
            self._drop_empty()
            self._bubble("note", "Listening with the meeting copilot. The meeting, its notes and a follow-up email "
                                 "are saved in Meeting history when you stop.")

        def _attach(self, cp):
            if self.cp is cp:
                return
            self._detach()
            self.cp = cp
            cp.listener.segment.connect(self._heard)
            cp.listener.partial.connect(self._partial)
            cp.answered.connect(self._copilot_answer)
            cp.answer_failed.connect(self._copilot_failed)
            cp.meeting_changed.connect(self._meeting_changed)
            self.actions.setVisible(True)
            self.heard_lab.setText("Listening" + ELLIPSIS)

        def _detach(self):
            cp, self.cp = self.cp, None
            if cp is not None:
                for sig, slot in ((cp.listener.segment, self._heard), (cp.listener.partial, self._partial),
                                  (cp.answered, self._copilot_answer), (cp.answer_failed, self._copilot_failed),
                                  (cp.meeting_changed, self._meeting_changed)):
                    try:
                        sig.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
            self.actions.setVisible(False)
            self.heard_lab.setText("")

        def _leave(self, end):
            cp, owned = self.cp, self.owns
            self._detach()
            self.owns = False
            if not (end and cp is not None and cp.running):
                return
            if owned:
                words = cp.transcript.words()
                cp.end_meeting()                         # notes + follow-up email go to Meeting history
                self._bubble("note", "Meeting ended. %s" % ("Its notes and a follow-up email will be in Meeting "
                                                            "history shortly." if words >= 15 else
                                                            "It was too short for notes, but it's in Meeting history."))
            else:
                self._bubble("note", "Stopped listening here. The meeting continues in the copilot window.")

        def _meeting_changed(self, live):
            if not live and self.cp is not None:         # ended from the copilot window
                self._detach()
                self.owns = False
                self._set_switch(False)
                self._bubble("note", "The meeting ended. Its notes are in Meeting history.")

        def _set_switch(self, on):
            self.listen_sw.blockSignals(True)
            self.listen_sw.setChecked(on)
            self.listen_sw.blockSignals(False)
            self.refresh_live()

        def _partial(self, who, text):
            if text:
                self.heard_lab.setText(("%s: %s" % (meeting.LABELS.get(who, "Them"), text))[-160:])

        def _heard(self, who, text):
            self.heard_lab.setText(("%s: %s" % (meeting.LABELS.get(who, "Them"), text))[-160:])

        def _suggest_toggled(self, on):
            """Smart answers is one setting for the copilot and the assistant."""
            self.c.cfg.s.copilot_smart = on
            self.c.cfg.save()
            if self.c.copilot is not None:
                self.c.copilot.sync_settings()

        # ---------------------------------------------------------------- copilot answers + actions
        def _act(self, action):
            if self.cp is None or self.cp.busy:
                return
            if not self._ready():
                self._bubble("error", "Sign in or add an API key in Settings " + chr(0x203A) + " AI assistant first.")
                return
            self.cp.run_action(action)
            self.refresh_live()

        def _copilot_answer(self, badge, text, question):
            self._drop_empty()
            if question:
                q = question if len(question) <= 140 else question[:137] + ELLIPSIS
                self._bubble("suggest", text, reply=True, header="SUGGESTED ANSWER",
                             sub="They asked: " + chr(0x201C) + q + chr(0x201D))
            else:
                self._bubble("suggest", text, reply=True, header=badge or "COPILOT")
            self.refresh_live()

        def _copilot_failed(self, msg):
            self._bubble("error", msg)
            self.refresh_live()

        # ---------------------------------------------------------------- chat
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
            if not self._ready():
                self.refresh_info()
                return
            jpeg = None
            if self.use_screen.isChecked():
                try:
                    jpeg = self._grab_jpeg()
                except Exception as e:                # noqa: BLE001 - answer without the screen
                    self._bubble("note", "Couldn't capture the screen (%s). Answering without it." % e)
            self._drop_empty()
            self.text.clear()
            self.history.append({"role": "user", "content": q})
            self._bubble("user", q)
            self.waiting = self._bubble("note", "Looking at your screen" + ELLIPSIS if jpeg else "Thinking" + ELLIPSIS)
            self.busy = True
            self.refresh_info()
            msgs = list(self.history[-ai.MAX_TURNS:])
            title, script = self.c.prompter.script_title, self.c.prompter.script_text
            cfg = self.c.cfg.s
            model, extra = cfg.ai_model, {"provider": cfg.ai_provider, "base_url": cfg.ai_base_url,
                                          "max_tokens": cfg.ai_max_tokens,
                                          "context": self.cp._context() if self.transcript is not None else ""}

            def work():
                try:
                    self.relay.done.emit(ai.chat(key, msgs, model, jpeg, title, script, **extra), None)
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
            while self.log_lay.count() > 1:            # keep the stretch at index 0
                it = self.log_lay.takeAt(1)
                if it.widget():
                    it.widget().deleteLater()
            self.waiting = None
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
            s = self.c.store.create("AI: " + (first[:60] or "suggestion"), text)
            self.c.load_script(s["id"], "the AI assistant")

        def done(self, r):
            self._leave(end=True)
            self.clock.stop()
            self.c.assistant = None
            super().done(r)

    return Assistant()
