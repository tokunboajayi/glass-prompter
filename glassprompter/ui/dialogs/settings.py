"""Settings dialog: one sidebar page per area, with the AI sign-in and key handling in AIKeyPanel."""
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ... import paths
from ... import platform as native
from .. import icons
from ..glass import GLASS_LEVELS
from ..theme import DOT, ELLIPSIS, T
from .common import BaseDialog, Card, _section, button, label, switch


class AIKeyPanel(QObject):
    """The AI card: one-click sign-in, provider, API key, model and answer length."""

    done = Signal(bool, str, list)
    signed = Signal(str, object, object)          # (which, result, error)

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dlg = dialog
        self.c = dialog.c

    def build(self, card):
        from ... import ai
        s = self.c.cfg.s
        # one-click sign-in instead of copying a key: ChatGPT (your Plus/Pro plan) or OpenRouter (makes a key)
        signin_box = QWidget()
        sb = QHBoxLayout(signin_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(6)
        self.chatgpt_btn = button("ChatGPT", self._chatgpt_sign_in)
        self.chatgpt_btn.setProperty("compact", True)
        self.chatgpt_btn.setToolTip("Sign in with your ChatGPT Plus or Pro account. Answers use your plan's "
                                    "allowance, no API key or API bill.")
        self.openrouter_btn = button("OpenRouter", self._openrouter_sign_in)
        self.openrouter_btn.setProperty("compact", True)
        self.openrouter_btn.setToolTip("Sign in with OpenRouter and get a key automatically: one key for Claude, "
                                       "GPT, Gemini and hundreds more. Pay-as-you-go credit.")
        sb.addWidget(self.chatgpt_btn)
        sb.addWidget(self.openrouter_btn)
        self.signin_hint = card.row("Sign in", signin_box, "No key needed.")      # text set by _refresh_signin
        self.ai_provider = QComboBox()
        self.ai_provider.setAccessibleName("AI provider")
        self.ai_provider.setMinimumWidth(190)
        self.ai_provider.setMaximumWidth(220)
        self.ai_provider.addItem("Detect from my key", ai.AUTO)
        for pid, prov in ai.PROVIDERS.items():
            self.ai_provider.addItem(prov["name"], pid)
        self.ai_provider.setCurrentIndex(max(0, self.ai_provider.findData(s.ai_provider)))
        self.ai_provider.currentIndexChanged.connect(self._provider_changed)
        card.row("Provider", self.ai_provider, "Any provider works.")
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
        self.ai_url.textChanged.connect(lambda t: (self.dlg._set("ai_base_url", t.strip()), self.key_timer.start()))
        card.row("Server URL", self.ai_url)
        self.ai_model = QComboBox()
        self.ai_model.setEditable(True)
        self.ai_model.setAccessibleName("AI model")
        self.ai_model.setMinimumWidth(190)
        self.ai_model.setMaximumWidth(220)
        self.ai_model.addItem("Automatic (best)", "")
        if s.ai_model:
            self.ai_model.addItem(s.ai_model, s.ai_model)
            self.ai_model.setCurrentIndex(1)
        self.ai_model.lineEdit().setCursorPosition(0)        # show the start of a long name, not its tail
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
        self.ai_len.currentIndexChanged.connect(lambda _: self.dlg._set("ai_max_tokens", int(self.ai_len.currentData())))
        card.row("Answer length", self.ai_len, "Pay only for use.")
        b = button("Get a key", self._open_key_page)
        b.setProperty("compact", True)
        card.row("Chat", b, "Press A to ask.")
        self.key_timer = QTimer(self, singleShot=True, interval=700, timeout=self._check_key)
        self.done.connect(self._key_checked)
        self.signed.connect(self._signed_in)
        self._signing = None
        self._refresh_signin()
        self._key_field_state()
        if ai.is_ready(s.ai_provider):
            self.key_timer.start()

    # ---- one-click sign-in (signin.py). Runs on a worker thread; the browser does the rest.
    def _refresh_signin(self):
        from ... import signin
        connected = signin.chatgpt_connected()
        busy = self._signing
        self.chatgpt_btn.setText("Waiting" + ELLIPSIS if busy == "chatgpt" else
                                 ("Sign out" if connected else "ChatGPT"))
        self.openrouter_btn.setText("Waiting" + ELLIPSIS if busy == "openrouter" else "OpenRouter")
        self.chatgpt_btn.setEnabled(busy in (None, "chatgpt"))
        self.openrouter_btn.setEnabled(busy in (None, "openrouter"))
        if busy:
            self.signin_hint.setText("Finish in your browser. Click again to cancel.")
        elif connected:
            who = signin.chatgpt_account()
            self.signin_hint.setText("ChatGPT plan connected" + ((" " + DOT + " " + who) if who else "") + ".")
        else:
            self.signin_hint.setText("Use your ChatGPT plan, or get an OpenRouter key.")

    def _start_signin(self, which, fn):
        import threading
        if self._signing == which:                       # second click cancels
            self._cancel.set()
            return
        self._signing = which
        self._cancel = threading.Event()
        cancel = self._cancel
        self._refresh_signin()

        def work():
            from ... import signin
            try:
                self.signed.emit(which, fn(cancel=cancel), None)
            except signin.SignInError as e:
                self.signed.emit(which, None, str(e))
            except Exception as e:                       # noqa: BLE001
                self.signed.emit(which, None, "Sign-in failed: %s" % e)
        threading.Thread(target=work, name="signin-" + which, daemon=True).start()

    def _chatgpt_sign_in(self):
        from ... import signin
        if self._signing is None and signin.chatgpt_connected():
            return self._chatgpt_sign_out()
        self._start_signin("chatgpt", signin.chatgpt_sign_in)

    def _openrouter_sign_in(self):
        from ... import signin
        self._start_signin("openrouter", signin.openrouter_sign_in)

    def _signed_in(self, which, result, error):
        from ... import ai
        self._signing = None
        if error:
            self._refresh_signin()
            self.signin_hint.setText(("✗ " + error) if "cancelled" not in error else "Sign-in cancelled.")
            self.signin_hint.setStyleSheet("" if "cancelled" in error else "color: #FF8DA3;")
            return
        self.signin_hint.setStyleSheet("")
        if which == "openrouter":
            self.ai_key.setText(result)                  # saves it and checks it (_key_changed)
            self.ai_provider.setCurrentIndex(self.ai_provider.findData("openrouter"))
        else:
            self.ai_provider.setCurrentIndex(self.ai_provider.findData("chatgpt"))
            self.key_timer.start()
        self._refresh_signin()
        self.c.prompter.toast("Signed in with %s" % ("ChatGPT" if which == "chatgpt" else "OpenRouter"), T.ok)
        if ai.is_ready(self.c.cfg.s.ai_provider) and getattr(self.c, "assistant", None) is not None:
            self.c.assistant.refresh_info()

    def _chatgpt_sign_out(self):
        import threading
        from ... import signin
        threading.Thread(target=signin.chatgpt_sign_out, name="signout-chatgpt", daemon=True).start()
        from ... import ai
        if self.c.cfg.s.ai_provider == "chatgpt":
            self.ai_provider.setCurrentIndex(max(0, self.ai_provider.findData(ai.AUTO)))
        self._refresh_signin()
        self.c.prompter.toast("Signed out of ChatGPT", T.ok)

    # ---- AI: provider, key, model. The key is cleaned, saved and tested as you paste it (free model-list call),
    #      and the model list is filled from the provider so new models appear without an app update.
    def _key_changed(self, text):
        from ... import ai
        ai.save_key(text)
        key = ai.clean_key(text)
        if key and self.c.cfg.s.ai_provider == ai.AUTO:
            pid = ai.detect_provider(key)
            self.key_hint.setText("Checking the key (%s)…" % (ai.PROVIDERS[pid]["name"] if pid else "OpenAI-compatible"))
        else:
            self.key_hint.setText("Checking the key…" if key else "Stays on this computer.")
        self.key_hint.setStyleSheet("")
        self.key_timer.start()

    def _provider_changed(self, _):
        self.dlg._set("ai_provider", self.ai_provider.currentData())
        self.dlg._set("ai_model", "")                 # a model from the old provider won't exist on the new one
        self.ai_model.blockSignals(True)
        self.ai_model.clear()
        self.ai_model.addItem("Automatic (best)", "")
        self.ai_model.setCurrentIndex(0)
        self.ai_model.blockSignals(False)
        self._key_field_state()
        self.key_timer.start()

    def _key_field_state(self):
        """With the ChatGPT plan there's no key: grey the field out instead of asking for one."""
        plan = self.c.cfg.s.ai_provider == "chatgpt"
        self.ai_key.setEnabled(not plan)
        self.ai_key.setPlaceholderText("Not needed with ChatGPT sign-in" if plan else "Paste your API key")

    def _model_changed(self, text):
        idx = self.ai_model.findText(text)
        data = self.ai_model.itemData(idx) if idx >= 0 else text.strip()
        self.dlg._set("ai_model", data if data is not None else text.strip())

    def _open_key_page(self):
        from ... import ai
        try:
            _, prov, _ = ai.resolve(self.c.cfg.s.ai_provider, ai.load_key(), self.c.cfg.s.ai_base_url or "x")
            url = prov.get("keys") or "https://console.anthropic.com/settings/keys"
        except ai.AIError:
            url = "https://openrouter.ai/keys"
        QDesktopServices.openUrl(QUrl(url))

    def _check_key(self):
        import threading
        from ... import ai
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
            self.done.emit(ok, msg, models)
        if key or prov in ("ollama", "chatgpt"):
            threading.Thread(target=work, daemon=True).start()

    def _key_checked(self, ok, msg, models):
        self.key_hint.setText(("✓ " if ok else "✗ ") + msg)
        self.key_hint.setStyleSheet("color: %s;" % ("#3DDC97" if ok else "#FF8DA3"))
        if ok and models:
            current = self.c.cfg.s.ai_model
            self.ai_model.blockSignals(True)
            self.ai_model.clear()
            self.ai_model.addItem("Automatic: " + models[0], "")
            for m in models:
                self.ai_model.addItem(m, m)
            i = self.ai_model.findData(current) if current else 0
            if i < 0:
                self.ai_model.addItem(current, current)
                i = self.ai_model.count() - 1
            self.ai_model.setCurrentIndex(i)
            self.ai_model.lineEdit().setCursorPosition(0)
            self.ai_model.blockSignals(False)


class SettingsDialog(BaseDialog):
    last_page = 0                                       # reopen on the page you used last

    def __init__(self, parent, controller):
        super().__init__(parent, "Settings", resizable=True)
        self.c = controller
        # A sidebar of pages, one shown at a time: fits a 1280x800 laptop with room to spare, and Done stays put.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(0)
        main = QHBoxLayout()
        main.setSpacing(18)
        outer.addLayout(main, 1)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setAccessibleName("Settings pages")
        self.nav.setFixedWidth(150)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main.addWidget(self.nav)
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        self._pages = {}
        reading, ai_page = self._page("Reading", "mic"), self._page("AI", "spark")
        look, privacy, system = self._page("Look", "ghost"), self._page("Privacy", "shield"), self._page("System", "settings")
        self.nav.currentRowChanged.connect(self._show_page)

        self._build_reading(reading)
        self._build_privacy(privacy)
        self._build_look(look)
        self._build_ai(ai_page)
        self._build_system(system)
        for lay in self._pages.values():
            lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 12, 0, 0)
        foot.addWidget(label("Changes apply as you make them.", "muted"))
        foot.addStretch(1)
        done = button("Done", self.accept, primary=True)
        done.setToolTip("Close Settings  (Esc)")
        foot.addWidget(done)
        outer.addLayout(foot)
        self.nav.setCurrentRow(max(0, min(self.nav.count() - 1, SettingsDialog.last_page)))
        self.resize(780, 560)
        self.setMinimumSize(640, 420)
        self._dl = None

    def _page(self, name, icon):
        if name not in self._pages:
            body = QWidget()
            lay = QVBoxLayout(body)
            lay.setContentsMargins(0, 0, 8, 0)
            lay.setSpacing(6)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            area.setWidget(body)
            self.stack.addWidget(area)
            it = QListWidgetItem(icons.icon(icon, "#C9CFDD", 18), name)
            self.nav.addItem(it)
            self._pages[name] = lay
        return self._pages[name]

    def _build_reading(self, page):
        s = self.c.cfg.s
        card = Card()
        card.slider("Speed", 40, 400, s.wpm, lambda v: "%d wpm" % v, lambda v: self._set("wpm", v))
        card.row("3-2-1 countdown", switch(s.countdown, lambda v: self._set("countdown", v)))
        _section(page, card, "Reading")

        card = Card()
        card.row("Voice Follow", switch(s.voice_follow, lambda v: v != s.voice_follow and self.c.prompter.toggle_voice()),
                 "Scrolls with your words. 100% offline.")
        card.row("Coach report after each run", switch(s.coach, lambda v: self._set("coach", v)))
        self.mic = QComboBox()
        self.mic.setAccessibleName("Microphone")
        self.mic.setMinimumWidth(190)
        self.mic.setMaximumWidth(220)
        self.mic.addItem("System default", "")
        from ...voice import list_microphones
        for m in list_microphones():
            self.mic.addItem(m, m)
        i = self.mic.findData(s.mic_device)
        if i < 0 and s.mic_device:
            self.mic.addItem(s.mic_device + " (unplugged)", s.mic_device)
            i = self.mic.count() - 1
        self.mic.setCurrentIndex(max(0, i))
        self.mic.currentIndexChanged.connect(lambda _: self._set("mic_device", self.mic.currentData() or ""))
        lat = self.c.voice.latency_ms
        card.row("Microphone", self.mic, ("Measured latency %d ms" % lat) if lat else
                 "Wired mics react fastest.")
        _section(page, card, "Voice Follow")

        from ... import tts
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
        self.voice_hint = card.row("Voice", self.voice_box, "Offline neural voices.")
        self.preview = button("Play sample", self._preview)
        self.preview.setProperty("compact", True)
        card.row("Hear it", self.preview)
        _section(page, card, "Read aloud")

    def _build_privacy(self, page):
        s = self.c.cfg.s
        level, note = native.capture_support()
        card = Card()
        card.row("Hide from screen share", switch(s.hide_from_capture, lambda v: self._set("hide_from_capture", v)),
                 note)
        card.row("Phone remote on this Wi-Fi", switch(s.remote_enabled, self._remote), "Protected by a PIN.")
        card.row("Phone can view my screen", switch(s.phone_screen, lambda v: self._set("phone_screen", v)),
                 "Live view and AI chat on your paired phone.")
        _section(page, card, "Privacy")

    def _build_look(self, page):
        s = self.c.cfg.s
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
        _section(page, card, "Prompter")

        card = Card()
        self.glass_box = QComboBox()
        self.glass_box.setAccessibleName("Window see-through")
        self.glass_box.setMinimumWidth(170)
        for lvl, name in GLASS_LEVELS:
            self.glass_box.addItem(name, lvl)
        self.glass_box.setCurrentIndex(max(0, self.glass_box.findData(s.window_glass)))
        self.glass_box.currentIndexChanged.connect(lambda _: self.c.set_window_glass(self.glass_box.currentData()))
        card.row("See-through", self.glass_box, "Every window: settings, copilot, AI. Text stays sharp.")
        card.row("Solid while I use it", switch(s.glass_solid_hover, lambda v: self._set_glass_hover(v)),
                 "Turns solid under the mouse, see-through again when you move away.")
        _section(page, card, "Windows")

    def _build_ai(self, page):
        s = self.c.cfg.s
        card = Card()
        self.ai = AIKeyPanel(self)
        self.ai.build(card)
        _section(page, card, "AI assistant")

        from ...listen import system_audio_supported
        card = Card()
        hear = switch(s.copilot_system_audio and system_audio_supported(),
                      lambda v: self._set("copilot_system_audio", v))
        hear.setEnabled(system_audio_supported())
        card.row("Hear the other side", hear, "Transcribe the call's sound as Them." if system_audio_supported()
                 else "This system can't share its sound; your microphone only.")
        card.row("Smart answers", switch(s.copilot_smart, lambda v: self._set("copilot_smart", v)),
                 "Suggests answers to their questions.")
        card.row("Copilot sees my screen", switch(s.copilot_screen, lambda v: self._set("copilot_screen", v)),
                 "Only when you press an action.")
        b = button("Edit" + ELLIPSIS, self._copilot_context)
        b.setProperty("compact", True)
        card.row("Context", b, "Your notes, files and custom modes.")
        b = button("Open", self._meetings)
        b.setProperty("compact", True)
        card.row("Meeting history", b, "Notes, transcripts, follow-up emails.")
        _section(page, card, "Meeting copilot")

    def _build_system(self, page):
        s, controller = self.c.cfg.s, self.c
        card = Card()
        card.row("Check for updates", switch(s.auto_update, lambda v: self._set("auto_update", v)),
                 "Daily, from GitHub. Sends nothing about you.")
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
        if hasattr(controller, "hotkey_summary"):
            b = button("Show", lambda: (self.accept(), QTimer.singleShot(0, controller.prompter.toggle_help)))
            b.setProperty("compact", True)
            card.row("Shortcuts", b, controller.hotkey_summary())
            b.setToolTip(controller.hotkey_report())
        _section(page, card, "System")

    def _set(self, key, value):
        setattr(self.c.cfg.s, key, value)
        self.c.settings_changed(live=True)

    def apply_glass(self):
        super().apply_glass()
        box = getattr(self, "glass_box", None)              # keep the menu in step with the header's glass button
        if box is not None:
            i = min(range(box.count()), key=lambda k: abs(box.itemData(k) - self.level()))
            box.blockSignals(True)
            box.setCurrentIndex(i)
            box.blockSignals(False)

    def _show_page(self, row):
        if row >= 0:
            self.stack.setCurrentIndex(row)
            SettingsDialog.last_page = row

    def _set_glass_hover(self, on):
        self._set("glass_solid_hover", on)
        self.c.set_window_glass(self.c.cfg.s.window_glass)

    def _copilot_context(self):
        from ..copilot import SetupDialog
        SetupDialog(self, self.c).exec()

    def _meetings(self):
        self.accept()                                  # history is a normal window; Settings is modal
        QTimer.singleShot(0, self.c.open_meetings)

    def _remote(self, on):
        self.c.cfg.s.remote_enabled = on
        self.c.set_remote_enabled(on)

    def _autostart(self, on):
        self.c.cfg.s.start_with_windows = on
        native.set_autostart(on)
        self.c.settings_changed()

    # ---- natural voices
    def _voice_changed(self, _):
        from ... import tts
        vid = self.voice_box.currentData()
        if vid != tts.SYSTEM and tts.voice_file(vid) is None:
            return self._download(vid)
        self._set("tts_voice", vid)
        self.c.speaker.preload(vid)

    def _download(self, vid):
        import threading
        from ... import tts
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
        from ... import engine
        sample = ("Hi, I'm your Glass Prompter voice. I read at your pace, and the prompter follows every word.")
        lines = engine.wrap(sample, 10000, len)
        if self.c.speaker.speaking:
            self.c.speaker.stop()
            return
        self.c.speaker.speak(lines, self.c.cfg.s.wpm, self.c.cfg.s.tts_voice)
