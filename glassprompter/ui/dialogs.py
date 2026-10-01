"""Dialogs: script library, settings, phone pairing, about, first-run welcome."""
import os
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, engine, paths, scripts, win32
from .theme import DASH, DOT, ELLIPSIS

try:
    import qrcode
except Exception:            # optional
    qrcode = None


def label(text, role=None, wrap=False):
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


def button(text, fn, primary=False, danger=False):
    b = QPushButton(text)
    b.clicked.connect(fn)
    if primary:
        b.setProperty("primary", True)
        b.setDefault(True)
    if danger:
        b.setProperty("danger", True)
    return b


class BaseDialog(QDialog):
    """Dark, top-most dialog that is also hidden from screen sharing (scripts and PINs stay private)."""

    def __init__(self, parent, title):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("%s %s %s" % (APP_NAME, DASH, title))

    def showEvent(self, e):
        super().showEvent(e)
        win32.set_capture_excluded(int(self.winId()), True)

    def confirm(self, title, text, ok_text):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.NoIcon)
        ok = box.addButton(ok_text, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        ok.setProperty("danger", True)
        box.exec()
        return box.clickedButton() is ok


# ====================================================================== library
class LibraryDialog(BaseDialog):
    def __init__(self, parent, store, current_id, load_cb):
        super().__init__(parent, "Scripts")
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
        left.addWidget(label("Scripts", "title"))
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
        row.addWidget(button("New", self.new_script))
        row.addWidget(button("Import" + ELLIPSIS, self.import_files))
        row.addStretch(1)
        self.del_btn = button("Delete", self.delete_script, danger=True)
        row.addWidget(self.del_btn)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(300)
        root.addWidget(lw)

        # right: editor
        right = QVBoxLayout()
        right.setSpacing(10)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (optional " + DASH + " taken from the first line)")
        self.title.setMaxLength(scripts.MAX_TITLE)
        self.title.textEdited.connect(self._edited)
        right.addWidget(self.title)
        right.addWidget(label("[PAUSE] on its own line stops the scroll  %s  [ANY CUE] on its own line shows in amber"
                              % DOT, "muted"))
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


# ====================================================================== settings
class SettingsDialog(BaseDialog):
    def __init__(self, parent, controller):
        super().__init__(parent, "Settings")
        self.c = controller
        s = controller.cfg.s
        self.setFixedWidth(820)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)
        outer.addWidget(label("Settings", "title"))
        cols = QHBoxLayout()
        cols.setSpacing(36)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(10)
        right.setSpacing(10)
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        outer.addLayout(cols)

        def section(lay, name, first=False):
            if not first:
                lay.addSpacing(8)
            lay.addWidget(label(name.upper(), "section"))

        def slider_row(lay, text, lo, hi, val, fmt, apply):
            row = QHBoxLayout()
            name = label(text)
            name.setFixedWidth(96)
            row.addWidget(name)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(val)
            sl.setAccessibleName(text)
            val_lbl = label(fmt(val), "muted")
            val_lbl.setFixedWidth(68)

            def changed(v):
                val_lbl.setText(fmt(v))
                apply(v)
            sl.valueChanged.connect(changed)
            row.addWidget(sl, 1)
            row.addWidget(val_lbl)
            lay.addLayout(row)
            return sl

        def check(lay, text, val, apply, hint=None):
            cb = QCheckBox(text)
            cb.setChecked(val)
            cb.toggled.connect(apply)
            lay.addWidget(cb)
            if hint:
                h = label(hint, "muted", True)
                h.setContentsMargins(28, 0, 0, 2)
                lay.addWidget(h)
            return cb

        section(left, "Reading", first=True)
        slider_row(left, "Speed", 40, 400, s.wpm, lambda v: "%d wpm" % v, lambda v: self._set("wpm", v))
        check(left, "3-2-1 countdown before scrolling", s.countdown, lambda v: self._set("countdown", v))
        section(left, "Look")
        slider_row(left, "Text size", 14, 96, s.font_px, lambda v: "%d px" % v, lambda v: self._set("font_px", v))
        slider_row(left, "Glass", 20, 100, int(s.panel_alpha * 100), lambda v: "%d%%" % v,
                   lambda v: self._set("panel_alpha", v / 100))
        slider_row(left, "Reading line", 20, 70, int(s.read_line * 100), lambda v: "%d%% down" % v,
                   lambda v: self._set("read_line", v / 100))
        check(left, "Text only (no glass panel)", s.clear_mode, lambda v: self._set("clear_mode", v))
        check(left, "Reduce motion", s.reduce_motion, lambda v: self._set("reduce_motion", v))
        row = QHBoxLayout()
        row.addWidget(button("Move back under the camera", controller.prompter.reset_position))
        row.addStretch(1)
        left.addLayout(row)
        left.addStretch(1)

        section(right, "Privacy", first=True)
        check(right, "Hide from screen sharing and recordings", s.hide_from_capture,
              lambda v: self._set("hide_from_capture", v),
              "Zoom, Teams, Meet, OBS and screenshots won't see the prompter.")
        check(right, "Phone remote on this Wi-Fi", s.remote_enabled, self._remote,
              "A phone on the same network can send scripts and control playback, protected by a PIN.")
        section(right, "System")
        check(right, "Start with Windows (in the tray)", win32.is_autostart(), self._autostart)
        right.addWidget(label("Drop folder", None))
        drop = label(s.drop_dir, "muted", True)
        drop.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(drop)
        right.addWidget(label("Save a .txt, .md or .docx here (from any device via OneDrive) and it's added to "
                              "your library and loaded automatically.", "muted", True))
        row = QHBoxLayout()
        row.addWidget(button("Open drop folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(s.drop_dir))))
        row.addStretch(1)
        right.addLayout(row)
        hk = controller.hotkey_report() if hasattr(controller, "hotkey_report") else ""
        if hk:
            right.addWidget(label(hk, "muted", True))
        right.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept, primary=True))
        outer.addLayout(foot)

    def _set(self, key, value):
        setattr(self.c.cfg.s, key, value)
        self.c.settings_changed(live=True)

    def _remote(self, on):
        self.c.cfg.s.remote_enabled = on
        self.c.set_remote_enabled(on)

    def _autostart(self, on):
        self.c.cfg.s.start_with_windows = on
        win32.set_autostart(on)
        self.c.settings_changed()


# ====================================================================== phone
class QrWidget(QWidget):
    def __init__(self, data, size=220):
        super().__init__()
        self.setFixedSize(size, size)
        self.matrix = None
        if qrcode:
            q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
            q.add_data(data)
            q.make(fit=True)
            self.matrix = q.get_matrix()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)
        if not self.matrix:
            p.setPen(QColor("#333"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "QR code unavailable")
            return
        n = len(self.matrix)
        cell = (self.width() - 8) / n
        off = (self.width() - cell * n) / 2
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(QColor("#000000"))
        for y, row in enumerate(self.matrix):
            for x, v in enumerate(row):
                if v:
                    p.drawRect(QRectF(off + x * cell, off + y * cell, cell + 0.6, cell + 0.6))


class PhoneDialog(BaseDialog):
    def __init__(self, parent, controller):
        super().__init__(parent, "Phone remote")
        self.c = controller
        self.setFixedWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(12)
        self.build()

    def build(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _clear_layout(it.layout())
        lay, srv = self.lay, self.c.server
        lay.addWidget(label("Control it from your phone", "title"))
        if not self.c.cfg.s.remote_enabled:
            lay.addWidget(label("The phone remote is turned off.", "muted", True))
            lay.addWidget(button("Turn it on", lambda: (self.c.set_remote_enabled(True), self.build()), primary=True))
        elif not srv or not srv.running:
            err = srv.error if srv else "not started"
            lay.addWidget(label("The phone remote couldn't start (%s). Another app may be using port %d. "
                                "Change nothing and restart the app, or turn the remote off in Settings."
                                % (err, self.c.cfg.s.remote_port), "warn", True))
        else:
            url = srv.url()
            lay.addWidget(label("Scan with your phone's camera. Your phone must be on the same Wi-Fi as this PC.",
                                "muted", True))
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(QrWidget(url))
            row.addStretch(1)
            lay.addLayout(row)
            lay.addWidget(label("Or open this address and enter the PIN", "muted"))
            urow = QHBoxLayout()
            box = QLineEdit(srv.url(with_pin=False))
            box.setReadOnly(True)
            urow.addWidget(box, 1)
            copy = button("Copy", lambda: (QGuiApplication.clipboard().setText(srv.url(with_pin=False)),
                                           copy.setText("Copied")))
            urow.addWidget(copy)
            lay.addLayout(urow)
            prow = QHBoxLayout()
            prow.addWidget(label("PIN", "muted"))
            prow.addWidget(label(srv.pin, "pin"))
            prow.addStretch(1)
            prow.addWidget(button("New PIN", self._new_pin))
            lay.addLayout(prow)
            lay.addWidget(label("A new PIN disconnects every paired phone.", "muted"))
            if self.c.network_category == "Public":
                lay.addWidget(label("This Wi-Fi is set to Public in Windows. If your phone can't connect, allow "
                                    "Glass Prompter through the firewall when Windows asks, or set this network to "
                                    "Private: Settings > Network & internet > Wi-Fi > your network.", "warn", True))
        lay.addWidget(label("Different network? Save a .txt or .docx into your Glass Prompter drop folder "
                            "(Documents) from any device through OneDrive. It loads here automatically.",
                            "muted", True))
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept, primary=True))
        lay.addLayout(foot)

    def _new_pin(self):
        self.c.regenerate_pin()
        self.build()


def _clear_layout(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())


# ====================================================================== about
class AboutDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "About")
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        lay.addWidget(label(APP_NAME, "hero"))
        lay.addWidget(label("Version %s" % __version__, "muted"))
        lay.addWidget(label("A see-through teleprompter that sits under your webcam, so you can read your script "
                            "and keep eye contact on calls, demos and videos.", None, True))
        lay.addWidget(label("Your scripts and settings stay on this PC:\n" + paths.data_dir(), "muted", True))
        row = QHBoxLayout()
        row.addWidget(button("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir()))))
        row.addWidget(button("Open logs", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.log_dir()))))
        row.addStretch(1)
        row.addWidget(button("Close", self.accept, primary=True))
        lay.addSpacing(6)
        lay.addLayout(row)


# ====================================================================== welcome
class WelcomeDialog(BaseDialog):
    def __init__(self, parent, drop_dir):
        super().__init__(parent, "Welcome")
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)
        lay.addWidget(label("Welcome to Glass Prompter", "hero"))
        lay.addWidget(label("Read your script while looking straight at the camera.", "muted"))
        steps = [
            ("1", "It sits under your camera", "The glass bar at the top of your screen is the prompter. Drag it "
                                              "anywhere, or drag an edge to resize it."),
            ("2", "Add a script", "Press E for your script library, send one from your phone (P), or drop a file "
                                  "into Documents\\Glass Prompter."),
            ("3", "Read from any app", "Ctrl+Alt+Space plays and pauses even while Zoom or Teams is in front. "
                                       "Ctrl+Alt+Up and Down change the speed."),
        ]
        for num, head, body in steps:
            card = QFrame()
            card.setProperty("role", "card")
            g = QGridLayout(card)
            g.setContentsMargins(16, 14, 16, 14)
            g.setHorizontalSpacing(14)
            n = label(num, "title")
            n.setFixedWidth(22)
            n.setStyleSheet("color: #FFB020;")
            g.addWidget(n, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            hl = label(head)
            hl.setStyleSheet("font-weight: 600;")
            g.addWidget(hl, 0, 1)
            g.addWidget(label(body, "muted", True), 1, 1)
            lay.addWidget(card)
        lay.addWidget(label("The green \"Hidden from screen share\" badge means viewers can't see the prompter. "
                            "Glass Prompter lives in the tray (bottom-right of the taskbar) " + DASH +
                            " right-click it for everything else.", "muted", True))
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Get started", self.accept, primary=True))
        lay.addLayout(foot)
