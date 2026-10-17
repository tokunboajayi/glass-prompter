"""AI assistant window on the computer: chat with any AI, optionally showing it your screen, plus one-click screenshots.

It can also listen to a meeting. Your microphone ("You") and the computer's sound ("Them") are transcribed offline
by the same engine as the meeting copilot (it shares the copilot's live transcript when a meeting is running there).
While it listens:
  * every question you type also sees the conversation;
  * with Auto-suggest on, it offers an answer when someone asks you a question, and follow-up questions after the
    others have talked for a while.

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
from ..listen import MeetingListener
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
    suggested = Signal(str, str, object, object)  # (kind, trigger text, reply | None, error | None)


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
            self.suggesting = False
            self.relay = _Relay()
            self.relay.done.connect(self._answered)
            self.relay.suggested.connect(self._suggested)
            self.listener = None              # our own; None while sharing the copilot's (or not listening)
            self.shared = False               # True: following the copilot's running meeting
            self.transcript = None
            self.trigger = meeting.SuggestionTrigger()
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
            self.suggest_sw = Switch("Auto-suggest")
            self.suggest_sw.setChecked(controller.cfg.s.assistant_suggest)
            self.suggest_sw.setToolTip("While listening: suggest an answer when someone asks you a question, and "
                                       "follow-up questions after they've talked for a while.")
            self.suggest_sw.toggled.connect(self._suggest_toggled)
            r.addWidget(self.suggest_sw)
            r.addStretch(1)
            self.live_pill = label("", "idle")
            r.addWidget(self.live_pill)
            sl.addLayout(r)
            self.heard_lab = label("", "muted")
            self.heard_lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            sl.addWidget(self.heard_lab)
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
            return bool(ai.load_key()) or self.c.cfg.s.ai_provider == "ollama"

        def refresh_info(self):
            s = self.c.cfg.s
            key = ai.load_key()
            ready = self._ready()
            if ready:
                name = ai.provider_name(s.ai_provider, key)
                self.info.setText("%s · %s · answers anything and can see your screen"
                                  % (name, s.ai_model or "best model"))
            else:
                self.info.setText("Add an API key from any AI provider in Settings › AI assistant to start.")
            self.send_btn.setEnabled(ready and not self.busy)

        def refresh_live(self):
            on = self.transcript is not None
            if on:
                t = meeting.fmt_clock(time.time() - self.transcript.started)
                self.live_pill.setText(chr(0x2022) + "  " + ("Copilot " if self.shared else "") + "Live  " + t)
            else:
                self.live_pill.setText("Not listening")
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

        # ---------------------------------------------------------------- listening
        def set_listening(self, on):
            if on:
                cp = self.c.copilot
                if cp is not None and cp.running:
                    self.attach_copilot(cp)
                else:
                    self._start_own()
            else:
                self._stop_all()
            self.refresh_live()

        def _start_own(self):
            s = self.c.cfg.s
            if not MeetingListener.available(s.copilot_model):
                self._bubble("error", MeetingListener.why_unavailable(s.copilot_model))
                self._set_switch(False)
                return
            self.shared = False
            self.transcript = meeting.Transcript()
            self.trigger = meeting.SuggestionTrigger()
            self.listener = MeetingListener()
            self.listener.segment.connect(self._own_segment)
            self.listener.partial.connect(self._partial)
            self.listener.status.connect(lambda st: st == "loading" and self.heard_lab.setText(
                "Loading speech recognition" + ELLIPSIS))
            self.listener.note.connect(lambda m: self._bubble("note", m))
            self.listener.failed.connect(self._listen_failed)
            self.listener.start(s.mic_device, s.copilot_system_audio, s.copilot_model)
            self.heard_lab.setText("Listening" + ELLIPSIS)
            if not s.copilot_consent_seen:
                s.copilot_consent_seen = True
                self.c.cfg.save()
                self._bubble("note", "Tip: let the other people know you're taking notes. In some places "
                                     "transcribing a call needs everyone's consent.")

        def _stop_all(self):
            if self.listener is not None:
                self.listener.stop()
                self.listener.deleteLater()
                self.listener = None
            if self.shared:
                self._detach_copilot()
            self.transcript = None
            self.heard_lab.setText("")

        def _set_switch(self, on):
            self.listen_sw.blockSignals(True)
            self.listen_sw.setChecked(on)
            self.listen_sw.blockSignals(False)
            self.refresh_live()

        def attach_copilot(self, cp):
            """Follow the copilot's running meeting instead of opening the microphone twice."""
            if self.listener is not None:
                self.listener.stop()
                self.listener.deleteLater()
                self.listener = None
            self.shared = True
            self._cp = cp
            self.transcript = cp.transcript
            self.trigger = meeting.SuggestionTrigger()
            cp.listener.segment.connect(self._shared_segment)
            cp.listener.partial.connect(self._partial)
            self.heard_lab.setText("Following the meeting copilot" + ELLIPSIS)
            self.refresh_live()

        def _detach_copilot(self):
            cp = getattr(self, "_cp", None)
            if cp is not None:
                for sig, slot in ((cp.listener.segment, self._shared_segment), (cp.listener.partial, self._partial)):
                    try:
                        sig.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
            self._cp = None
            self.shared = False

        def copilot_ended(self):
            """The copilot's meeting ended while we followed it: keep listening on our own."""
            if self.shared:
                self._detach_copilot()
                self.transcript = None
                if self.listen_sw.isChecked():
                    self._start_own()
                self.refresh_live()

        def _listen_failed(self, msg):
            self._bubble("error", msg)
            self._stop_all()
            self._set_switch(False)

        def _partial(self, who, text):
            if text:
                self.heard_lab.setText(("%s: %s" % (meeting.LABELS.get(who, "Them"), text))[-160:])

        def _own_segment(self, who, text):
            if self.transcript is not None and self.transcript.add(who, text) is not None:
                self._heard(who, text)

        def _shared_segment(self, who, text):
            if self.shared:                      # the copilot already added it to the shared transcript
                self._heard(who, text)

        def _heard(self, who, text):
            self.heard_lab.setText(("%s: %s" % (meeting.LABELS.get(who, "Them"), text))[-160:])
            if not self.suggest_sw.isChecked() or self.suggesting or not self._ready():
                return
            hit = self.trigger.on_segment(who, text, time.time())
            if hit:
                self.suggest(*hit)

        def _suggest_toggled(self, on):
            self.c.cfg.s.assistant_suggest = on
            self.c.cfg.save()

        # ---------------------------------------------------------------- suggestions
        def suggest(self, kind, question=""):
            """Ask for an answer to `question`, or for follow-up questions, from the live conversation."""
            s = self.c.cfg.s
            key = ai.load_key()
            action = "assist" if kind == "answer" else "followups"
            msg = meeting.action_message(action, question)
            ctx = meeting.build_context(s.copilot_mode, s.copilot_modes, self.transcript,
                                        meeting.read_knowledge(s.copilot_files), s.copilot_notes)
            jpeg = None
            if self.use_screen.isChecked() and sys.platform == "win32":     # no window flicker for automatic help
                try:
                    jpeg = self._grab_jpeg()
                except Exception:                           # noqa: BLE001 - suggest without the screen
                    jpeg = None
            self.suggesting = True
            self._drop_empty()
            self.suggest_wait = self._bubble("note", ("They asked a question. Thinking" if kind == "answer" else
                                                      "Thinking of good questions") + ELLIPSIS)

            def work():
                try:
                    reply = ai.chat(key, [{"role": "user", "content": msg}], s.ai_model, jpeg, "", "", web=False,
                                    provider=s.ai_provider, base_url=s.ai_base_url,
                                    max_tokens=meeting.LIVE_TOKENS, context=ctx)
                    self.relay.suggested.emit(kind, question, reply, None)
                except ai.AIError as e:
                    self.relay.suggested.emit(kind, question, None, str(e))
                except Exception as e:                      # noqa: BLE001
                    self.relay.suggested.emit(kind, question, None, "Something went wrong: %s" % e)
            threading.Thread(target=work, name="ai-suggest", daemon=True).start()

        def _suggested(self, kind, question, reply, error):
            self.suggesting = False
            if getattr(self, "suggest_wait", None) is not None:
                self.suggest_wait.deleteLater()
                self.suggest_wait = None
            if not reply:
                self._bubble("error", "Couldn't suggest: %s" % (error or "no answer"))
                return
            if kind == "answer":
                q = question if len(question) <= 140 else question[:137] + ELLIPSIS
                self._bubble("suggest", reply, reply=True, header="SUGGESTED ANSWER",
                             sub="They asked: " + chr(0x201C) + q + chr(0x201D))
            else:
                self._bubble("suggest", reply, reply=True, header="QUESTIONS YOU COULD ASK")

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
                                          "context": meeting.listen_context(self.transcript)}

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
            self.waiting = self.suggest_wait = None
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
            self._stop_all()
            self.clock.stop()
            self.c.assistant = None
            super().done(r)

    return Assistant()
