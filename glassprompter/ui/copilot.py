"""Meeting copilot window: live transcript of the call, one-click AI help, and notes when the meeting ends.

  * Start meeting: transcribes your microphone ("You") and the computer's sound ("Them") offline.
  * Assist (Ctrl+Alt+Enter from any app): the AI reads the conversation (and your screen) and tells you what to say.
  * Quick actions: What should I say?, Follow-up questions, Recap, Fact-check, Explain.
  * Smart mode: when someone asks you a question, an answer appears on its own.
  * End meeting: the AI writes a summary, decisions, action items and a follow-up email, saved in Meeting history.

Like every Glass Prompter window it's hidden from screen sharing, so the screenshot the AI sees is what's under it.
"""
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout)

from .. import ai, meeting, paths
from ..listen import MeetingListener, system_audio_supported
from ..platform import MOD
from .theme import T

SMART_GAP = 8.0                       # seconds between automatic suggestions


class _Relay(QObject):
    done = Signal(str, object, object, bool)       # (kind, reply | None, error | None, saw_screen)


def _small(text, fn, tip=""):
    b = QPushButton(text)
    b.setProperty("compact", True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    b.clicked.connect(fn)
    return b


def _ai_ready(cfg):
    return bool(ai.load_key()) or cfg.ai_provider == "ollama"


def _ask(controller, kind, messages, context, jpeg, tokens, web, relay):
    """Run one AI request on a worker thread; the answer comes back through `relay`."""
    cfg = controller.cfg.s
    key = ai.load_key()

    def work():
        try:
            reply = ai.chat(key, messages, cfg.ai_model, jpeg, "", "", web=web, provider=cfg.ai_provider,
                            base_url=cfg.ai_base_url, max_tokens=tokens, context=context)
            relay.done.emit(kind, reply, None, jpeg is not None)
        except ai.AIError as e:
            relay.done.emit(kind, None, str(e), False)
        except Exception as e:                          # noqa: BLE001
            relay.done.emit(kind, None, "Something went wrong: %s" % e, False)
    threading.Thread(target=work, name="copilot-" + kind, daemon=True).start()


def make_copilot(controller):
    from .dialogs import BaseDialog, button, label

    class Copilot(BaseDialog):
        def __init__(self):
            super().__init__(None, "Meeting copilot", resizable=True)
            self.c = controller
            s = controller.cfg.s
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
            self.resize(600, 760)
            self.setMinimumSize(460, 560)

            root = QVBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(10)

            top = QHBoxLayout()
            self.start_btn = button("Start meeting", self.toggle_meeting, primary=True)
            top.addWidget(self.start_btn)
            self.mode = QComboBox()
            self.reload_modes()
            self.mode.currentIndexChanged.connect(self._mode_changed)
            top.addWidget(self.mode, 1)
            top.addWidget(_small("Context" + "…", self.open_setup, "Your notes, knowledge files and custom modes"))
            top.addWidget(_small("History", self.c.open_meetings, "Past meetings, notes and follow-up emails"))
            root.addLayout(top)

            self.info = label("", "muted", True)
            root.addWidget(self.info)

            opts = QHBoxLayout()
            self.sys_audio = QCheckBox("Hear the other side")
            self.sys_audio.setChecked(s.copilot_system_audio and system_audio_supported())
            self.sys_audio.setEnabled(system_audio_supported())
            self.sys_audio.setToolTip("Transcribe the computer's sound (Zoom, Teams, Meet...) as 'Them'. "
                                      "Your microphone is 'You'." if system_audio_supported() else
                                      "This system can't share its sound with apps; only your microphone is used.")
            self.sys_audio.toggled.connect(lambda on: self._set("copilot_system_audio", on))
            self.smart = QCheckBox("Smart answers")
            self.smart.setChecked(s.copilot_smart)
            self.smart.setToolTip("When someone asks you a question, a suggested answer appears on its own.")
            self.smart.toggled.connect(lambda on: self._set("copilot_smart", on))
            self.use_screen = QCheckBox("Use my screen")
            self.use_screen.setChecked(s.copilot_screen)
            self.use_screen.setToolTip("Actions include a screenshot. Glass Prompter windows never appear in it.")
            self.use_screen.toggled.connect(lambda on: self._set("copilot_screen", on))
            for w in (self.sys_audio, self.smart, self.use_screen):
                opts.addWidget(w)
            opts.addStretch(1)
            root.addLayout(opts)

            self.live = QPlainTextEdit()
            self.live.setReadOnly(True)
            self.live.setPlaceholderText("The live transcript appears here once the meeting starts.")
            self.live.setStyleSheet("QPlainTextEdit { font-size: 13px; padding: 10px; }")
            root.addWidget(self.live, 2)
            self.partial_lab = label("", "muted", True)
            root.addWidget(self.partial_lab)

            grid = QGridLayout()
            grid.setSpacing(6)
            acts = list(meeting.ACTIONS.items())
            for i, (aid, (name, _prompt)) in enumerate(acts):
                tip = "%s+Enter from any app" % MOD if aid == "assist" else ""
                b = _small(name, lambda _=False, a=aid: self.run_action(a), tip)
                if aid == "assist":
                    b.setProperty("compact", False)
                    b.setProperty("primary", True)
                grid.addWidget(b, i // 3, i % 3)
            root.addLayout(grid)

            self.badge = label("", "muted")
            root.addWidget(self.badge)
            self.answer = QPlainTextEdit()
            self.answer.setReadOnly(True)
            self.answer.setPlaceholderText("Press Assist (%s+Enter) or a quick action. Answers appear here." % MOD)
            self.answer.setStyleSheet("QPlainTextEdit { font-size: 15px; padding: 12px; }")
            root.addWidget(self.answer, 3)

            tools = QHBoxLayout()
            tools.addWidget(_small("Copy", self.copy_answer))
            tools.addWidget(_small("Send to prompter", self.answer_to_prompter))
            tools.addStretch(1)
            exit_btn = _small("Exit", self.exit, "Close the copilot. A running meeting is ended and its notes are "
                                                 "still written and saved to History.")
            exit_btn.setProperty("danger", True)
            tools.addWidget(exit_btn)
            root.addLayout(tools)

            ask = QHBoxLayout()
            self.ask_box = QLineEdit()
            self.ask_box.setPlaceholderText("Ask about the meeting or your screen" + "…")
            self.ask_box.returnPressed.connect(self.ask)
            ask.addWidget(self.ask_box, 1)
            ask.addWidget(button("Ask", self.ask))
            root.addLayout(ask)

            self.clock = QTimer(self, interval=1000, timeout=self.refresh_info)
            self.clock.start()
            self.refresh_info()

        # ---------------------------------------------------------------- settings
        def _set(self, name, value):
            setattr(self.c.cfg.s, name, value)
            self.c.cfg.save()

        def reload_modes(self):
            s = self.c.cfg.s
            self.mode.blockSignals(True)
            self.mode.clear()
            for mid, name, _prompt in meeting.all_modes(s.copilot_modes):
                self.mode.addItem(name, mid)
            i = self.mode.findData(s.copilot_mode)
            self.mode.setCurrentIndex(max(0, i))
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
            if not _ai_ready(s):
                text = "Add an AI key in Settings › AI assistant to get suggestions. The transcript works without one."
            elif self.running:
                t = meeting.fmt_clock(time.time() - self.transcript.started)
                text = "25cf Live %s · %d words · %s" % (t, self.transcript.words(),
                                                         "listening" if self.listener.listening else "paused")
            else:
                text = "%s · %s. Start the meeting, then press Assist whenever you need help." % (
                    ai.provider_name(s.ai_provider, ai.load_key()), s.ai_model or "best model")
            self.info.setText(text)

        def toggle_meeting(self):
            if self.running:
                self.end_meeting()
            else:
                self.start_meeting()

        def start_meeting(self):
            s = self.c.cfg.s
            if not s.copilot_consent_seen:
                s.copilot_consent_seen = True
                self.c.cfg.save()
                self.show_note("Tip: let the other people know you're taking notes. In some places recording or "
                               "transcribing a call needs everyone's consent.")
            if not MeetingListener.available(s.copilot_model):
                self.show_note(MeetingListener.why_unavailable(s.copilot_model))
                return
            self.transcript = meeting.Transcript()
            self.meeting_id = self.store.create(self.transcript.started, s.copilot_mode)
            self.chat = []
            self.live.clear()
            self.listener.start(s.mic_device, self.sys_audio.isChecked(), s.copilot_model)
            self.start_btn.setText("End meeting")
            self.start_btn.setProperty("danger", True)
            self.start_btn.setProperty("primary", False)
            self._repolish(self.start_btn)
            self.refresh_info()

        def end_meeting(self):
            self.listener.stop()
            tr, mid = self.transcript, self.meeting_id
            self.transcript = None
            self.start_btn.setText("Start meeting")
            self.start_btn.setProperty("danger", False)
            self.start_btn.setProperty("primary", True)
            self._repolish(self.start_btn)
            self.refresh_info()
            if tr is None:
                return
            self.store.update(mid, ended=time.time(), transcript=tr.to_json())
            if tr.words() < 15:
                self.show_note("Meeting saved to History. It was too short to write notes.")
                return
            if not _ai_ready(self.c.cfg.s):
                self.show_note("Meeting saved to History. Add an AI key to get notes and a follow-up email.")
                return
            self.write_notes(mid, tr)

        def write_notes(self, mid, tr):
            self.notes_for = mid
            self.badge.setText("Writing meeting notes" + "…")
            s = self.c.cfg.s
            ctx = meeting.build_context(s.copilot_mode, s.copilot_modes, tr,
                                        meeting.read_knowledge(s.copilot_files), s.copilot_notes)
            _ask(self.c, "notes", [{"role": "user", "content": meeting.NOTES_PROMPT}], ctx, None,
                 meeting.NOTES_TOKENS, False, self.relay)

        @staticmethod
        def _repolish(w):
            w.style().unpolish(w)
            w.style().polish(w)

        def on_status(self, st):
            if st == "loading":
                self.partial_lab.setText("Loading speech recognition" + "…")
            elif st == "listening":
                self.partial_lab.setText("Listening" + "…")
            self.refresh_info()

        def on_failed(self, msg):
            self.show_note(msg)
            if self.running:
                self.end_meeting()

        def on_partial(self, who, text):
            self.partials[who] = text
            shown = ["%s: %s" % (meeting.LABELS[w], t) for w, t in self.partials.items() if t]
            self.partial_lab.setText("   ".join(shown)[-220:] if shown else
                                     ("Listening" + "…" if self.running else ""))

        def on_segment(self, who, text):
            if not self.running:
                return
            seg = self.transcript.add(who, text)
            if seg is None:
                return
            self._render_live()
            if len(self.transcript.segments) % 8 == 0:   # crash-safe: keep the saved copy close to live
                self.store.update(self.meeting_id, transcript=self.transcript.to_json())
            if (who == meeting.THEM and self.smart.isChecked() and meeting.is_question(text) and not self.busy
                    and time.time() - self.last_smart > SMART_GAP and _ai_ready(self.c.cfg.s)):
                self.last_smart = time.time()
                self.run_action("assist", question=text, auto=True)

        def _render_live(self):
            self.live.setPlainText(self.transcript.render(limit=12000))
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

        def run_action(self, action, question="", auto=False):
            if self.busy:
                return
            if not _ai_ready(self.c.cfg.s):
                self.refresh_info()
                self.show_note("Add an API key from any AI provider in Settings › AI assistant first.")
                return
            jpeg = self._grab_jpeg()
            msg = meeting.action_message(action, question)
            self.busy = True
            name = meeting.ACTIONS.get(action, meeting.ACTIONS["assist"])[0]
            self.badge.setText(("Someone asked a question · thinking" if auto else name + " · thinking") + "…")
            web = action == "factcheck"
            _ask(self.c, action, [{"role": "user", "content": msg}], self._context(), jpeg,
                 meeting.LIVE_TOKENS, web, self.relay)

        def ask(self):
            q = self.ask_box.text().strip()
            if not q or self.busy:
                return
            if not _ai_ready(self.c.cfg.s):
                self.show_note("Add an API key from any AI provider in Settings › AI assistant first.")
                return
            self.ask_box.clear()
            self.chat.append({"role": "user", "content": q})
            self.busy = True
            self.badge.setText("Thinking" + "…")
            _ask(self.c, "ask", list(self.chat[-ai.MAX_TURNS:]), self._context(), self._grab_jpeg(),
                 meeting.LIVE_TOKENS * 2, True, self.relay)

        def _answered(self, kind, reply, error, saw_screen):
            if kind == "notes":
                return self._notes_done(reply, error)
            self.busy = False
            if kind == "ask":
                if reply:
                    self.chat.append({"role": "assistant", "content": reply})
                elif self.chat:
                    self.chat.pop()
            if reply:
                name = meeting.ACTIONS[kind][0] if kind in meeting.ACTIONS else "Answer"
                self.badge.setText(name + (" · viewed screen" if saw_screen else ""))
                self.answer.setPlainText(reply)
            else:
                self.badge.setText("")
                self.show_note(error or "No answer.")

        def _notes_done(self, reply, error):
            mid = getattr(self, "notes_for", None)
            if not reply:
                self.badge.setText("")
                self.show_note("Meeting saved, but the notes failed: %s. Open History to try again." % error)
                return
            parsed = meeting.parse_notes(reply)
            title = parsed.get("TITLE", "").strip().strip("\"'").splitlines()[0][:80] if parsed.get("TITLE") else ""
            fields = {"notes": reply, "email": parsed.get("FOLLOW-UP EMAIL", "")}
            if title:
                fields["title"] = title
            self.store.update(mid, **fields)
            self.badge.setText("Meeting notes · saved to History")
            self.answer.setPlainText(reply)

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
                s = self.c.store.create("Copilot: " + (self.badge.text() or "answer")[:60], text)
                self.c.load_script(s["id"], "the meeting copilot")

        def exit(self):
            if self.running and self.transcript.words() >= 15 and _ai_ready(self.c.cfg.s):
                self.c.prompter.toast("Meeting ended · notes will be in Meeting history shortly", T.ok, 4)
            self.done(0)

        def done(self, r):
            if self.running:
                self.end_meeting()
            self.clock.stop()
            self.c.copilot = None
            super().done(r)

    return Copilot()


# ====================================================================== setup
def _setup_dialog():
    from .dialogs import BaseDialog, button, label

    class Setup(BaseDialog):
        """Your context for the copilot: notes about you and your offer, knowledge files, custom modes."""

        def __init__(self, parent, controller):
            super().__init__(parent, "Copilot context", resizable=True)
            self.c = controller
            s = controller.cfg.s
            self.resize(560, 680)
            root = QVBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(8)

            root.addWidget(label("Your notes", "h2"))
            root.addWidget(label("Who you are, what you offer, prices, goals and limits. The AI treats this as the "
                                 "truth and won't invent anything beyond it.", "muted", True))
            self.notes = QPlainTextEdit(s.copilot_notes)
            self.notes.setPlaceholderText("e.g. I'm Sam, account exec at Acme. Pro plan is $49/user/month, "
                                          "annual saves 20%. Goal today: book a pilot.")
            root.addWidget(self.notes, 2)

            root.addWidget(label("Knowledge files", "h2"))
            root.addWidget(label("Product sheets, agendas, FAQs, CVs (.txt, .md, .docx). About %d,000 characters "
                                 "in total are used." % (meeting.MAX_KNOWLEDGE_CHARS // 1000), "muted", True))
            self.files = QListWidget()
            for f in s.copilot_files:
                self.files.addItem(QListWidgetItem(f))
            root.addWidget(self.files, 1)
            fr = QHBoxLayout()
            fr.addWidget(_small("Add files" + "…", self.add_files))
            fr.addWidget(_small("Remove", self.remove_file))
            fr.addStretch(1)
            root.addLayout(fr)

            root.addWidget(label("Custom mode", "h2"))
            root.addWidget(label("Name a mode and say how the AI should help (e.g. 'Investor pitch: answer like a "
                                 "founder, keep numbers from my notes').", "muted", True))
            mr = QHBoxLayout()
            self.mode_pick = QComboBox()
            self.mode_pick.addItem("New mode", "")
            for m in meeting.custom_modes(s.copilot_modes):
                self.mode_pick.addItem(m["name"], m["name"])
            self.mode_pick.currentIndexChanged.connect(self.pick_mode)
            mr.addWidget(self.mode_pick, 1)
            self.mode_name = QLineEdit()
            self.mode_name.setPlaceholderText("Mode name")
            mr.addWidget(self.mode_name, 1)
            root.addLayout(mr)
            self.mode_prompt = QPlainTextEdit()
            self.mode_prompt.setPlaceholderText("How should the AI help in this mode?")
            root.addWidget(self.mode_prompt, 1)
            mb = QHBoxLayout()
            mb.addWidget(_small("Save mode", self.save_mode))
            mb.addWidget(_small("Delete mode", self.delete_mode))
            mb.addStretch(1)
            root.addLayout(mb)

            speech = paths.speech_models()
            if len(speech) > 1:
                sr = QHBoxLayout()
                sr.addWidget(label("Speech language model"))
                self.speech = QComboBox()
                self.speech.addItem("Default (English)", "")
                for name in speech:
                    self.speech.addItem(name, name)
                self.speech.setCurrentIndex(max(0, self.speech.findData(s.copilot_model)))
                sr.addWidget(self.speech, 1)
                root.addLayout(sr)
            else:
                self.speech = None

            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(button("Done", self.save, primary=True))
            root.addLayout(row)

        def add_files(self):
            files, _ = QFileDialog.getOpenFileNames(self, "Add knowledge files", paths.documents_dir(),
                                                    "Documents (*.txt *.md *.docx)")
            have = {self.files.item(i).text() for i in range(self.files.count())}
            for f in files:
                f = os.path.normpath(f)
                if f not in have:
                    self.files.addItem(QListWidgetItem(f))

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
            s.copilot_files = [self.files.item(i).text() for i in range(self.files.count())]
            if self.speech is not None:
                s.copilot_model = self.speech.currentData() or ""
            self.c.cfg.save()
            self.accept()

    return Setup


def SetupDialog(parent, controller):              # noqa: N802 - built lazily, like the other copilot windows
    return _setup_dialog()(parent, controller)


# ====================================================================== history
def make_meetings(controller):
    from .dialogs import BaseDialog, button, label

    class Meetings(BaseDialog):
        def __init__(self):
            super().__init__(None, "Meeting history", resizable=True)
            self.c = controller
            self.store = controller.meetings
            self.current = None
            self.relay = _Relay()
            self.relay.done.connect(self._renotes)
            self.resize(860, 620)
            root = QHBoxLayout(self)
            root.setContentsMargins(20, 18, 20, 18)
            root.setSpacing(12)

            left = QVBoxLayout()
            self.search = QLineEdit()
            self.search.setPlaceholderText("Search meetings" + "…")
            self.search.textChanged.connect(self.refresh)
            left.addWidget(self.search)
            self.list = QListWidget()
            self.list.currentItemChanged.connect(self.show_item)
            left.addWidget(self.list, 1)
            root.addLayout(left, 2)

            right = QVBoxLayout()
            self.title = label("", "h2", True)
            right.addWidget(self.title)
            self.view = QPlainTextEdit()
            self.view.setReadOnly(True)
            self.view.setStyleSheet("QPlainTextEdit { font-size: 14px; padding: 12px; }")
            right.addWidget(self.view, 1)
            tools = QHBoxLayout()
            for text, fn in (("Copy notes", self.copy_notes), ("Copy email", self.copy_email),
                             ("Export", self.export), ("To prompter", self.to_prompter),
                             ("Rewrite notes", self.rewrite)):
                tools.addWidget(_small(text, fn))
            tools.addStretch(1)
            tools.addWidget(button("Delete", self.delete, danger=True))
            right.addLayout(tools)
            root.addLayout(right, 5)
            self.refresh()

        def refresh(self):
            self.list.clear()
            for m in self.store.list(self.search.text().strip() or None):
                when = time.strftime("%d %b %Y, %H:%M", time.localtime(m["started"]))
                it = QListWidgetItem("%s\n%s · %d words" % (m["title"], when, m["words"]))
                it.setData(Qt.ItemDataRole.UserRole, m["id"])
                self.list.addItem(it)
            if self.list.count():
                self.list.setCurrentRow(0)
            else:
                self.current = None
                self.title.setText("No meetings yet")
                self.view.setPlainText("Open the meeting copilot (%s+M from any app) and start a meeting. "
                                       "Its transcript, notes and follow-up email are kept here." % MOD)

        def show_item(self, it, _prev=None):
            if it is None:
                return
            self.current = self.store.get(it.data(Qt.ItemDataRole.UserRole))
            if not self.current:
                return
            self.title.setText(self.current["title"])
            self.view.setPlainText(meeting.to_markdown(self.current))

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
                self.c.prompter.toast("Add an AI key in Settings › AI assistant first.", T.bad, 4)
                return
            s = self.c.cfg.s
            tr = meeting.Transcript(m["segments"], m["started"])
            ctx = meeting.build_context(m.get("mode") or s.copilot_mode, s.copilot_modes, tr,
                                        meeting.read_knowledge(s.copilot_files), s.copilot_notes)
            self.pending = m["id"]
            self.view.setPlainText("Writing meeting notes" + "…")
            _ask(self.c, "notes", [{"role": "user", "content": meeting.NOTES_PROMPT}], ctx, None,
                 meeting.NOTES_TOKENS, False, self.relay)

        def _renotes(self, _kind, reply, error, _saw):
            mid = getattr(self, "pending", None)
            if reply and mid:
                parsed = meeting.parse_notes(reply)
                fields = {"notes": reply, "email": parsed.get("FOLLOW-UP EMAIL", "")}
                title = (parsed.get("TITLE") or "").strip().strip("\"'")
                if title:
                    fields["title"] = title.splitlines()[0][:80]
                self.store.update(mid, **fields)
                self.refresh()
            elif error:
                self.view.setPlainText("Couldn't write the notes: %s" % error)

        def delete(self):
            if self.current and self.confirm("Delete meeting", "Delete \"%s\" and its transcript?"
                                             % self.current["title"], "Delete"):
                self.store.delete(self.current["id"])
                self.refresh()

        def done(self, r):
            self.c.meetings_window = None
            super().done(r)

    return Meetings()
