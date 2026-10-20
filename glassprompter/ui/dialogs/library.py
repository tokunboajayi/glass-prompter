"""Script library dialog."""
import os
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from ... import engine, paths, scripts
from ..theme import DASH, DOT, ELLIPSIS
from .common import BaseDialog, button, label


# ====================================================================== library
class LibraryDialog(BaseDialog):
    def __init__(self, parent, store, current_id, load_cb):
        super().__init__(parent, "Scripts", resizable=True)
        self.store, self.load_cb = store, load_cb
        self.current = None              # dict of the script being edited (None = new)
        self.dirty = False
        self.resize(940, 600)
        self.setMinimumSize(640, 420)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # left: list
        left = QVBoxLayout()
        left.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search" + ELLIPSIS)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.search_timer = QTimer(self, singleShot=True, interval=200, timeout=self.refresh)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list.currentItemChanged.connect(self._picked)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        for b in (button("New", self.new_script), button("Import", self.import_files),
                  button("Export", self.export_all)):
            b.setProperty("compact", True)
            row.addWidget(b)
        row.addStretch(1)
        self.del_btn = button("Delete", self.delete_script, danger=True)
        self.del_btn.setProperty("compact", True)
        row.addWidget(self.del_btn)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(320)
        root.addWidget(lw)

        # right: editor
        right = QVBoxLayout()
        right.setSpacing(10)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (optional " + DASH + " taken from the first line)")
        self.title.setMaxLength(scripts.MAX_TITLE)
        self.title.textEdited.connect(self._edited)
        right.addWidget(self.title)
        right.addWidget(label("# Heading = section  %s  [PAUSE] on its own line stops the scroll  %s  [ANY CUE] shows "
                              "in orange" % (DOT, DOT), "muted"))
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Paste or type your script" + ELLIPSIS)
        self.body.textChanged.connect(self._edited)
        right.addWidget(self.body, 1)
        foot = QHBoxLayout()
        foot.addWidget(button("Insert [PAUSE]", lambda: self.body.insertPlainText("\n[PAUSE]\n")))
        self.info = label("", "muted")
        foot.addSpacing(8)
        foot.addWidget(self.info, 1)
        self.save_btn = button("Save", self.save)
        foot.addWidget(self.save_btn)
        foot.addWidget(button("Load into prompter", self.load, primary=True))
        right.addLayout(foot)
        root.addLayout(right, 1)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.load)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_script)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)

        self.refresh(select_id=current_id)
        if self.list.count() == 0:
            self.new_script()

    # -- list
    def refresh(self, select_id=None):
        if select_id is None and self.current:
            select_id = self.current["id"]
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.store.list(self.search.text().strip() or None):
            it = QListWidgetItem("%s\n%d words  %s  %s" % (s["title"], s["words"], DOT, _ago(s["last_used"] or s["updated"])))
            it.setData(Qt.ItemDataRole.UserRole, s["id"])
            it.setSizeHint(QSize(0, 58))
            self.list.addItem(it)
            if s["id"] == select_id:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        cur = self.list.currentItem()
        if cur and (not self.current or self.current["id"] != cur.data(Qt.ItemDataRole.UserRole)):
            self._open(cur.data(Qt.ItemDataRole.UserRole))
        self.del_btn.setEnabled(self.current is not None)

    def _picked(self, item, _prev):
        if not item:
            return
        if self.dirty and not self.save(quiet=True):
            return
        self._open(item.data(Qt.ItemDataRole.UserRole))

    def _open(self, sid):
        s = self.store.get(sid)
        self.current = s
        self.title.setText(s["title"] if s else "")
        self.body.blockSignals(True)
        self.body.setPlainText(s["body"] if s else "")
        self.body.blockSignals(False)
        self.dirty = False
        self._update_info()
        self.del_btn.setEnabled(s is not None)

    def new_script(self):
        if self.dirty and not self.save(quiet=True):
            return
        self.list.blockSignals(True)
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.list.blockSignals(False)
        self.current = None
        self.title.clear()
        self.body.blockSignals(True)
        self.body.clear()
        self.body.blockSignals(False)
        self.dirty = False
        self._update_info()
        self.del_btn.setEnabled(False)
        self.body.setFocus()

    # -- edit
    def _edited(self, *_):
        self.dirty = True
        self._update_info()

    def _update_info(self):
        n = engine.count_words(self.body.toPlainText())
        state = "Unsaved changes" if self.dirty else ("Saved" if self.current else "New script")
        self.info.setText("%d words  %s  ~%s  %s  %s" % (n, DOT, engine.fmt_secs(n / 150 * 60), DOT, state))
        self.info.setToolTip("Estimated speaking time at 150 words per minute")

    def save(self, quiet=False):
        text = self.body.toPlainText()
        if not text.strip():
            if not quiet:
                self.info.setText("The script is empty")
            return not quiet           # an empty new script is simply discarded when switching
        try:
            if self.current:
                self.current = self.store.update(self.current["id"], self.title.text(), text)
            else:
                self.current = self.store.create(self.title.text(), text)
        except scripts.ValidationError as ex:
            self.info.setText(str(ex))
            return False
        self.dirty = False
        self.title.setText(self.current["title"])
        self.refresh(select_id=self.current["id"])
        self._update_info()
        return True

    def load(self):
        if not self.save():
            return
        self.load_cb(self.current["id"])
        self.accept()

    def delete_script(self):
        if not self.current:
            return
        if not self.confirm("Delete script", "Delete \"%s\"? This can't be undone." % self.current["title"], "Delete"):
            return
        self.store.delete(self.current["id"])
        self.current, self.dirty = None, False
        self.refresh()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.new_script()

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import scripts", paths.documents_dir(),
                                                "Scripts (*.txt *.md *.docx)")
        last = None
        errors = []
        for f in files:
            try:
                last = self.store.create(scripts.title_from_filename(f), scripts.read_file(f))
            except (scripts.ValidationError, OSError) as ex:
                errors.append("%s: %s" % (os.path.basename(f), ex))
        if last:
            self.current, self.dirty = None, False
            self.refresh(select_id=last["id"])
        if errors:
            self.info.setText("; ".join(errors)[:200])

    def export_all(self):
        """Every script as a Markdown file - your words are never locked in."""
        if self.dirty:
            self.save(quiet=True)
        folder = QFileDialog.getExistingDirectory(self, "Export all scripts to", paths.documents_dir())
        if not folder:
            return
        try:
            n = scripts.export_markdown(self.store, folder)
        except OSError as ex:
            self.info.setText("Export failed: %s" % ex)
            return
        self.info.setText("Exported %d script%s to %s" % (n, "" if n == 1 else "s", folder))

    def done(self, r):
        if self.dirty:
            self.save(quiet=True)          # never lose typing
        super().done(r)


def _ago(ts):
    if not ts:
        return ""
    s = max(0, time.time() - ts)
    if s < 60:
        return "just now"
    if s < 3600:
        return "%d min ago" % (s // 60)
    if s < 86400:
        return "%d h ago" % (s // 3600)
    return "%d d ago" % (s // 86400)
