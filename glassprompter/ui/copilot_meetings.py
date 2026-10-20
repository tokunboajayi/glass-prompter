import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser,
                               QVBoxLayout)

from .. import meeting, paths
from ..platform import MOD
from .copilot import _ai_ready, _ask, _btn, _card, _Relay
from .dialogs import BaseDialog, label
from .theme import ELLIPSIS, T

_DOC_CSS = ("h1 { font-size: 20px; } h2 { font-size: 15px; color: #8C95AB; margin-top: 18px; } "
            "h3 { font-size: 13px; color: #8C95AB; margin-top: 14px; } "
            "p, li { color: #E4E8F2; line-height: 140%; } em { color: #A0A8BC; } strong { color: #40E8D0; }")


class Meetings(BaseDialog):
    def __init__(self, controller):
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
