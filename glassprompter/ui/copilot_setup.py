import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from .. import meeting, paths
from .copilot import _btn
from .dialogs import BaseDialog, Card, _section, button, label
from .theme import ELLIPSIS, T


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
