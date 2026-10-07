"""Dialogs: script library, settings, phone pairing, about, first-run welcome."""
import os
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, engine, paths, scripts
from .. import platform as native
from .glass import GlassDialog, Switch
from .theme import AQUA, DASH, DOT, ELLIPSIS, T, VIOLET

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


class BaseDialog(GlassDialog):
    """Frosted glass, top-most dialog that is also hidden from screen sharing (scripts and PINs stay private)."""

    def __init__(self, parent, title, resizable=False):
        super().__init__(parent, resizable=resizable, title=title)
        self.setWindowTitle("%s %s %s" % (APP_NAME, DASH, title))

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


# ====================================================================== settings
class Card(QFrame):
    """Grouped settings surface: rows separated by hairlines (System-Settings style)."""

    def __init__(self, title=None):
        super().__init__()
        self.setProperty("role", "card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 4, 14, 4)
        self.lay.setSpacing(0)
        self.title = title
        self._rows = 0

    def _add(self, w):
        if self._rows:
            line = QFrame()
            line.setProperty("role", "hairline")
            self.lay.addWidget(line)
        self.lay.addWidget(w)
        self._rows += 1

    def row(self, title, control=None, hint=None):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 9, 0, 9)
        h.setSpacing(12)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        txt.addWidget(label(title, "rowtitle"))
        hint_lbl = None
        if hint:
            hint_lbl = label(hint, "muted", True)
            txt.addWidget(hint_lbl)
        h.addLayout(txt, 1)
        if control is not None:
            h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self._add(w)
        return hint_lbl

    def slider(self, title, lo, hi, val, fmt, apply):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 7, 0, 7)
        h.setSpacing(12)
        name = label(title, "rowtitle")
        name.setFixedWidth(92)
        h.addWidget(name)
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        sl.setAccessibleName(title)
        val_lbl = label(fmt(val), "value")
        val_lbl.setFixedWidth(64)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def changed(v):
            val_lbl.setText(fmt(v))
            apply(v)
        sl.valueChanged.connect(changed)
        h.addWidget(sl, 1)
        h.addWidget(val_lbl)
        self._add(w)
        return sl


def _section(lay, card, name):
    head = label(name.upper(), "section")
    head.setContentsMargins(4, 0, 0, 0)
    lay.addWidget(head)
    lay.addSpacing(-2)
    lay.addWidget(card)
    lay.addSpacing(14)


def switch(val, apply):
    sw = Switch()
    sw.setChecked(val)
    sw.toggled.connect(apply)
    return sw


class SettingsDialog(BaseDialog):
    def __init__(self, parent, controller):
        super().__init__(parent, "Settings")
        self.c = controller
        s = controller.cfg.s
        self.setFixedWidth(1240)                      # three columns: short enough for a laptop screen
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(0)
        cols = QHBoxLayout()
        cols.setSpacing(20)
        left, mid, right = QVBoxLayout(), QVBoxLayout(), QVBoxLayout()
        for col in (left, mid, right):
            col.setSpacing(6)
            cols.addLayout(col, 1)
        outer.addLayout(cols)

        # ---- left: reading, voice, read aloud
        card = Card()
        card.slider("Speed", 40, 400, s.wpm, lambda v: "%d wpm" % v, lambda v: self._set("wpm", v))
        card.row("3-2-1 countdown", switch(s.countdown, lambda v: self._set("countdown", v)))
        _section(left, card, "Reading")

        card = Card()
        card.row("Voice Follow", switch(s.voice_follow, lambda v: v != s.voice_follow and controller.prompter.toggle_voice()),
                 "Scrolls with your words. 100% offline.")
        card.row("Coach report after each run", switch(s.coach, lambda v: self._set("coach", v)))
        self.mic = QComboBox()
        self.mic.setAccessibleName("Microphone")
        self.mic.setMinimumWidth(190)
        self.mic.setMaximumWidth(220)
        self.mic.addItem("System default", "")
        from ..voice import list_microphones
        for m in list_microphones():
            self.mic.addItem(m, m)
        i = self.mic.findData(s.mic_device)
        if i < 0 and s.mic_device:
            self.mic.addItem(s.mic_device + " (unplugged)", s.mic_device)
            i = self.mic.count() - 1
        self.mic.setCurrentIndex(max(0, i))
        self.mic.currentIndexChanged.connect(lambda _: self._set("mic_device", self.mic.currentData() or ""))
        lat = controller.voice.latency_ms
        card.row("Microphone", self.mic, ("Measured latency %d ms" % lat) if lat else
                 "Wired or built-in mics react fastest.")
        _section(left, card, "Voice Follow")

        from .. import tts
        card = Card()
        self.voice_box = QComboBox()
        self.voice_box.setAccessibleName("Read aloud voice")
        self.voice_box.setMinimumWidth(220)
        self.voice_box.setMaximumWidth(250)
        for vid, (name, _, _, _) in tts.VOICES.items():
            have = tts.voice_file(vid) is not None
            self.voice_box.addItem(name if have else name + "  (download)", vid)
        self.voice_box.addItem("System voice", tts.SYSTEM)
        i = self.voice_box.findData(s.tts_voice)
        self.voice_box.setCurrentIndex(max(0, i))
        self.voice_box.currentIndexChanged.connect(self._voice_changed)
        self.voice_hint = card.row("Voice", self.voice_box, "Natural neural voices, offline. Pace follows your speed.")
        self.preview = button("Play sample", self._preview)
        self.preview.setProperty("compact", True)
        card.row("Hear it", self.preview)
        _section(left, card, "Read aloud")
        level, note = native.capture_support()
        card = Card()
        card.row("Hide from screen share", switch(s.hide_from_capture, lambda v: self._set("hide_from_capture", v)),
                 note)
        card.row("Phone remote on this Wi-Fi", switch(s.remote_enabled, self._remote), "Protected by a PIN.")
        card.row("Phone can view my screen", switch(s.phone_screen, lambda v: self._set("phone_screen", v)),
                 "Live view and AI chat on your paired phone.")
        left.addStretch(1)
        _section(mid, card, "Privacy")

        # ---- right: appearance, privacy, system
        card = Card()
        card.slider("Text size", 14, 96, s.font_px, lambda v: "%d px" % v, lambda v: self._set("font_px", v))
        card.slider("Glass", 20, 100, int(s.panel_alpha * 100), lambda v: "%d%%" % v,
                    lambda v: self._set("panel_alpha", v / 100))
        card.slider("Reading line", 20, 70, int(s.read_line * 100), lambda v: "%d%%" % v,
                    lambda v: self._set("read_line", v / 100))
        card.slider("Ghost level", 15, 100, int(s.ghost_opacity * 100), lambda v: "%d%%" % v,
                    lambda v: self._set("ghost_opacity", v / 100))
        card.row("Text only, no panel", switch(s.clear_mode, lambda v: self._set("clear_mode", v)))
        card.row("Mirror for teleprompter glass", switch(s.mirror, lambda v: self._set("mirror", v)))
        card.row("Reduce motion", switch(s.reduce_motion, lambda v: self._set("reduce_motion", v)))
        _section(right, card, "Appearance")

        from .. import ai
        card = Card()
        self.ai_provider = QComboBox()
        self.ai_provider.setAccessibleName("AI provider")
        self.ai_provider.setMinimumWidth(190)
        self.ai_provider.setMaximumWidth(220)
        self.ai_provider.addItem("Detect from my key", ai.AUTO)
        for pid, prov in ai.PROVIDERS.items():
            self.ai_provider.addItem(prov["name"], pid)
        self.ai_provider.setCurrentIndex(max(0, self.ai_provider.findData(s.ai_provider)))
        self.ai_provider.currentIndexChanged.connect(self._provider_changed)
        card.row("Provider", self.ai_provider, "Claude, GPT, Gemini\u2026")
        self.ai_key = QLineEdit(ai.load_key())
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key.setPlaceholderText("Paste your API key")
        self.ai_key.setAccessibleName("AI API key")
        self.ai_key.setMinimumWidth(190)
        self.ai_key.setMaximumWidth(220)
        self.ai_key.textChanged.connect(self._key_changed)
        self.key_hint = card.row("API key", self.ai_key, "Stays on this computer.")
        self.ai_url = QLineEdit(s.ai_base_url)
        self.ai_url.setPlaceholderText("Only for Ollama or Other")
        self.ai_url.setAccessibleName("AI server URL")
        self.ai_url.setMinimumWidth(190)
        self.ai_url.setMaximumWidth(220)
        self.ai_url.textChanged.connect(lambda t: (self._set("ai_base_url", t.strip()), self.key_timer.start()))
        card.row("Server URL", self.ai_url)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        self.ai_model.setAccessibleName("AI model")
        self.ai_model.setMinimumWidth(190)
        self.ai_model.setMaximumWidth(220)
        self.ai_model.addItem("Best available (automatic)", "")
        if s.ai_model:
            self.ai_model.addItem(s.ai_model, s.ai_model)
            self.ai_model.setCurrentIndex(1)
        self.ai_model.currentTextChanged.connect(self._model_changed)
        self.model_hint = card.row("Model", self.ai_model, "Or type any name.")
        self.ai_len = QComboBox()
        self.ai_len.setAccessibleName("Answer length")
        self.ai_len.setMinimumWidth(190)
        self.ai_len.setMaximumWidth(220)
        for n, name in ai.ANSWER_LENGTHS.items():
            self.ai_len.addItem(name, n)
        i = self.ai_len.findData(s.ai_max_tokens)
        if i < 0:
            self.ai_len.addItem("%d tokens" % s.ai_max_tokens, s.ai_max_tokens)
            i = self.ai_len.count() - 1
        self.ai_len.setCurrentIndex(i)
        self.ai_len.currentIndexChanged.connect(lambda _: self._set("ai_max_tokens", int(self.ai_len.currentData())))
        card.row("Answer length", self.ai_len, "Pay only for use.")
        b = button("Get a key", self._open_key_page)
        b.setProperty("compact", True)
        card.row("Chat", b, "Press A to ask.")
        self.key_timer = QTimer(self, singleShot=True, interval=700, timeout=self._check_key)
        from PySide6.QtCore import QObject, Signal

        class _Relay(QObject):
            done = Signal(bool, str, list)
        self.key_relay = _Relay(self)
        self.key_relay.done.connect(self._key_checked)
        if ai.load_key() or s.ai_provider == "ollama":
            self.key_timer.start()
        _section(mid, card, "AI assistant")
        mid.addStretch(1)


        card = Card()
        card.row("Check for updates", switch(s.auto_update, lambda v: self._set("auto_update", v)),
                 "Once a day, from GitHub. Nothing about you is sent.")
        card.row("Start at login", switch(native.is_autostart(), self._autostart),
                 "Waits quietly in the %s." % native.TRAY.split(" (")[0])
        b = button("Open", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(s.drop_dir)))
        b.setProperty("compact", True)
        card.row("Drop folder", b, "Drop a .txt, .md or .docx here to load it.")
        b = button("Open", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.backup_dir())))
        b.setProperty("compact", True)
        card.row("Backups", b, "Your library is saved every day. Last 7 kept.")
        b = button("Move", controller.prompter.reset_position)
        b.setProperty("compact", True)
        card.row("Prompter position", b, "Put it back under the camera.")
        _section(right, card, "System")
        hk = controller.hotkey_report() if hasattr(controller, "hotkey_report") else ""
        if hk:
            right.addWidget(label(hk, "muted", True))
        right.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept, primary=True))
        outer.addLayout(foot)
        self._dl = None

    def _set(self, key, value):
        setattr(self.c.cfg.s, key, value)
        self.c.settings_changed(live=True)

    # ---- AI: provider, key, model. The key is cleaned, saved and tested as you paste it (free model-list call),
    #      and the model list is filled from the provider so new models appear without an app update.
    def _key_changed(self, text):
        from .. import ai
        ai.save_key(text)
        key = ai.clean_key(text)
        if key and self.c.cfg.s.ai_provider == ai.AUTO:
            pid = ai.detect_provider(key)
            self.key_hint.setText("Checking the key (%s)\u2026" % (ai.PROVIDERS[pid]["name"] if pid else "OpenAI-compatible"))
        else:
            self.key_hint.setText("Checking the key\u2026" if key else "Stays on this computer.")
        self.key_hint.setStyleSheet("")
        self.key_timer.start()

    def _provider_changed(self, _):
        self._set("ai_provider", self.ai_provider.currentData())
        self._set("ai_model", "")                 # a model from the old provider won't exist on the new one
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        self.ai_model.addItem("Best available (automatic)", "")
        self.ai_model.setCurrentIndex(0)
        self.ai_model.blockSignals(False)
        self.key_timer.start()

    def _model_changed(self, text):
        idx = self.ai_model.findText(text)
        data = self.ai_model.itemData(idx) if idx >= 0 else text.strip()
        self._set("ai_model", data if data is not None else text.strip())

    def _open_key_page(self):
        from .. import ai
        try:
            _, prov, _ = ai.resolve(self.c.cfg.s.ai_provider, ai.load_key(), self.c.cfg.s.ai_base_url or "x")
            url = prov.get("keys") or "https://console.anthropic.com/settings/keys"
        except ai.AIError:
            url = "https://openrouter.ai/keys"
        QDesktopServices.openUrl(QUrl(url))

    def _check_key(self):
        import threading
        from .. import ai
        s = self.c.cfg.s
        key, prov, url = ai.load_key(), s.ai_provider, s.ai_base_url

        def work():
            ok, msg = ai.check_key(key, prov, url)
            models = []
            if ok:
                try:
                    models = ai.list_models(prov, key, url)[:60]
                except Exception:                     # noqa: BLE001 - the list is a convenience
                    models = []
            self.key_relay.done.emit(ok, msg, models)
        if key or prov == "ollama":
            threading.Thread(target=work, daemon=True).start()

    def _key_checked(self, ok, msg, models):
        self.key_hint.setText(("\u2713 " if ok else "\u2717 ") + msg)
        self.key_hint.setStyleSheet("color: %s;" % ("#3DDC97" if ok else "#FF8DA3"))
        if ok and models:
            current = self.c.cfg.s.ai_model
            self.ai_model.blockSignals(True)
            self.ai_model.clear()
            self.ai_model.addItem("Best available (automatic): " + models[0], "")
            for m in models:
                self.ai_model.addItem(m, m)
            i = self.ai_model.findData(current) if current else 0
            if i < 0:
                self.ai_model.addItem(current, current)
                i = self.ai_model.count() - 1
            self.ai_model.setCurrentIndex(i)
            self.ai_model.blockSignals(False)

    def _remote(self, on):
        self.c.cfg.s.remote_enabled = on
        self.c.set_remote_enabled(on)

    def _autostart(self, on):
        self.c.cfg.s.start_with_windows = on
        native.set_autostart(on)
        self.c.settings_changed()

    # ---- natural voices
    def _voice_changed(self, _):
        from .. import tts
        vid = self.voice_box.currentData()
        if vid != tts.SYSTEM and tts.voice_file(vid) is None:
            return self._download(vid)
        self._set("tts_voice", vid)
        self.c.speaker.preload(vid)

    def _download(self, vid):
        import threading
        from .. import tts
        if self._dl:
            return
        state = {"p": 0.0, "done": False, "err": None}

        def run():
            try:
                tts.download_voice(vid, lambda f: state.__setitem__("p", f))
            except Exception as ex:
                state["err"] = str(ex)
            state["done"] = True

        self._dl = threading.Thread(target=run, daemon=True)
        self._dl.start()
        self.voice_box.setEnabled(False)

        def poll():
            if not state["done"]:
                self.voice_hint.setText("Downloading %s  %d%%" % (tts.VOICES[vid][0].split(" ")[0],
                                                                  int(state["p"] * 100)))
                return
            timer.stop()
            self._dl = None
            self.voice_box.setEnabled(True)
            if state["err"]:
                self.voice_hint.setText("Download failed: %s" % state["err"][:80])
                return
            i = self.voice_box.findData(vid)
            self.voice_box.setItemText(i, tts.VOICES[vid][0])
            self.voice_hint.setText("Ready. Natural neural voice, offline.")
            self._set("tts_voice", vid)
            self.c.speaker.preload(vid)

        timer = QTimer(self, interval=150, timeout=poll)
        timer.start()

    def _preview(self):
        from .. import engine
        sample = ("Hi, I'm your Glass Prompter voice. I read at your pace, and the prompter follows every word.")
        lines = engine.wrap(sample, 10000, len)
        if self.c.speaker.speaking:
            self.c.speaker.stop()
            return
        self.c.speaker.speak(lines, self.c.cfg.s.wpm, self.c.cfg.s.tts_voice)


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
            lay.addWidget(label("Scan with your phone's camera. Your phone must be on the same Wi-Fi as this "
                                "computer.", "muted", True))
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
            if self.c.network_note:
                lay.addWidget(label(self.c.network_note, "warn", True))
        lay.addWidget(label("Different network? Save a .txt or .docx into your Glass Prompter drop folder "
                            "(Documents) from any device through OneDrive or iCloud Drive. It loads here "
                            "automatically.", "muted", True))
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
    def __init__(self, parent, check_updates=None):
        super().__init__(parent, "About")
        self.setFixedWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        lay.addWidget(label(APP_NAME, "hero"))
        lay.addWidget(label("Version %s" % __version__, "muted"))
        lay.addWidget(label("A see-through teleprompter that sits under your webcam, so you can read your script "
                            "and keep eye contact on calls, demos and videos.", None, True))
        lay.addWidget(label("Your scripts and settings stay on this computer:\n" + paths.data_dir(), "muted", True))
        row = QHBoxLayout()
        row.addWidget(button("Open data folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir()))))
        row.addWidget(button("Open logs", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.log_dir()))))
        if check_updates:
            row.addWidget(button("Check for updates", lambda: (check_updates(), self.accept())))
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
                                  "into the Glass Prompter folder in Documents."),
            ("3", "Read from any app", "%s+Space plays and pauses even while Zoom or Teams is in front. "
                                       "Turn on Voice Follow (V) and the script follows your voice." % native.MOD),
        ]
        for num, head, body in steps:
            card = QFrame()
            card.setProperty("role", "card")
            g = QGridLayout(card)
            g.setContentsMargins(16, 14, 16, 14)
            g.setHorizontalSpacing(14)
            n = label(num, "title")
            n.setFixedWidth(22)
            n.setStyleSheet("color: %s;" % (AQUA if num != "2" else VIOLET))
            g.addWidget(n, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
            hl = label(head)
            hl.setStyleSheet("font-weight: 600;")
            g.addWidget(hl, 0, 1)
            g.addWidget(label(body, "muted", True), 1, 1)
            lay.addWidget(card)
        lay.addWidget(label("The badge in the corner always tells you the truth about what viewers can see. "
                            "Glass Prompter lives in the " + native.TRAY + " " + DASH +
                            " click its icon for everything else.", "muted", True))
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(button("Get started", self.accept, primary=True))
        lay.addLayout(foot)


# ====================================================================== rehearsal report card
class ScoreRing(QWidget):
    def __init__(self, score):
        super().__init__()
        self.score = score
        self.setFixedSize(150, 150)
        self._shown = 0.0
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=float(score), duration=900,
                                       easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)
        QTimer.singleShot(150, self._anim.start)

    def _tick(self, v):
        self._shown = float(v)
        self.update()

    def color(self):
        from .theme import T
        return T.ok if self.score >= 85 else (T.warn if self.score >= 65 else T.bad)

    def paintEvent(self, e):
        from PySide6.QtGui import QPen
        from .theme import font
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(10, 10, 130, 130)
        p.setPen(QPen(QColor(255, 255, 255, 28), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 225 * 16, -270 * 16)
        from .theme import aurora_line
        pen = QPen(self.color(), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        if self.score >= 85:
            pen.setBrush(aurora_line(10, 140))
        p.setPen(pen)
        p.drawArc(r, 225 * 16, int(-270 * 16 * self._shown / 100.0))
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font("display", 44, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 30, 150, 64), Qt.AlignmentFlag.AlignCenter, str(int(round(self._shown))))
        p.setPen(QColor("#9A9AA8"))
        p.setFont(font("ui", 12))
        p.drawText(QRectF(0, 88, 150, 20), Qt.AlignmentFlag.AlignCenter, "score")


class HistoryBars(QWidget):
    def __init__(self, scores):
        super().__init__()
        self.scores = list(reversed(scores))[-8:]        # oldest -> newest
        self.setFixedHeight(64)

    def paintEvent(self, e):
        from .theme import T
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = max(1, len(self.scores))
        bw = min(26.0, (self.width() - 8) / n - 6)
        for i, s in enumerate(self.scores):
            h = max(4.0, (self.height() - 18) * s / 100.0)
            x = 4 + i * (bw + 6)
            last = i == len(self.scores) - 1
            col = QColor(T.accent if last else QColor(255, 255, 255, 60))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, self.height() - 14 - h, bw, h), 4, 4)
            p.setPen(QColor("#9A9AA8") if not last else T.accent)
            from .theme import font
            p.setFont(font("ui", 10))
            p.drawText(QRectF(x - 4, self.height() - 13, bw + 8, 13), Qt.AlignmentFlag.AlignCenter, str(s))


class ReportDialog(BaseDialog):
    """Peak-end moment after a rehearsal: score, pace, fillers, pauses, skips, one tip, progress over time."""

    def __init__(self, parent, report, history):
        super().__init__(parent, "Rehearsal report")
        self.again = False
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(20)
        head.addWidget(ScoreRing(report["score"]))
        txt = QVBoxLayout()
        txt.addWidget(label(report.get("title", "") or "Your run", "title", True))
        trend = report.get("trend")
        if trend is not None:
            t = label(("+%d" % trend if trend >= 0 else "%d" % trend) + " vs your last run", None)
            t.setStyleSheet("color: %s; font-weight: 600;" % ("#3DDC97" if trend >= 0 else "#FF5C7A"))
            txt.addWidget(t)
        tip = label(report["tip"], None, True)
        tip.setStyleSheet("font-size: 15px;")
        txt.addSpacing(6)
        txt.addWidget(tip)
        txt.addStretch(1)
        head.addLayout(txt, 1)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(10)
        from ..coach import GOOD_PACE, pace_label
        pace = pace_label(report["wpm"]) or "good"
        fill = report["fillers"]
        top = ", ".join("%s %d" % (k, v) for k, v in sorted(fill.items(), key=lambda kv: -kv[1])[:3]) or "none"
        tiles = [
            ("PACE", "%d wpm" % report["wpm"], {"good": "in the zone", "fast": "too fast",
                                                "slow": "a bit slow"}[pace] + "  %s  %d-%d" % ((DOT,) + GOOD_PACE)),
            ("FILLERS", str(report["filler_count"]), top),
            ("PAUSES", str(report["long_pauses"]), "longest %.1fs" % report["longest_pause"]
             if report["long_pauses"] else "no long gaps"),
            ("SKIPPED", "%d words" % report["skipped"], "%d%% covered" % int(report["coverage"] * 100)),
            ("TIME", engine.fmt_secs(report["seconds"]), "spoken"),
        ]
        for i, (k, v, sub) in enumerate(tiles):
            card = QFrame()
            card.setProperty("role", "card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            cl.setSpacing(2)
            cl.addWidget(label(k, "section"))
            big = label(v)
            big.setStyleSheet("font-size: 21px; font-weight: 600;")
            cl.addWidget(big)
            cl.addWidget(label(sub, "muted"))
            grid.addWidget(card, i // 3, i % 3)
        lay.addLayout(grid)
        if len(history) > 1:
            lay.addWidget(label("YOUR LAST %d RUNS" % len(history), "section"))
            lay.addWidget(HistoryBars([h["score"] for h in history]))
        foot = QHBoxLayout()
        foot.addWidget(label("Everything stays on this computer.", "muted"))
        foot.addStretch(1)
        foot.addWidget(button("Done", self.accept))
        foot.addWidget(button("Practice again", self._again, primary=True))
        lay.addLayout(foot)

    def _again(self):
        self.again = True
        self.accept()
