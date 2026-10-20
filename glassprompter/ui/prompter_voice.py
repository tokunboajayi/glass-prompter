"""Voice Follow and read-aloud behavior for the prompter window."""
import time

from PySide6.QtCore import QTimer

from .. import coach as coachlib, engine
from .theme import DOT, T


class PrompterVoice:
    def toggle_voice(self):
        self.cfg.voice_follow = not self.cfg.voice_follow
        if not self.cfg.voice_follow and self.listening:
            self.stop_listening(summary=False)
        if self.cfg.voice_follow:
            self.playing = self.counting = False
            self.toast("Voice Follow on  %s  press Space and start talking" % DOT, T.accent, 3)
        else:
            self.toast("Voice Follow off  %s  auto-scroll at %d wpm" % (DOT, self.cfg.wpm))
        self.settingsChanged.emit()
        self.sync_ui()

    def start_listening(self):
        if not self.vwords:
            return self.toast("This script has no words to follow", T.bad)
        if self.aligner.done:
            self.aligner.reset(-1)
            self.set_pos(0)
        if self.aligner.cursor < 0:
            # start from whatever line is on the reading line right now
            cur_line = engine.line_index(self.pos, self.lh)
            first = next((k for k, ln in enumerate(self.vline) if ln >= cur_line), 0)
            self.aligner.reset(first - 1)
        if self.reading_aloud:
            self.stop_read_aloud()
        self.listening = True
        self.voice_loading = True
        self.v_t0, self.v_count, self.live_wpm = None, 0, 0
        self.coach = coachlib.Coach(self.vwords)
        self.coach.start(time.monotonic(), self.aligner.cursor)
        self.v_target = self.pos
        self.listenRequested.emit(True)
        self.kick()
        self.sync_ui()

    def stop_listening(self, summary=True):
        was = self.listening
        self.listening = False
        self.voice_loading = False
        self.mic_level = 0.0
        self.listenRequested.emit(False)
        if was and summary and self.coach and self.v_count > 5:
            report = self.coach.report(time.monotonic())
            report["script_id"], report["title"] = self.script_id, self.script_title
            if self.cfg.coach:
                self.rehearsalFinished.emit(report)
            else:
                self.toast("Nice.  %s  %s  %d wpm" % (engine.fmt_secs(report["seconds"]), DOT, report["wpm"]), T.ok, 4)
        self.coach = None
        self.sync_ui()

    def on_utterance(self, words):
        if self.listening and self.coach:
            self.coach.on_utterance(words, time.monotonic())
            self.update()

    # ---- read aloud (text-to-speech rehearsal)
    def toggle_read_aloud(self):
        if self.reading_aloud:
            return self.stop_read_aloud()
        if self.listening:
            self.stop_listening(summary=False)
        self.reading_aloud = True
        self.counting = False
        self.tts_word, self.tts_follow, self.tts_preparing = -1, False, True
        self.playing = True                                     # system voice: scroll at wpm
        self.last = self.now()
        self.readAloudRequested.emit(True)
        self.sync_ui()

    def read_start_word(self):
        """First word on the line at the reading band, so Read Aloud starts where you are."""
        if self.pos <= 0.5 or not self.vline:
            return 0
        cur = engine.line_index(self.pos, self.lh)
        return next((k for k, ln in enumerate(self.vline) if ln >= cur), 0)

    def set_tts_follow(self, natural):
        """Natural voice: the band follows the spoken word instead of a fixed wpm."""
        self.tts_follow = bool(natural)
        if natural:
            self.playing = False
            self.v_target, self.v_vel = self.pos, 0.0
        self.kick()

    def on_tts_progress(self, word):
        if not self.reading_aloud:
            return
        self.tts_preparing = False
        self.tts_word = word
        if self.vline:
            self.v_target = min(self.maxpos(), engine.voice_target(self.vline, word) * self.lh)
        self.kick()

    def on_tts_status(self, status):
        self.tts_preparing = status == "preparing"
        self.update()

    def stop_read_aloud(self):
        self.reading_aloud = False
        self.tts_follow = False
        self.playing = False
        self.readAloudRequested.emit(False)
        self.sync_ui()

    def on_read_aloud_done(self):
        if self.reading_aloud:
            self.reading_aloud = False
            self.tts_follow = False
            self.playing = False
            self.toast("Finished reading", T.ok)
            self.sync_ui()

    def on_voice_status(self, status):
        self.voice_loading = status == "loading"
        if status == "stopped" and self.listening:
            self.listening = False
            self.sync_ui()
        self.update()

    def on_level(self, level):
        self.mic_level = level
        if self.listening:
            self.update()

    def on_heard(self, words):
        if not self.listening or not self.aligner:
            return
        self.voice_loading = False
        before = self.aligner.cursor
        c = self.aligner.update(words)
        if c > before and self.coach:
            self.coach.on_cursor(before, c)
        if c > before:
            now = time.monotonic()
            if self.v_t0 is None:
                self.v_t0 = now
            self.v_count += c - before
            mins = max(1e-6, (now - self.v_t0) / 60.0)
            if now - self.v_t0 > 4:
                self.live_wpm = int(round(self.v_count / mins))
        if c != before:
            self._retarget()
            self.stateChanged.emit()
        if self.aligner.done and not getattr(self, "_finishing", False):
            # wait a moment so the recognizer's final phrase (and any last filler) reaches the coach
            self._finishing = True
            QTimer.singleShot(1300, self._finish_run)

    def _finish_run(self):
        self._finishing = False
        if self.listening:
            self.stop_listening()
            if not self.cfg.coach:
                self.toast("End of script  %s  %d wpm average" % (DOT, self.live_wpm) if self.live_wpm
                           else "End of script", T.ok, 4)

    def _retarget(self):
        if self.vline:
            self.v_target = min(self.maxpos(), engine.voice_target(self.vline, self.aligner.cursor) * self.lh)
        self.kick()

    def on_voice_stats(self, stats):
        self.voice_latency = int(stats.get("latency_ms", 0))
