"""Application bootstrap and controller: wires the prompter, library, remote server, tray,
global hotkeys, drop folder and single-instance handling together."""
import argparse
import ctypes
import getpass
import logging
import os
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_ID, APP_NAME, ORG, __version__, config, engine, paths, scripts, win32
from . import log as logsetup
from .server import RemoteServer
from .voice import VoiceEngine
from .tts import Speaker
from .ui import icon as appicon
from .ui import theme
from .ui.dialogs import AboutDialog, LibraryDialog, PhoneDialog, ReportDialog, SettingsDialog, WelcomeDialog
from .ui.prompter import Prompter

log = logging.getLogger("glassprompter")

HOTKEYS = {1: ("SPACE", "play"), 2: ("UP", "faster"), 3: ("DOWN", "slower"), 4: ("LEFT", "back"),
           5: ("RIGHT", "ahead"), 6: ("R", "restart"), 7: ("H", "toggle"), 8: ("E", "library"),
           9: ("V", "voice"), 10: ("G", "ghost"), 11: ("PGUP", "prev_section"), 12: ("PGDN", "next_section")}
DROP_EXT = (".txt", ".md", ".docx")
WELCOME_SCRIPT = """Welcome to Glass Prompter.

Read the line in the amber band. It sits right under your camera, so your eyes stay on your audience.

[LOOK AT THE CAMERA]

Press Space, or Ctrl+Alt+Space from any app, to play and pause. Up and Down change the speed.

[PAUSE]

Put [PAUSE] on its own line and the prompter waits for you. Anything else in square brackets shows up as a cue.

Press E to open your script library, or P to send scripts from your phone."""

DROP_README = """Glass Prompter drop folder
==========================

Save a .txt, .md or .docx file in this folder and Glass Prompter adds it to your
script library and loads it automatically. Saving the same file again updates it.

If this folder is inside OneDrive, you can edit scripts from your phone or any computer.
Files whose names start with an underscore (like this one) are ignored.
"""


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


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            hid = win32.parse_hotkey_msg(message)
            if hid is not None:
                QTimer.singleShot(0, lambda: self.callback(hid))
                return True, 0
        return False, 0


class Controller(QObject):
    def __init__(self, app, args):
        super().__init__()
        self.app = app
        self.cfg = config.Config()
        self.cfg.load()
        self.store = scripts.ScriptStore(paths.database_path())
        self.server = None
        self.network_category = ""
        self.dialog = None
        self.drop_mtimes = {}
        self.hotkeys_ok = []

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
        self.prompter.rehearsalFinished.connect(self._rehearsal_done)
        self.speaker = Speaker()
        self.speaker.finished.connect(self.prompter.on_read_aloud_done)
        self.prompter.readAloudRequested.connect(
            lambda on: self.speaker.speak(self.prompter.script_text, self.cfg.s.wpm) if on else self.speaker.stop())

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
        if self.cfg.s.start_with_windows != win32.is_autostart():
            win32.set_autostart(self.cfg.s.start_with_windows)

        self.hotkey_filter = HotkeyFilter(self.on_hotkey)
        app.installNativeEventFilter(self.hotkey_filter)
        self.register_hotkeys()

        if not args.background:
            self.prompter.show_window()
        if not self.cfg.s.first_run_done:
            QTimer.singleShot(400, self.first_run)
        if args.file:
            QTimer.singleShot(300, lambda: self.import_path(args.file))
        log.info("Ready (remote=%s, hotkeys=%d/%d)", bool(self.server and self.server.running),
                 sum(self.hotkeys_ok), len(HOTKEYS))

    # ------------------------------------------------------------ voice follow
    def _listen(self, on):
        if on:
            self.voice.start(self.prompter.vwords)
        else:
            self.voice.stop()

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
        self.network_category = win32.network_category()
        log.info("Network category: %s", self.network_category or "unknown")

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
         "read_aloud": p.toggle_read_aloud,
         "next_section": lambda: p.jump_section(1), "prev_section": lambda: p.jump_section(-1)}[action]()
        self.schedule_publish()

    # ------------------------------------------------------------ hotkeys
    def register_hotkeys(self):
        hwnd = self.prompter.hwnd()
        self.hotkeys_ok = [win32.register_hotkey(hwnd, hid, win32.VK[key]) for hid, (key, _) in HOTKEYS.items()]
        # Another app owns some combos? Fall back to watching the keyboard for those so they still work.
        self.poll_ids = [hid for hid, ok in zip(HOTKEYS, self.hotkeys_ok) if not ok]
        self._poll_prev = {}
        if self.poll_ids:
            self.poll_timer = QTimer(self, interval=30, timeout=self.poll_hotkeys)
            self.poll_timer.start()

    def poll_hotkeys(self):
        held = win32.key_down(win32.VK_CONTROL) and win32.key_down(win32.VK_MENU)
        for hid in self.poll_ids:
            down = held and win32.key_down(win32.VK[HOTKEYS[hid][0]])
            if down and not self._poll_prev.get(hid):
                self.on_hotkey(hid)
            self._poll_prev[hid] = down

    def hotkey_report(self):
        names = {"SPACE": "Space", "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
                 "PGUP": "PgUp", "PGDN": "PgDn"}
        taken = ["Ctrl+Alt+" + names.get(HOTKEYS[h][0], HOTKEYS[h][0]) for h in getattr(self, "poll_ids", [])]
        if not taken:
            return "All Ctrl+Alt shortcuts are active."
        return ("%s %s also used by another app on this PC. Glass Prompter still responds to %s, "
                "but that app may react too." % (", ".join(taken), "is" if len(taken) == 1 else "are",
                                                   "it" if len(taken) == 1 else "them"))

    def unregister_hotkeys(self):
        hwnd = self.prompter.hwnd()
        for hid in HOTKEYS:
            win32.unregister_hotkey(hwnd, hid)

    def on_hotkey(self, hid):
        action = HOTKEYS.get(hid, (None, None))[1]
        p = self.prompter
        if action == "toggle":
            return p.toggle_window()
        if action == "library":
            return self.open_library()
        if action == "ghost":
            return p.toggle_ghost()
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
        self.show_dialog(AboutDialog(None))

    # ------------------------------------------------------------ tray
    def setup_tray(self):
        self.tray = QSystemTrayIcon(appicon.app_icon(), self)
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
        m.addAction(QAction("About Glass Prompter", m, triggered=self.open_about))
        m.addAction(QAction("Quit", m, triggered=self.quit))
        m.aboutToShow.connect(self.update_tray)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.update_tray()

    def _tray_activated(self, reason):
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
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GlassPrompter.App")
    except Exception:
        pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.app_qss())
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
