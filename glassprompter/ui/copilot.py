"""Meeting copilot window: live transcript of the call, one-click AI help, and notes when the meeting ends.

  * Start meeting: transcribes your microphone ("You") and the computer's sound ("Them") offline.
  * Assist (Ctrl+Alt+Enter from any app): the AI reads the conversation (and your screen) and tells you what to say.
  * Quick actions: What to say, Follow-ups, Recap, Fact-check, Explain.
  * Smart answers: when someone asks you a question, an answer appears on its own.
  * End meeting: the AI writes a summary, decisions, action items and a follow-up email, saved in Meeting history.

Layout, top to bottom: status and Start/End; mode and context; the transcript card; Assist and quick actions; the
answer card; a box to ask anything; the three switches. Same cards, switches and type as Settings.

Like every Glass Prompter window it's hidden from screen sharing, so the screenshot the AI sees is what's under it.
"""
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import ai, meeting, paths
from ..listen import MeetingListener, system_audio_supported
from ..platform import MOD
from . import icons
from .glass import Switch
from .theme import ELLIPSIS, T

SMART_GAP = 8.0                       # seconds between automatic suggestions
CHIPS = (("say", "What to say"), ("followups", "Follow-ups"), ("recap", "Recap"), ("factcheck", "Fact-check"),
         ("explain", "Explain"))


class _Relay(QObject):
    done = Signal(str, object, object, bool)       # (kind, reply | None, error | None, saw_screen)


def _btn(text, fn, tip="", **props):
    """A push button with the app's roles: compact, chip, ghost, primary, accent, danger."""
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    for k, v in props.items():
        b.setProperty(k, v)
    if tip:
        b.setToolTip(tip)
        b.setAccessibleDescription(tip)
    b.clicked.connect(fn)
    return b


def _icon_btn(icon, text, fn, tip=""):
    b = _btn(text, fn, tip, ghost=True, compact=True)
    b.setIcon(icons.icon(icon, "#C9CFDD", 16))
    b.setIconSize(QSize(16, 16))
    return b


def _repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


def _ai_ready(cfg):
    return ai.is_ready(cfg.ai_provider)


def _ask(controller, kind, messages, context, jpeg, tokens, web, relay, meeting_id=None):
    """Run one AI request on a worker thread; the answer comes back through `relay`. Notes are saved right here
    on the worker, so they're kept even if the window closed while the AI was writing them."""
    cfg = controller.cfg.s
    key = ai.load_key()
    store = controller.meetings

    def emit(*args):
        try:
            relay.done.emit(*args)
        except RuntimeError:                            # the window (and its relay) is gone; nothing to show
            pass

    def work():
        try:
            reply = ai.chat(key, messages, cfg.ai_model, jpeg, "", "", web=web, provider=cfg.ai_provider,
                            base_url=cfg.ai_base_url, max_tokens=tokens, context=context)
            if kind == "notes" and meeting_id is not None:
                meeting.save_notes(store, meeting_id, reply)
            emit(kind, reply, None, jpeg is not None)
        except ai.AIError as e:
            emit(kind, None, str(e), False)
        except Exception as e:                          # noqa: BLE001
            emit(kind, None, "Something went wrong: %s" % e, False)
    threading.Thread(target=work, name="copilot-" + kind, daemon=True).start()


def _card_header(title, right=None):
    """Section label on the left of a card, an optional widget on the right."""
    from .dialogs import label
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 10, 0, 4)
    h.addWidget(label(title.upper(), "section"))
    h.addStretch(1)
    if right is not None:
        h.addWidget(right)
    return w


def _card(spacing=6):
    c = QFrame()
    c.setProperty("role", "card")
    lay = QVBoxLayout(c)
    lay.setContentsMargins(14, 2, 14, 12)
    lay.setSpacing(spacing)
    return c, lay


def _flat_text(placeholder, px):
    t = QPlainTextEdit()
    t.setReadOnly(True)
    t.setProperty("flat", True)
    t.setPlaceholderText(placeholder)
    t.setStyleSheet("QPlainTextEdit { font-size: %dpx; }" % px)
    t.setFrameShape(QFrame.Shape.NoFrame)
    return t


def transcript_html(tr, limit=200):
    """The live transcript as HTML: a coloured speaker label per line (You aqua, Them violet), newest last."""
    import html
    rows = []
    for s in tr.segments[-limit:]:
        me = s.get("who") == meeting.ME
        rows.append('<p style="margin:0 0 6px 0"><span style="color:%s;font-weight:600">%s</span>'
                    '<span style="color:#8C95AB">&nbsp;&nbsp;%s</span><br>%s</p>'
                    % ("#40E8D0" if me else "#A48BFF", "You" if me else "Them", meeting.fmt_clock(s.get("t", 0)),
                       html.escape(s.get("text", ""))))
    return "".join(rows)


def make_copilot(controller):
    from .dialogs import BaseDialog, label

    class Copilot(BaseDialog):
        # The one meeting engine: the AI assistant listens through it too, and shows every answer it produces.
        answered = Signal(str, str, str)          # (badge, answer, the question that triggered it, or "")
        answer_failed = Signal(str)
        meeting_changed = Signal(bool)            # live?

        def __init__(self):
            super().__init__(None, "Meeting copilot", resizable=True)
            self._pending_q = ""
            self.trigger = meeting.SuggestionTrigger(answer_gap=SMART_GAP)
            self.c = controller
            self.store = controller.meetings
            self.listener = MeetingListener()
            self.listener.segment.connect(self.on_segment)
            self.listener.partial.connect(self.on_partial)
            self.listener.status.connect(self.on_status)
            self.listener.note.connect(lambda m: self.show_note(m))
            self.listener.failed.connect(self.on_failed)
            self.relay = _Relay()
            self.relay.done.connect(self._answered)
            self.transcript = None
            self.meeting_id = None
            self.partials = {}
            self.busy = False
            self.last_smart = 0.0
            self.chat = []                               # follow-up questions typed in this meeting
            self.answers = []                            # [(badge, text)] every answer this session, oldest first
            self.ans_i = -1
            self._full_size = None
            self.resize(580, 780)
            self.setMinimumSize(540, 700)

            root = QVBoxLayout(self)
            root.setContentsMargins(20, 16, 20, 18)
            root.setSpacing(10)

            # status + start/end
            top = QHBoxLayout()
            top.setSpacing(10)
            self.pill = label("", "idle")
            top.addWidget(self.pill)
            self.info = label("", "muted")
            self.info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            top.addWidget(self.info, 1)
            self.start_btn = _btn("Start meeting", self.toggle_meeting, "Start or end the meeting  (%s+M)" % MOD,
                                  primary=True)
            top.addWidget(self.start_btn)
            self.compact_btn = _btn("", self.toggle_compact, "Compact bar  (Ctrl+B)", ghost=True, compact=True)
            self.compact_btn.setFixedWidth(34)
            top.addWidget(self.compact_btn)
            root.addLayout(top)

            # mode + context + history
            row = QHBoxLayout()
            row.setSpacing(6)
            self.mode = QComboBox()
            self.mode.setAccessibleName("Copilot mode")
            self.reload_modes()
            self.mode.currentIndexChanged.connect(self._mode_changed)
            row.addWidget(self.mode, 1)
            row.addWidget(_icon_btn("settings", "Context", self.open_setup,
                                    "Your notes, knowledge files and custom modes"))
            row.addWidget(_icon_btn("history", "History", self.c.open_meetings,
                                    "Past meetings, notes and follow-up emails"))
            self.mode_row = QWidget()
            self.mode_row.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            root.addWidget(self.mode_row)

            # transcript
            card, lay = _card(2)
            lay.addWidget(_card_header("Transcript", label("You = microphone  " + chr(0xB7) + "  Them = computer sound",
                                                          "muted")))
            self.live = QTextBrowser()                     # colour-coded: You in aqua, Them in violet
            self.live.setProperty("flat", True)
            self.live.setFrameShape(QFrame.Shape.NoFrame)
            self.live.setOpenLinks(False)
            self.live.setStyleSheet("QTextBrowser { font-size: 13px; }")
            self.live.setPlaceholderText("The conversation appears here once the meeting starts.")
            self.live.setMinimumHeight(80)
            lay.addWidget(self.live, 1)
            self.partial_lab = label("", "muted")
            self.partial_lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lay.addWidget(self.partial_lab)
            self.transcript_card = card
            root.addWidget(card, 4)

            # actions
            self.assist_btn = _btn("Assist   " + chr(0xB7) + "   %s+Enter" % MOD, lambda: self.run_action("assist"),
                                   "Reads the conversation and your screen and tells you what to say. Works from "
                                   "any app.", accent=True)
            self.assist_btn.setMinimumHeight(40)
            root.addWidget(self.assist_btn)
            chips = QHBoxLayout()
            chips.setSpacing(6)
            self.chip_btns = []
            for aid, name in CHIPS:
                b = _btn(name, lambda _=False, a=aid: self.run_action(a), meeting.ACTIONS[aid][0], chip=True)
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                chips.addWidget(b)
                self.chip_btns.append(b)
            self.chips_row = QWidget()
            self.chips_row.setLayout(chips)
            chips.setContentsMargins(0, 0, 0, 0)
            root.addWidget(self.chips_row)

            # answer
            self.badge = label("", "badge")
            card, lay = _card(4)
            lay.addWidget(_card_header("Answer", self.badge))
            self.answer = _flat_text("Press Assist or a quick action. Answers appear here.", 15)
            self.answer.setMinimumHeight(110)
            self.answer.textChanged.connect(self.c.schedule_publish)    # new answers reach the phone at once
            lay.addWidget(self.answer, 1)
            tools = QHBoxLayout()
            tools.setSpacing(4)
            tools.addWidget(_btn("Copy", self.copy_answer, ghost=True, compact=True))
            tools.addWidget(_btn("Send to prompter", self.answer_to_prompter, "Read the answer on the prompter",
                                 ghost=True, compact=True))
            tools.addStretch(1)
            self.prev_btn = _btn(chr(0x2039), lambda: self.show_answer(self.ans_i - 1), "Earlier answer  (Alt+Left)",
                                 ghost=True, compact=True)
            self.ans_count = label("", "muted")
            self.next_btn = _btn(chr(0x203A), lambda: self.show_answer(self.ans_i + 1), "Later answer  (Alt+Right)",
                                 ghost=True, compact=True)
            for w in (self.prev_btn, self.ans_count, self.next_btn):
                tools.addWidget(w)
            lay.addLayout(tools)
            self.answer_card = card
            root.addWidget(card, 6)

            # ask
            ask = QHBoxLayout()
            ask.setSpacing(6)
            self.ask_box = QLineEdit()
            self.ask_box.setPlaceholderText("Ask about the meeting or your screen" + ELLIPSIS)
            self.ask_box.setAccessibleName("Ask the copilot")
            self.ask_box.returnPressed.connect(self.ask)
            ask.addWidget(self.ask_box, 1)
            self.ask_btn = _btn("Ask", self.ask)
            ask.addWidget(self.ask_btn)
            self.ask_row = QWidget()
            self.ask_row.setLayout(ask)
            ask.setContentsMargins(0, 0, 0, 0)
            root.addWidget(self.ask_row)

            # switches
            opts = QHBoxLayout()
            opts.setSpacing(18)
            self.sys_audio = Switch("Hear the call")
            self.sys_audio.setEnabled(system_audio_supported())
            self.sys_audio.setToolTip("Transcribe the computer's sound (Zoom, Teams, Meet...) as Them."
                                      if system_audio_supported() else
                                      "This system can't share its sound with apps; only your microphone is used.")
            self.sys_audio.toggled.connect(lambda on: self._set("copilot_system_audio", on))
            self.smart = Switch("Smart answers")
            self.smart.setToolTip("When someone asks you a question, a suggested answer appears on its own.")
            self.smart.toggled.connect(lambda on: self._set("copilot_smart", on))
            self.use_screen = Switch("Use my screen")
            self.use_screen.setToolTip("Actions include a screenshot. Glass Prompter windows never appear in it.")
            self.use_screen.toggled.connect(lambda on: self._set("copilot_screen", on))
            for w in (self.sys_audio, self.smart, self.use_screen):
                opts.addWidget(w)
            opts.addStretch(1)
            self.opts_row = QWidget()
            self.opts_row.setLayout(opts)
            opts.setContentsMargins(0, 0, 0, 0)
            root.addWidget(self.opts_row)
            self.sync_settings()
            self._shortcuts()
            self._update_history_nav()
            self.set_compact(bool(getattr(self.c.cfg.s, "copilot_compact", False)), save=False)

            self.clock = QTimer(self, interval=1000, timeout=self.refresh_info)
            self.clock.start()
            self.refresh_info()

        # ---------------------------------------------------------------- settings
        def _set(self, name, value):
            setattr(self.c.cfg.s, name, value)
            self.c.cfg.save()

        def sync_settings(self):
            """Settings can change these too; show the current values whenever the window is brought up."""
            s = self.c.cfg.s
            for sw, on in ((self.sys_audio, s.copilot_system_audio and system_audio_supported()),
                           (self.smart, s.copilot_smart), (self.use_screen, s.copilot_screen)):
                sw.blockSignals(True)
                sw.setChecked(on)
                sw.blockSignals(False)
            self.reload_modes()

        def reload_modes(self):
            s = self.c.cfg.s
            self.mode.blockSignals(True)
            self.mode.clear()
            for mid, name, _prompt in meeting.all_modes(s.copilot_modes):
                self.mode.addItem(name, mid)
            self.mode.setCurrentIndex(max(0, self.mode.findData(s.copilot_mode)))
            self.mode.blockSignals(False)

        def _mode_changed(self, _i):
            self._set("copilot_mode", self.mode.currentData() or meeting.DEFAULT_MODE)

        def open_setup(self):
            SetupDialog(self, self.c).exec()
            self.reload_modes()

        # ---------------------------------------------------------------- meeting
        @property
        def running(self):
            return self.transcript is not None

        def refresh_info(self):
            s = self.c.cfg.s
            if self.running:
                t = meeting.fmt_clock(time.time() - self.transcript.started)
                self.pill.setText(chr(0x2022) + "  Live  " + t)
                self.info.setText("%d words" % self.transcript.words())
                role = "live"
            else:
                self.pill.setText("Ready")
                self.info.setText(("%s %s %s" % (ai.provider_name(s.ai_provider, ai.load_key()).split(" (")[0],
                                                  chr(0xB7), s.ai_model or "best model")) if _ai_ready(s) else
                                  "Sign in or add an AI key in Settings to get answers")
                role = "idle"
            if self.pill.property("role") != role:
                self.pill.setProperty("role", role)
                _repolish(self.pill)
            ready = _ai_ready(s) and not self.busy
            for b in [self.assist_btn, self.ask_btn] + self.chip_btns:
                b.setEnabled(ready)

        def toggle_meeting(self):
            if self.running:
                self.end_meeting()
            else:
                self.start_meeting()

        def _start_style(self, live):
            self.start_btn.setText("End meeting" if live else "Start meeting")
            self.start_btn.setProperty("danger", live)
            self.start_btn.setProperty("primary", not live)
            _repolish(self.start_btn)
            self.c.prompter.set_copilot_live(live)

        def start_meeting(self):
            s = self.c.cfg.s
            if not MeetingListener.available(s.copilot_model):
                self.show_note(MeetingListener.why_unavailable(s.copilot_model))
                return
            if not s.copilot_consent_seen:
                s.copilot_consent_seen = True
                self.c.cfg.save()
                self.show_note("Tip: let the other people know you're taking notes. In some places recording or "
                               "transcribing a call needs everyone's consent.")
            self.transcript = meeting.Transcript()
            self.trigger = meeting.SuggestionTrigger(answer_gap=SMART_GAP)
            self.meeting_id = self.store.create(self.transcript.started, s.copilot_mode)
            self.chat = []
            self.live.clear()
            self.listener.start(s.mic_device, self.sys_audio.isChecked(), s.copilot_model)
            self._start_style(True)
            self.refresh_info()
            self.c.schedule_publish()
            self.meeting_changed.emit(True)

        def end_meeting(self):
            self.listener.stop()
            tr, mid = self.transcript, self.meeting_id
            self.transcript = None
            self.partials = {}
            self.partial_lab.setText("")
            self.meeting_changed.emit(False)
            self._start_style(False)
            self.refresh_info()
            self.c.schedule_publish()
            if tr is None:
                return
            self.store.update(mid, ended=time.time(), transcript=tr.to_json())
            if tr.words() < 15:
                self.show_note("Meeting saved to History. It was too short to write notes.")
                return
            if not _ai_ready(self.c.cfg.s):
                self.show_note("Meeting saved to History. Sign in or add an AI key to get notes and a follow-up email.")
                return
            self.badge.setText("WRITING NOTES" + ELLIPSIS)
            self.answer.setPlainText("Writing your meeting notes and follow-up email" + ELLIPSIS)
            s = self.c.cfg.s
            ctx = meeting.build_context(s.copilot_mode, s.copilot_modes, tr,
                                        meeting.read_knowledge(s.copilot_files), s.copilot_notes)
            _ask(self.c, "notes", [{"role": "user", "content": meeting.NOTES_PROMPT}], ctx, None,
                 meeting.NOTES_TOKENS, False, self.relay, meeting_id=mid)

        def on_status(self, st):
            if st == "loading":
                self.partial_lab.setText("Loading speech recognition" + ELLIPSIS)
            elif st == "listening":
                self.partial_lab.setText("Listening" + ELLIPSIS)
            self.refresh_info()

        def on_failed(self, msg):
            self.show_note(msg)
            if self.running:
                self.end_meeting()

        def on_partial(self, who, text):
            self.partials[who] = text
            shown = ["%s: %s" % (meeting.LABELS[w], t) for w, t in self.partials.items() if t]
            self.partial_lab.setText("   ".join(shown)[-180:] if shown else
                                     ("Listening" + ELLIPSIS if self.running else ""))

        def on_segment(self, who, text):
            if not self.running:
                return
            if self.transcript.add(who, text) is None:
                return
            self._render_live()
            if len(self.transcript.segments) % 8 == 0:   # crash-safe: keep the saved copy close to live
                self.store.update(self.meeting_id, transcript=self.transcript.to_json())
            # Smart answers: an answer when they ask you something, follow-up questions after a long stretch of
            # them talking. Only their lines count. The assistant shows these too, so nothing is asked twice.
            if self.smart.isChecked() and not self.busy and _ai_ready(self.c.cfg.s):
                hit = self.trigger.on_segment(who, text, time.time())
                if hit:
                    self.last_smart = time.time()
                    kind, question = hit
                    if kind == "answer":
                        self.run_action("assist", question=question, auto=True)
                    else:
                        self.run_action("followups", auto=True)

        def _render_live(self):
            self.live.setHtml(transcript_html(self.transcript))
            self.live.moveCursor(QTextCursor.MoveOperation.End)

        # ---------------------------------------------------------------- AI
        def _grab_jpeg(self):
            if not self.use_screen.isChecked():
                return None
            from ..app import grab_screen_jpeg
            hide = sys.platform != "win32"                # Windows already keeps this window out of captures
            try:
                if hide:
                    self.setWindowOpacity(0.0)
                    QApplication.processEvents()
                    time.sleep(0.15)
                return grab_screen_jpeg(self.c.prompter)
            except Exception:                            # noqa: BLE001 - answer without the screen
                return None
            finally:
                if hide:
                    self.setWindowOpacity(1.0)

        def _context(self):
            s = self.c.cfg.s
            return meeting.build_context(s.copilot_mode, s.copilot_modes, self.transcript,
                                         meeting.read_knowledge(s.copilot_files), s.copilot_notes)

        def _set_busy(self, on, what=""):
            self.busy = on
            self.assist_btn.setText(("%s" % what or "Thinking") + ELLIPSIS if on else
                                    "Assist   " + chr(0xB7) + "   %s+Enter" % MOD)
            self.refresh_info()
            self.c.schedule_publish()                     # the phone shows "thinking" too

        def run_action(self, action, question="", auto=False):
            if self.busy:
                return
            if not _ai_ready(self.c.cfg.s):
                self.refresh_info()
                self.show_note("Sign in or add an API key in Settings " + chr(0x203A) +
                               " AI assistant first.")
                return
            jpeg = self._grab_jpeg()
            msg = meeting.action_message(action, question)
            name = meeting.ACTIONS.get(action, meeting.ACTIONS["assist"])[0]
            self._pending_q = question
            self._set_busy(True, "Answering their question" if (auto and question) else name)
            self.badge.setText("")
            _ask(self.c, action, [{"role": "user", "content": msg}], self._context(), jpeg,
                 meeting.LIVE_TOKENS, action == "factcheck", self.relay)

        def ask(self):
            q = self.ask_box.text().strip()
            if not q or self.busy:
                return
            if not _ai_ready(self.c.cfg.s):
                self.show_note("Sign in or add an API key in Settings " + chr(0x203A) +
                               " AI assistant first.")
                return
            self.ask_box.clear()
            self.chat.append({"role": "user", "content": q})
            self._set_busy(True)
            _ask(self.c, "ask", list(self.chat[-ai.MAX_TURNS:]), self._context(), self._grab_jpeg(),
                 meeting.LIVE_TOKENS * 2, True, self.relay)

        def _answered(self, kind, reply, error, saw_screen):
            if kind == "notes":
                if reply:
                    self.add_answer("NOTES " + chr(0xB7) + " SAVED TO HISTORY", reply)
                else:
                    self.show_note("Meeting saved, but the notes failed: %s. Open History to try again." % error)
                return
            self._set_busy(False)
            if kind == "ask":
                if reply:
                    self.chat.append({"role": "assistant", "content": reply})
                elif self.chat:
                    self.chat.pop()
            if reply:
                name = meeting.ACTIONS[kind][0] if kind in meeting.ACTIONS else "Answer"
                self.add_answer((name + (" " + chr(0xB7) + " viewed screen" if saw_screen else "")).upper(), reply)
            else:
                self.show_note(error or "No answer.")
                self._pending_q = ""
                self.answer_failed.emit(error or "No answer.")

        def snapshot(self):
            """What the phone remote shows: live state and the latest answer (never the transcript itself)."""
            return {"live": self.running, "busy": self.busy,
                    "elapsed": meeting.fmt_clock(time.time() - self.transcript.started) if self.running else "",
                    "words": self.transcript.words() if self.running else 0,
                    "badge": self.badge.text().title(), "answer": self.answer.toPlainText()[:4000],
                    "ready": _ai_ready(self.c.cfg.s)}

        # ---------------------------------------------------------------- answer history
        def add_answer(self, badge, text):
            self.answers.append((badge, text))
            self.answers = self.answers[-50:]
            self.show_answer(len(self.answers) - 1)
            question, self._pending_q = self._pending_q, ""
            self.answered.emit(badge, text, question)

        def show_answer(self, i):
            if not self.answers:
                return
            self.ans_i = max(0, min(len(self.answers) - 1, i))
            badge, text = self.answers[self.ans_i]
            self.badge.setText(badge)
            self.answer.setPlainText(text)
            self._update_history_nav()

        def _update_history_nav(self):
            n = len(self.answers)
            for w in (self.prev_btn, self.ans_count, self.next_btn):
                w.setVisible(n > 1)
            self.prev_btn.setEnabled(self.ans_i > 0)
            self.next_btn.setEnabled(0 <= self.ans_i < n - 1)
            self.ans_count.setText("%d of %d" % (self.ans_i + 1, n) if n else "")

        # ---------------------------------------------------------------- compact bar
        def toggle_compact(self):
            self.set_compact(not self.compact)

        def set_compact(self, on, save=True):
            """Compact: a slim bar (status, Start/End, Assist, the latest answer) to sit beside a video call."""
            was = getattr(self, "compact", None)
            self.compact = bool(on)
            for w in (self.mode_row, self.transcript_card, self.chips_row, self.ask_row, self.opts_row):
                w.setVisible(not on)
            self.answer.setMinimumHeight(64 if on else 110)
            self.compact_btn.setIcon(icons.icon("plus" if on else "minus", "#C9CFDD", 14))
            self.compact_btn.setToolTip(("Full view" if on else "Compact bar") + "  (Ctrl+B)")
            if on:
                if was is False:
                    self._full_size = self.size()
                self.setMinimumSize(420, 0)
                self.layout().activate()
                self.resize(max(440, min(self.width(), 520)), self.layout().totalMinimumSize().height() + 60)
            else:
                self.setMinimumSize(540, 700)
                size = self._full_size
                self.resize(size if size is not None else self.size().expandedTo(self.minimumSize()))
            if save:
                self._set("copilot_compact", self.compact)

        # ---------------------------------------------------------------- keyboard
        def _shortcuts(self):
            from PySide6.QtGui import QKeySequence, QShortcut
            keys = [("Ctrl+Return", lambda: self.run_action("assist")), ("Ctrl+Enter", lambda: self.run_action("assist")),
                    ("Ctrl+B", self.toggle_compact), ("Ctrl+L", self._focus_ask),
                    ("Alt+Left", lambda: self.show_answer(self.ans_i - 1)),
                    ("Alt+Right", lambda: self.show_answer(self.ans_i + 1))]
            keys += [("Ctrl+%d" % (i + 1), (lambda a=aid: self.run_action(a))) for i, (aid, _n) in enumerate(CHIPS)]
            self._keys = []
            for seq, fn in keys:
                sc = QShortcut(QKeySequence(seq), self)
                sc.activated.connect(fn)
                self._keys.append(sc)
            for i, b in enumerate(self.chip_btns):
                b.setToolTip("%s  (Ctrl+%d)" % (b.toolTip(), i + 1))
            self.assist_btn.setToolTip(self.assist_btn.toolTip() + "  In this window: Ctrl+Enter.")

        def _focus_ask(self):
            if self.compact:
                self.set_compact(False)
            self.ask_box.setFocus()

        # ---------------------------------------------------------------- output
        def show_note(self, text):
            self.badge.setText("")
            self.answer.setPlainText(text)

        def copy_answer(self):
            QGuiApplication.clipboard().setText(self.answer.toPlainText())
            self.c.prompter.toast("Copied", T.ok)

        def answer_to_prompter(self):
            text = self.answer.toPlainText().strip()
            if text:
                s = self.c.store.create("Copilot: " + (self.badge.text().title() or "answer")[:60], text)
                self.c.load_script(s["id"], "the meeting copilot")

        def done(self, r):
            a = self.c.assistant
            if self.running and a is not None and a.following(self):
                self.hide()                              # the assistant is listening through this meeting
                self.c.prompter.toast("Meeting still running in the AI assistant", T.ok, 3)
                return
            if self.running:
                notes = self.transcript.words() >= 15 and _ai_ready(self.c.cfg.s)
                self.end_meeting()
                if notes:
                    self.c.prompter.toast("Meeting ended " + chr(0xB7) + " notes will be in Meeting history "
                                          "shortly", T.ok, 4)
            self.clock.stop()
            self.c.copilot = None
            super().done(r)

    return Copilot()


# ====================================================================== context
def _setup_dialog():
    from .dialogs import BaseDialog, Card, _section, button, label

    class Setup(BaseDialog):
        """Your context for the copilot: notes about you and your offer, knowledge files, custom modes."""

        def __init__(self, parent, controller):
            super().__init__(parent, "Copilot context", resizable=True)
            self.c = controller
            s = controller.cfg.s
            self.setMinimumWidth(500)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(24, 16, 24, 20)
            outer.setSpacing(0)
            body = QWidget()
            root = QVBoxLayout(body)                     # the cards; scrolls when the screen is short
            root.setContentsMargins(0, 0, 6, 0)
            root.setSpacing(6)

            card = Card()
            card.lay.setContentsMargins(14, 12, 14, 12)
            card.lay.addWidget(label("Who you are, what you offer, prices, goals and limits. The AI treats this as "
                                     "the truth and won't invent anything beyond it.", "muted", True))
            card.lay.addSpacing(6)
            self.notes = QPlainTextEdit(s.copilot_notes)
            self.notes.setAccessibleName("Your notes")
            self.notes.setPlaceholderText("e.g. I'm Sam, account exec at Acme. Pro plan is $49/user/month, "
                                          "annual saves 20%. Goal today: book a pilot.")
            self.notes.setStyleSheet("QPlainTextEdit { font-size: 14px; padding: 10px; }")
            self.notes.setMinimumHeight(72)
            self.notes.setMaximumHeight(150)
            card.lay.addWidget(self.notes)
            _section(root, card, "Your notes")

            card = Card()
            card.lay.setContentsMargins(14, 12, 14, 12)
            card.lay.addWidget(label("Product sheets, agendas, FAQs, CVs (.txt, .md, .docx). Up to about %d,000 "
                                     "characters in total are used." % (meeting.MAX_KNOWLEDGE_CHARS // 1000),
                                     "muted", True))
            card.lay.addSpacing(6)
            self.files = QListWidget()
            self.files.setAccessibleName("Knowledge files")
            self.files.setMinimumHeight(56)
            self.files.setMaximumHeight(120)
            for f in s.copilot_files:
                it = QListWidgetItem(os.path.basename(f))
                it.setToolTip(f)
                it.setData(Qt.ItemDataRole.UserRole, f)
                self.files.addItem(it)
            card.lay.addWidget(self.files)
            fr = QHBoxLayout()
            fr.setContentsMargins(0, 6, 0, 0)
            fr.addWidget(_btn("Add files" + ELLIPSIS, self.add_files, compact=True))
            fr.addWidget(_btn("Remove", self.remove_file, compact=True))
            fr.addStretch(1)
            card.lay.addLayout(fr)
            _section(root, card, "Knowledge files")

            card = Card()
            card.lay.setContentsMargins(14, 12, 14, 12)
            card.lay.addWidget(label("Name a mode and say how the AI should help, e.g. Investor pitch: answer like "
                                     "a founder and keep numbers to my notes.", "muted", True))
            card.lay.addSpacing(6)
            mr = QHBoxLayout()
            mr.setSpacing(6)
            self.mode_pick = QComboBox()
            self.mode_pick.setAccessibleName("Custom mode")
            self.mode_pick.addItem("New mode", "")
            for m in meeting.custom_modes(s.copilot_modes):
                self.mode_pick.addItem(m["name"], m["name"])
            self.mode_pick.currentIndexChanged.connect(self.pick_mode)
            mr.addWidget(self.mode_pick, 1)
            self.mode_name = QLineEdit()
            self.mode_name.setPlaceholderText("Mode name")
            self.mode_name.setAccessibleName("Mode name")
            mr.addWidget(self.mode_name, 1)
            card.lay.addLayout(mr)
            card.lay.addSpacing(6)
            self.mode_prompt = QPlainTextEdit()
            self.mode_prompt.setAccessibleName("How the AI should help in this mode")
            self.mode_prompt.setPlaceholderText("How should the AI help in this mode?")
            self.mode_prompt.setStyleSheet("QPlainTextEdit { font-size: 14px; padding: 10px; }")
            self.mode_prompt.setMinimumHeight(60)
            self.mode_prompt.setMaximumHeight(110)
            card.lay.addWidget(self.mode_prompt)
            mb = QHBoxLayout()
            mb.setContentsMargins(0, 6, 0, 0)
            mb.addWidget(_btn("Save mode", self.save_mode, compact=True))
            mb.addWidget(_btn("Delete mode", self.delete_mode, compact=True, danger=True))
            mb.addStretch(1)
            card.lay.addLayout(mb)
            _section(root, card, "Custom modes")

            speech = paths.speech_models()
            self.speech = None
            if len(speech) > 1:
                card = Card()
                self.speech = QComboBox()
                self.speech.setAccessibleName("Speech language model")
                self.speech.addItem("Default (English)", "")
                for name in speech:
                    self.speech.addItem(name, name)
                self.speech.setCurrentIndex(max(0, self.speech.findData(s.copilot_model)))
                card.row("Language", self.speech, "Speech models in the data folder's models folder.")
                _section(root, card, "Speech")

            root.addStretch(1)
            self.area = QScrollArea()
            self.area.setWidgetResizable(True)
            self.area.setFrameShape(QFrame.Shape.NoFrame)
            self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            self.area.setWidget(body)
            outer.addWidget(self.area, 1)
            row = QHBoxLayout()
            row.setContentsMargins(0, 10, 0, 0)
            row.addStretch(1)
            row.addWidget(button("Done", self.save, primary=True))
            outer.addLayout(row)
            self.resize(580, 760)
            self.setMinimumHeight(420)

        def showEvent(self, e):
            super().showEvent(e)
            body = self.area.widget()                    # tall enough for every card, unless the screen isn't
            want = body.heightForWidth(self.area.viewport().width()) + (self.height() - self.area.height())
            screen = self.screen().availableGeometry().height() if self.screen() else want
            self.resize(self.width(), max(480, min(want, screen - 40)))

        def add_files(self):
            files, _ = QFileDialog.getOpenFileNames(self, "Add knowledge files", paths.documents_dir(),
                                                    "Documents (*.txt *.md *.docx)")
            have = {self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
            for f in files:
                f = os.path.normpath(f)
                if f not in have:
                    it = QListWidgetItem(os.path.basename(f))
                    it.setToolTip(f)
                    it.setData(Qt.ItemDataRole.UserRole, f)
                    self.files.addItem(it)

        def remove_file(self):
            for it in self.files.selectedItems():
                self.files.takeItem(self.files.row(it))

        def _modes(self):
            return meeting.custom_modes(self.c.cfg.s.copilot_modes)

        def pick_mode(self, _i):
            name = self.mode_pick.currentData() or ""
            m = next((m for m in self._modes() if m["name"] == name), None)
            self.mode_name.setText(m["name"] if m else "")
            self.mode_prompt.setPlainText(m["prompt"] if m else "")

        def save_mode(self):
            name, prompt = self.mode_name.text().strip(), self.mode_prompt.toPlainText().strip()
            if not name or not prompt:
                return
            modes = [m for m in self._modes() if m["name"] != name] + [{"name": name, "prompt": prompt}]
            self.c.cfg.s.copilot_modes = modes
            self.c.cfg.s.copilot_mode = "custom:" + name
            self.c.cfg.save()
            if self.mode_pick.findData(name) < 0:
                self.mode_pick.addItem(name, name)
            self.c.prompter.toast("Mode saved: " + name, T.ok)

        def delete_mode(self):
            name = self.mode_pick.currentData() or ""
            if not name:
                return
            self.c.cfg.s.copilot_modes = [m for m in self._modes() if m["name"] != name]
            if self.c.cfg.s.copilot_mode == "custom:" + name:
                self.c.cfg.s.copilot_mode = meeting.DEFAULT_MODE
            self.c.cfg.save()
            self.mode_pick.removeItem(self.mode_pick.currentIndex())

        def save(self):
            s = self.c.cfg.s
            s.copilot_notes = self.notes.toPlainText().strip()
            s.copilot_files = [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]
            if self.speech is not None:
                s.copilot_model = self.speech.currentData() or ""
            self.c.cfg.save()
            self.accept()

    return Setup


def SetupDialog(parent, controller):              # noqa: N802 - built lazily, like the other copilot windows
    return _setup_dialog()(parent, controller)


# ====================================================================== history
_DOC_CSS = ("h1 { font-size: 20px; } h2 { font-size: 15px; color: #8C95AB; margin-top: 18px; } "
            "h3 { font-size: 13px; color: #8C95AB; margin-top: 14px; } "
            "p, li { color: #E4E8F2; line-height: 140%; } em { color: #A0A8BC; } strong { color: #40E8D0; }")


def make_meetings(controller):
    from .dialogs import BaseDialog, label

    class Meetings(BaseDialog):
        def __init__(self):
            super().__init__(None, "Meeting history", resizable=True)
            self.c = controller
            self.store = controller.meetings
            self.current = None
            self.relay = _Relay()
            self.relay.done.connect(self._renotes)
            self.resize(900, 640)
            self.setMinimumSize(720, 480)
            root = QHBoxLayout(self)
            root.setContentsMargins(20, 16, 20, 18)
            root.setSpacing(14)

            left = QVBoxLayout()
            left.setSpacing(8)
            self.search = QLineEdit()
            self.search.setPlaceholderText("Search titles, notes and transcripts" + ELLIPSIS)
            self.search.setAccessibleName("Search meetings")
            self.search.textChanged.connect(self.refresh)
            left.addWidget(self.search)
            self.list = QListWidget()
            self.list.setAccessibleName("Meetings")
            self.list.currentItemChanged.connect(self.show_item)
            left.addWidget(self.list, 1)
            root.addLayout(left, 2)

            right = QVBoxLayout()
            right.setSpacing(6)
            self.title = label("", "title", True)
            right.addWidget(self.title)
            self.meta = label("", "muted", True)
            right.addWidget(self.meta)
            card, lay = _card()
            lay.setContentsMargins(6, 6, 6, 6)
            self.view = QTextBrowser()
            self.view.setProperty("flat", True)
            self.view.setFrameShape(QFrame.Shape.NoFrame)
            self.view.setOpenExternalLinks(False)
            self.view.document().setDefaultStyleSheet(_DOC_CSS)
            lay.addWidget(self.view)
            right.addWidget(card, 1)
            tools = QHBoxLayout()
            tools.setSpacing(6)
            for text, fn, tip in (("Copy notes", self.copy_notes, ""), ("Copy email", self.copy_email,
                                                                        "Copy the follow-up email"),
                                  ("Export", self.export, "Save as a Markdown file"),
                                  ("To prompter", self.to_prompter, "Read these notes on the prompter"),
                                  ("Rewrite notes", self.rewrite, "Ask the AI to write the notes again")):
                tools.addWidget(_btn(text, fn, tip, compact=True))
            tools.addStretch(1)
            tools.addWidget(_btn("Delete", self.delete, compact=True, danger=True))
            right.addLayout(tools)
            root.addLayout(right, 5)
            self.refresh()

        def refresh(self):
            keep = self.current["id"] if self.current else None
            self.list.blockSignals(True)
            self.list.clear()
            row = 0
            for i, m in enumerate(self.store.list(self.search.text().strip() or None)):
                when = time.strftime("%d %b %Y, %H:%M", time.localtime(m["started"]))
                it = QListWidgetItem("%s\n%s  %s  %d words" % (m["title"], when, chr(0xB7), m["words"]))
                it.setData(Qt.ItemDataRole.UserRole, m["id"])
                self.list.addItem(it)
                if m["id"] == keep:
                    row = i
            self.list.blockSignals(False)
            if self.list.count():
                self.list.setCurrentRow(row)
                self.show_item(self.list.currentItem())
            else:
                self.current = None
                self.title.setText("No meetings yet" if not self.search.text().strip() else "Nothing found")
                self.meta.setText("")
                self.view.setMarkdown("Open the meeting copilot (**%s+M** from any app) and start a meeting. Its "
                                      "transcript, notes and follow-up email are kept here." % MOD)

        def show_item(self, it, _prev=None):
            if it is None:
                return
            self.current = self.store.get(it.data(Qt.ItemDataRole.UserRole))
            if not self.current:
                return
            m = self.current
            self.title.setText(m["title"])
            dur = meeting.fmt_clock((m.get("ended") or m["started"]) - m["started"])
            mode = meeting.mode_name(m.get("mode") or meeting.DEFAULT_MODE, self.c.cfg.s.copilot_modes)
            self.meta.setText("%s  %s  %s  %s  %d words  %s  %s" % (
                time.strftime("%A %d %B %Y, %H:%M", time.localtime(m["started"])), chr(0xB7), dur, chr(0xB7),
                m["words"], chr(0xB7), mode))
            body = meeting.to_markdown(m).split("\n", 3)[-1]          # title and date are shown above
            body = body.replace("## Transcript", "### Transcript")     # same weight as the notes headings
            self.view.setMarkdown(body if body.strip() else "_Nothing was transcribed._")

        def copy_notes(self):
            if self.current:
                QGuiApplication.clipboard().setText(self.current.get("notes") or meeting.to_markdown(self.current))
                self.c.prompter.toast("Notes copied", T.ok)

        def copy_email(self):
            if self.current and self.current.get("email"):
                QGuiApplication.clipboard().setText(self.current["email"])
                self.c.prompter.toast("Follow-up email copied", T.ok)
            elif self.current:
                self.c.prompter.toast("This meeting has no follow-up email yet. Try Rewrite notes.", T.bad, 4)

        def export(self):
            if not self.current:
                return
            from ..scripts import safe_filename
            name = safe_filename(self.current["title"]) + ".md"
            path, _ = QFileDialog.getSaveFileName(self, "Export meeting", os.path.join(paths.documents_dir(), name),
                                                  "Markdown (*.md)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(meeting.to_markdown(self.current))
                self.c.prompter.toast("Exported", T.ok)

        def to_prompter(self):
            if self.current:
                s = self.c.store.create(self.current["title"][:80], meeting.to_markdown(self.current))
                self.c.load_script(s["id"], "meeting history")

        def rewrite(self):
            m = self.current
            if not m or not m.get("segments"):
                return
            if not _ai_ready(self.c.cfg.s):
                self.c.prompter.toast("Sign in or add an AI key in Settings " + chr(0x203A) + " AI assistant first.", T.bad, 4)
                return
            s = self.c.cfg.s
            tr = meeting.Transcript(m["segments"], m["started"])
            ctx = meeting.build_context(m.get("mode") or s.copilot_mode, s.copilot_modes, tr,
                                        meeting.read_knowledge(s.copilot_files), s.copilot_notes)
            self.view.setMarkdown("_Writing meeting notes" + ELLIPSIS + "_")
            _ask(self.c, "notes", [{"role": "user", "content": meeting.NOTES_PROMPT}], ctx, None,
                 meeting.NOTES_TOKENS, False, self.relay, meeting_id=m["id"])

        def _renotes(self, _kind, reply, error, _saw):
            if reply:
                self.refresh()
            elif error:
                self.view.setMarkdown("Couldn't write the notes: %s" % error)

        def delete(self):
            if self.current and self.confirm("Delete meeting", "Delete \"%s\" and its transcript?"
                                             % self.current["title"], "Delete"):
                self.store.delete(self.current["id"])
                self.current = None
                self.refresh()

        def done(self, r):
            self.c.meetings_window = None
            super().done(r)

    return Meetings()
