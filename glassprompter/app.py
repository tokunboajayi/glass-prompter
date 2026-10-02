"""Application bootstrap and controller: wires the prompter, library, remote server, tray,
global hotkeys, drop folder and single-instance handling together."""
import argparse
import getpass
import logging
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_ID, APP_NAME, ORG, __version__, config, engine, paths, scripts
from . import log as logsetup
from . import platform as native
from .server import RemoteServer
from .voice import VoiceEngine
from .tts import Speaker
from .ui import icon as appicon
from .ui import icons, theme
from .ui.dialogs import AboutDialog, LibraryDialog, PhoneDialog, ReportDialog, SettingsDialog, WelcomeDialog
from .ui.prompter import Prompter

log = logging.getLogger("glassprompter")

HOTKEYS = {1: ("SPACE", "play"), 2: ("UP", "faster"), 3: ("DOWN", "slower"), 4: ("LEFT", "back"),
           5: ("RIGHT", "ahead"), 6: ("R", "restart"), 7: ("H", "toggle"), 8: ("E", "library"),
           9: ("V", "voice"), 10: ("G", "ghost"), 11: ("PGUP", "prev_section"), 12: ("PGDN", "next_section"),
           13: ("LBRACKET", "ghost_less"), 14: ("RBRACKET", "ghost_more")}
assert all(k in native.HOTKEY_KEYS for k, _ in HOTKEYS.values())
DROP_EXT = (".txt", ".md", ".docx")
WELCOME_SCRIPT = """Welcome to Glass Prompter.

Read the line in the glowing band. It sits right under your camera, so your eyes stay on your audience.

[LOOK AT THE CAMERA]

Press Space, or %s+Space from any app, to play and pause. Up and Down change the speed.

[PAUSE]

Put [PAUSE] on its own line and the prompter waits for you. Anything else in square brackets shows up as a cue.

Press E to open your script library, or P to send scripts from your phone.

# Voice Follow

Press V, then Space, and just talk. The script follows your voice, word by word, entirely offline.""" % native.MOD

DROP_README = """Glass Prompter drop folder
==========================

Save a .txt, .md or .docx file in this folder and Glass Prompter adds it to your
script library and loads it automatically. Saving the same file again updates it.

If this folder syncs with OneDrive or iCloud Drive, you can edit scripts from your phone or any computer.
Files whose names start with an underscore (like this one) are ignored.
"""


class UpdateSignals(QObject):
    found = Signal(dict)
    none = Signal(bool)          # True if the user asked (show "you're up to date")
    failed = Signal(str, bool)
    progress = Signal(float)
    ready = Signal(str)


class Bridge(QObject):
    """Thread-safe entry point for the remote server: it emits, the UI thread handles (queued)."""
    controlRequested = Signal(str)
    loadRequested = Signal(int, str)
    scriptChanged = Signal(int)

    def control(self, action):
        self.controlRequested.emit(action)

    def load_script(self, sid, source):
        self.loadRequested.emit(int(sid), str(source))

    def script_changed(self, sid):
        self.scriptChanged.emit(int(sid))


class Controller(QObject):
    def __init__(self, app, args):
        super().__init__()
        self.app = app
        self.cfg = config.Config()
        self.cfg.load()
        self.store = scripts.ScriptStore(paths.database_path())
        self.server = None
        self.dialog = None
        self.drop_mtimes = {}
        self.network_note = ""

        self.prompter = Prompter(self.cfg.s)
        self.prompter.paste_requested = self.paste_text
        self.prompter.requestLibrary.connect(self.open_library)
        self.prompter.requestPhone.connect(self.open_phone)
        self.prompter.requestSettings.connect(self.open_settings)
        self.prompter.settingsChanged.connect(self.settings_changed)
        self.prompter.stateChanged.connect(self.schedule_publish)
        self.prompter.pendingConsumed.connect(self._pending_loaded)

        self.voice = VoiceEngine()
        self.voice.heard.connect(self.prompter.on_heard)
        self.voice.level.connect(self.prompter.on_level)
        self.voice.status.connect(self.prompter.on_voice_status)
        self.voice.failed.connect(self._voice_failed)
        self.prompter.listenRequested.connect(self._listen)
        self.voice.utterance.connect(self.prompter.on_utterance)
        self.voice.stats.connect(self.prompter.on_voice_stats)
        self.prompter.rehearsalFinished.connect(self._rehearsal_done)
        self.speaker = Speaker()
        self.speaker.finished.connect(self.prompter.on_read_aloud_done)
        self.speaker.progress.connect(self.prompter.on_tts_progress)
        self.speaker.status.connect(self.prompter.on_tts_status)
        self.speaker.failed.connect(lambda m: self.prompter.toast(m, theme.T.bad, 5))
        self.prompter.readAloudRequested.connect(self._read_aloud)

        self.save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.cfg.save)
        self.publish_timer = QTimer(self, singleShot=True, interval=80, timeout=self.publish)
        self.tick = QTimer(self, interval=1000, timeout=self.periodic)
        self.tick.start()
        self.drop_timer = QTimer(self, interval=2000, timeout=self.scan_drop)

        self.bridge = Bridge()
        self.bridge.controlRequested.connect(self.remote_control)
        self.bridge.loadRequested.connect(lambda sid, src: self.load_script(sid, src))
        self.bridge.scriptChanged.connect(self.remote_script_changed)

        self._first_script()
        self.setup_tray()
        self.setup_drop()
        if self.cfg.s.remote_enabled:
            self.start_server()
        QTimer.singleShot(1200, self._probe_network)
        QTimer.singleShot(1500, self.voice.preload)             # first Space press starts listening instantly
        QTimer.singleShot(2500, lambda: self.speaker.preload(self.cfg.s.tts_voice))
        QTimer.singleShot(4000, self._backup)
        self.update = None
        self.updating = False
        self.upd = UpdateSignals()
        self.upd.found.connect(self._update_found)
        self.upd.none.connect(lambda asked: asked and self.prompter.toast(
            "You're on the latest version (%s)" % __version__, theme.T.ok))
        self.upd.failed.connect(lambda msg, asked: (log.info("Update check: %s", msg),
                                                    asked and self.prompter.toast(msg, theme.T.bad, 5)))
        self.upd.progress.connect(lambda f: self.prompter.toast("Downloading update  %d%%" % int(f * 100),
                                                                theme.T.aqua, 2))
        self.upd.ready.connect(self._update_ready)
        if self.cfg.s.auto_update:
            QTimer.singleShot(8000, lambda: self.check_updates(False))
        if self.cfg.s.start_with_windows != native.is_autostart():
            native.set_autostart(self.cfg.s.start_with_windows)

        self.hotkeys = native.make_hotkeys(app, self.on_hotkey, self.prompter)
        self.register_hotkeys()

        if not args.background:
            self.prompter.show_window()
        if not self.cfg.s.first_run_done:
            QTimer.singleShot(400, self.first_run)
        if args.file:
            QTimer.singleShot(300, lambda: self.import_path(args.file))
        log.info("Ready on %s (remote=%s, hotkeys=%d/%d, capture=%s)", native.OS,
                 bool(self.server and self.server.running), sum(self.hotkeys.ok.values()), len(HOTKEYS),
                 native.capture_support()[0])

    # ------------------------------------------------------------ voice follow
    def _listen(self, on):
        if on:
            self.voice.start(self.prompter.vwords, self.cfg.s.mic_device)
        else:
            self.voice.stop()

    # ------------------------------------------------------------ updates (GitHub Releases)
    def check_updates(self, asked=True):
        from . import updater

        def run():
            try:
                found = updater.check(force=asked, last_checked=self.cfg.s.last_update_check)
            except Exception as ex:
                self.upd.failed.emit("Couldn't check for updates (offline?)", asked)
                log.info("update check failed: %s", ex)
                return
            self.cfg.s.last_update_check = time.time()
            if found and (asked or found["version"] != self.cfg.s.skipped_version):
                self.upd.found.emit(found)
            else:
                self.upd.none.emit(asked)
        threading.Thread(target=run, name="update-check", daemon=True).start()

    def _update_found(self, update):
        self.update = update
        self.update_tray()
        self.prompter.toast("Glass Prompter %s is ready  %s  install it from the %s menu"
                            % (update["version"], theme.DOT, native.TRAY.split(" (")[0]), theme.T.aqua, 6)
        self.tray.showMessage(APP_NAME, "Version %s is available. Choose \"Update to %s\" in the menu."
                              % (update["version"], update["version"]), QSystemTrayIcon.MessageIcon.Information, 6000)

    def install_update(self):
        from . import updater
        if not self.update or self.updating:
            return
        u = self.update
        size = (u["installer"].get("size") or 0) / 1e6
        box = QMessageBox()
        box.setWindowTitle("Update Glass Prompter")
        box.setText("Install Glass Prompter %s?" % u["version"])
        box.setInformativeText("Downloads %.0f MB from GitHub and checks its fingerprint before installing. "
                               "Your scripts and settings stay exactly as they are." % size)
        ok = box.addButton("Download and install", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is skip:
            self.cfg.s.skipped_version = u["version"]
            self.update = None
            self.update_tray()
            self.save_timer.start()
            return
        if box.clickedButton() is not ok:
            return
        self.updating = True
        last = [0.0]

        def progress(f):
            if f - last[0] >= 0.1 or f >= 1.0:
                last[0] = f
                self.upd.progress.emit(f)

        def run():
            try:
                self.upd.ready.emit(updater.download(u, progress))
            except Exception as ex:
                self.updating = False
                self.upd.failed.emit("Update failed: %s" % ex, True)
        threading.Thread(target=run, name="update-download", daemon=True).start()

    def _update_ready(self, path):
        from . import updater
        self.updating = False
        if updater.install(path):
            log.info("Handing over to the installer: %s", path)
            self.quit()
        else:
            self.prompter.toast("Drag Glass Prompter into Applications to finish, then reopen it", theme.T.aqua, 8)

    def _read_aloud(self, on):
        p = self.prompter
        if not on:
            self.speaker.stop()
            return
        if not self.speaker.speak(p.lines, self.cfg.s.wpm, self.cfg.s.tts_voice, p.read_start_word()):
            p.stop_read_aloud()
            p.toast("Nothing to read here", theme.T.bad)
            return
        p.set_tts_follow(self.speaker.natural)

    def _rehearsal_done(self, report):
        sid = report.get("script_id") or 0
        history = self.store.rehearsals(sid, limit=8)
        if history:
            report["trend"] = report["score"] - history[0]["score"]
        self.store.add_rehearsal(sid, report)
        history = self.store.rehearsals(sid, limit=8)
        dlg = ReportDialog(None, report, history)
        self.show_dialog(dlg)
        if getattr(dlg, "again", False):
            self.prompter.restart()
            self.prompter.start_listening()

    def _voice_failed(self, msg):
        self.prompter.stop_listening(summary=False)
        self.prompter.toast(msg, theme.T.bad, 6)
        self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.MessageIcon.Warning, 6000)

    # ------------------------------------------------------------ startup helpers
    def _first_script(self):
        if self.store.count() == 0:
            legacy = os.path.join(os.path.dirname(paths.legacy_settings_path()), "last_script.txt")
            body = None
            if os.path.exists(legacy):
                try:
                    body = scripts.read_file(legacy)
                except Exception:
                    body = None
            if body and body.strip() and len(body.split()) > 3:
                self.store.create("My last script", body)
            self.store.create("Welcome to Glass Prompter", WELCOME_SCRIPT)
        sid = self.cfg.s.current_script_id
        s = self.store.get(sid) if sid else None
        if not s:
            s = self.store.get(self.store.list(limit=1)[0]["id"])
        self.prompter.set_script(s["body"], s["id"], s["title"])
        self.cfg.s.current_script_id = s["id"]

    def first_run(self):
        self.show_dialog(WelcomeDialog(None, self.cfg.s.drop_dir))
        self.cfg.s.first_run_done = True
        self.cfg.save()

    def _probe_network(self):
        def probe():                                   # may shell out (Windows) - never block the UI
            self.network_note = native.network_note()
        threading.Thread(target=probe, name="netprobe", daemon=True).start()

    def _backup(self):
        try:
            self.store.backup(paths.backup_dir())
        except Exception as ex:
            log.warning("Library backup failed: %s", ex)

    # ------------------------------------------------------------ settings & state
    def settings_changed(self, live=False):
        if live:
            self.prompter.apply_settings()
        self.save_timer.start()

    def schedule_publish(self):
        if not self.publish_timer.isActive():
            self.publish_timer.start()

    def publish(self):
        if self.server and self.server.running:
            self.server.publish_state(self.prompter.snapshot())
        self.update_tray()

    def periodic(self):
        connected = bool(self.server and self.server.running and self.server.connected())
        if connected != self.prompter.remote_connected:
            self.prompter.remote_connected = connected
            self.prompter.update()
        if self.prompter.playing:
            self.publish()

    # ------------------------------------------------------------ scripts
    def load_script(self, sid, source="your library"):
        s = self.store.get(sid)
        if not s:
            self.prompter.toast("That script no longer exists", theme.T.bad)
            return
        if not self.prompter.isVisible():
            self.prompter.show_window()
        if self.prompter.offer_script(s["body"], s["id"], s["title"], source):
            self._mark_current(s["id"])
        self.schedule_publish()

    def _pending_loaded(self):
        self._mark_current(self.prompter.script_id)

    def _mark_current(self, sid):
        self.cfg.s.current_script_id = sid
        self.store.touch(sid)
        self.save_timer.start()

    def remote_script_changed(self, sid):
        p = self.prompter
        if sid == p.script_id and not (p.playing or p.counting):
            s = self.store.get(sid)
            if s:
                p.set_script(s["body"], s["id"], s["title"])
                self.schedule_publish()

    def paste_text(self, text):
        if not text.strip():
            self.prompter.toast("Clipboard is empty", theme.T.bad)
            return
        try:
            s = self.store.create("", text)
        except scripts.ValidationError as ex:
            self.prompter.toast(str(ex), theme.T.bad)
            return
        self.load_script(s["id"], "the clipboard")

    def import_path(self, path):
        try:
            s = self.store.create(scripts.title_from_filename(path), scripts.read_file(path))
        except (scripts.ValidationError, OSError) as ex:
            self.prompter.toast("Couldn't open %s: %s" % (os.path.basename(path), ex), theme.T.bad, 4)
            return
        self.load_script(s["id"], os.path.basename(path))

    # ------------------------------------------------------------ drop folder (OneDrive friendly)
    def setup_drop(self):
        d = self.cfg.s.drop_dir
        try:
            os.makedirs(d, exist_ok=True)
            readme = os.path.join(d, "_How this folder works.txt")
            if not os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as f:
                    f.write(DROP_README)
        except OSError as ex:
            log.warning("Drop folder unavailable (%s): %s", d, ex)
            return
        self.drop_mtimes = self._drop_files()
        self.drop_timer.start()

    def _drop_files(self):
        out = {}
        d = self.cfg.s.drop_dir
        try:
            for name in os.listdir(d):
                if name.startswith(("_", "~$", ".")) or not name.lower().endswith(DROP_EXT):
                    continue
                p = os.path.join(d, name)
                try:
                    out[p] = os.path.getmtime(p)
                except OSError:
                    pass
        except OSError:
            pass
        return out

    def scan_drop(self):
        now = self._drop_files()
        for p, m in now.items():
            if self.drop_mtimes.get(p) != m:
                QTimer.singleShot(900, lambda p=p: self._import_drop(p))     # let OneDrive finish writing
        self.drop_mtimes = now

    def _import_drop(self, path):
        try:
            text = scripts.read_file(path)
            name = os.path.basename(path)
            s = self.store.upsert_source("file:" + name.lower(), scripts.title_from_filename(name), text)
        except (scripts.ValidationError, OSError) as ex:
            log.warning("Drop import failed for %s: %s", path, ex)
            return
        log.info("Imported drop file %s", os.path.basename(path))
        self.load_script(s["id"], os.path.basename(path))

    # ------------------------------------------------------------ remote server
    def start_server(self):
        self.stop_server()
        self.server = RemoteServer(self.store, self.bridge, self.cfg.s.pin, self.cfg.s.remote_port)
        if self.server.start():
            self.publish()
        return self.server.running

    def stop_server(self):
        if self.server:
            self.server.stop()
            self.server = None

    def set_remote_enabled(self, on):
        self.cfg.s.remote_enabled = on
        if on:
            self.start_server()
        else:
            self.stop_server()
        self.save_timer.start()

    def regenerate_pin(self):
        self.cfg.s.pin = config.new_pin()
        if self.server:
            self.server.set_pin(self.cfg.s.pin)
        self.cfg.save()

    def remote_control(self, action):
        p = self.prompter
        {"play": p.toggle_play, "restart": p.restart, "faster": lambda: p.change_wpm(10),
         "slower": lambda: p.change_wpm(-10), "back": lambda: p.nudge(-2), "ahead": lambda: p.nudge(2),
         "bigger": lambda: p.change_font(2), "smaller": lambda: p.change_font(-2),
         "hide": p.toggle_window, "voice": p.toggle_voice, "ghost": p.toggle_ghost,
         "ghost_less": lambda: p.change_ghost_opacity(-0.1), "ghost_more": lambda: p.change_ghost_opacity(0.1),
         "read_aloud": p.toggle_read_aloud,
         "next_section": lambda: p.jump_section(1), "prev_section": lambda: p.jump_section(-1)}[action]()
        self.schedule_publish()

    # ------------------------------------------------------------ hotkeys
    def register_hotkeys(self):
        for hid, (key, _) in HOTKEYS.items():
            self.hotkeys.register(hid, key)

    def hotkey_report(self):
        failed = [native.hotkey_label(native.MOD, HOTKEYS[h][0]) for h in self.hotkeys.failed()]
        if not failed:
            return "All %s shortcuts are active." % native.MOD
        if len(failed) == len(HOTKEYS) and native.OS != "windows":
            return "Global shortcuts aren't available on this system; the keys still work on the prompter."
        if native.OS == "windows":
            return ("%s %s also used by another app on this PC. Glass Prompter still responds, but that app may "
                    "react too." % (", ".join(failed), "is" if len(failed) == 1 else "are"))
        return "%s couldn't be registered (another app owns %s)." % (", ".join(failed),
                                                                    "it" if len(failed) == 1 else "them")

    def unregister_hotkeys(self):
        self.hotkeys.unregister_all()

    def on_hotkey(self, hid):
        action = HOTKEYS.get(hid, (None, None))[1]
        p = self.prompter
        if action == "toggle":
            return p.toggle_window()
        if action == "library":
            return self.open_library()
        if action == "ghost":
            return p.toggle_ghost()
        if action in ("ghost_less", "ghost_more"):          # works while clicks pass through
            return p.change_ghost_opacity(-0.1 if action == "ghost_less" else 0.1)
        if action == "voice":
            if not p.isVisible():
                p.show_window()
            return p.toggle_voice()
        if action in ("prev_section", "next_section"):
            return p.jump_section(-1 if action == "prev_section" else 1)
        if not p.isVisible():
            p.show_window()
        {"play": p.toggle_play, "faster": lambda: p.change_wpm(10), "slower": lambda: p.change_wpm(-10),
         "back": lambda: p.nudge(-2), "ahead": lambda: p.nudge(2), "restart": p.restart}[action]()

    # ------------------------------------------------------------ dialogs
    def show_dialog(self, dlg):
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return None
        self.dialog = dlg
        try:
            return dlg.exec()
        finally:
            self.dialog = None
            self.prompter.activateWindow()

    def open_library(self):
        self.show_dialog(LibraryDialog(None, self.store, self.prompter.script_id,
                                       lambda sid: self.load_script(sid, "your library")))
        self.remote_script_changed(self.prompter.script_id)

    def open_phone(self):
        if self.cfg.s.remote_enabled and (not self.server or not self.server.running):
            self.start_server()
        self.show_dialog(PhoneDialog(None, self))

    def open_settings(self):
        self.show_dialog(SettingsDialog(None, self))
        self.cfg.save()

    def open_about(self):
        self.show_dialog(AboutDialog(None, lambda: self.check_updates(True)))

    # ------------------------------------------------------------ tray
    def setup_tray(self):
        if native.OS == "macos":                        # monochrome template icon, like every menu-bar app
            ic = icons.icon("spark", "#000000", 18)
            ic.setIsMask(True)
        else:
            ic = appicon.app_icon()
        self.tray = QSystemTrayIcon(ic, self)
        m = QMenu()
        self.act_show = QAction("Hide prompter", m, triggered=self.prompter.toggle_window)
        self.act_play = QAction("Play", m, triggered=self.prompter.toggle_play)
        m.addAction(self.act_show)
        m.addAction(self.act_play)
        m.addSeparator()
        m.addAction(QAction("Scripts" + theme.ELLIPSIS, m, triggered=self.open_library))
        m.addAction(QAction("Phone remote" + theme.ELLIPSIS, m, triggered=self.open_phone))
        m.addAction(QAction("Settings" + theme.ELLIPSIS, m, triggered=self.open_settings))
        m.addSeparator()
        self.act_voice = QAction("Voice Follow (scroll as I speak)", m, checkable=True,
                                 triggered=lambda on: on != self.cfg.s.voice_follow and self.prompter.toggle_voice())
        self.act_ghost = QAction("Ghost mode (click through)", m, checkable=True,
                                 triggered=lambda on: self.prompter.set_ghost(on))
        self.act_mirror = QAction("Mirror text", m, checkable=True,
                                  triggered=lambda on: on != self.cfg.s.mirror and self.prompter.toggle_mirror())
        m.addAction(self.act_voice)
        m.addAction(QAction("Read script aloud", m, triggered=self.prompter.toggle_read_aloud))
        m.addAction(self.act_ghost)
        m.addAction(self.act_mirror)
        m.addSeparator()
        self.act_capture = QAction("Hide from screen share", m, checkable=True,
                                   triggered=lambda on: self._set_capture(on))
        m.addAction(self.act_capture)
        m.addAction(QAction("Move under the camera", m, triggered=self.prompter.reset_position))
        m.addSeparator()
        self.act_update = QAction("Update", m, triggered=self.install_update)
        self.act_update.setVisible(False)
        m.addAction(self.act_update)
        m.addAction(QAction("Check for updates", m, triggered=lambda: self.check_updates(True)))
        m.addAction(QAction("About Glass Prompter", m, triggered=self.open_about))
        m.addAction(QAction("Quit", m, triggered=self.quit))
        m.aboutToShow.connect(self.update_tray)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.update_tray()

    def _tray_activated(self, reason):
        if native.OS == "macos":
            return                                      # a click opens the menu on macOS
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.prompter.toggle_window()

    def _set_capture(self, on):
        if on != self.cfg.s.hide_from_capture:
            self.prompter.toggle_capture()

    def update_tray(self):
        p = self.prompter
        if not hasattr(self, "tray"):
            return
        self.act_show.setText("Hide prompter" if p.isVisible() else "Show prompter")
        self.act_play.setText("Pause" if (p.playing or p.counting) else "Play")
        self.act_capture.setChecked(self.cfg.s.hide_from_capture)
        if getattr(self, "update", None):
            self.act_update.setText("Update to %s%s" % (self.update["version"], theme.ELLIPSIS))
        self.act_update.setVisible(bool(getattr(self, "update", None)))
        self.act_voice.setChecked(self.cfg.s.voice_follow)
        self.act_ghost.setChecked(p.ghost)
        self.act_mirror.setChecked(self.cfg.s.mirror)
        state = "Listening" if p.listening else ("Playing" if p.playing else "Paused")
        self.tray.setToolTip("%s %s %s %s %s" % (APP_NAME, theme.DASH, state, theme.DOT, p.script_title[:40]))

    # ------------------------------------------------------------ lifecycle
    def show_from_other_instance(self, message):
        if message.startswith("open:"):
            self.import_path(message[5:])
        self.prompter.show_window()

    def quit(self):
        log.info("Quitting")
        self.voice.stop()
        self.speaker.stop()
        self.unregister_hotkeys()
        self.stop_server()
        self.cfg.save()
        self.store.close()
        self.tray.hide()
        self.app.quit()


# ---------------------------------------------------------------- entry point
def _single_instance(app, args):
    """Return a listening QLocalServer, or None if another copy is running (it gets our request)."""
    name = "%s-%s" % (APP_ID, getpass.getuser())
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(400):
        msg = ("open:" + os.path.abspath(args.file)) if args.file else "show"
        sock.write(msg.encode("utf-8"))
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return None
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.listen(name)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="glassprompter")
    parser.add_argument("file", nargs="?", help="script file to open (.txt, .md, .docx)")
    parser.add_argument("--background", action="store_true", help="start in the tray (used by autostart)")
    args = parser.parse_args(argv)

    logsetup.setup()
    native.set_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.app_qss())
    from .ui.glass import TipFilter
    app._tips = TipFilter(app)                      # every short tooltip becomes a glass tip
    app.installEventFilter(app._tips)
    app.setWindowIcon(appicon.app_icon())

    instance = _single_instance(app, args)
    if instance is None:
        log.info("Another instance is running; handed over and exiting")
        return 0
    ctl = Controller(app, args)

    def incoming():
        conn = instance.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(500)
        ctl.show_from_other_instance(bytes(conn.readAll()).decode("utf-8", "ignore"))
        conn.disconnectFromServer()
    instance.newConnection.connect(incoming)
    return app.exec()
