"""Read Aloud: the system voice (Windows SAPI, macOS `say`, espeak elsewhere) reads the script at your pace.

Runs as a separate process (no extra dependencies) so speech never blocks the UI.
"""
import os
import re
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal

from . import engine
from . import platform as native


def speakable(text):
    """Strip prompter markers so the voice reads only what you'd say."""
    out = []
    for ln in engine.normalize(text).split("\n"):
        s = ln.strip()
        if not s or engine.is_marker(s):
            continue
        out.append(s)
    return "\n".join(out)


def sapi_rate(wpm):
    """SAPI rate -10..10; 0 is roughly 170 wpm."""
    return max(-10, min(10, int(round((wpm - 170) / 14.0))))


class Speaker(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.proc = None
        self._file = None

    @property
    def speaking(self):
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def speak(self, text, wpm=150):
        self.stop()
        body = speakable(text)
        if not body:
            return False
        fd, self._file = tempfile.mkstemp(suffix=".txt", prefix="gp_tts_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        program, args = native.tts_command(self._file, wpm)
        self.proc = QProcess(self)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(lambda *_: self._done())
        self.proc.start(program, args)
        return True

    def stop(self):
        if self.speaking:
            self.proc.kill()
            self.proc.waitForFinished(1000)
        self._cleanup()

    def _done(self, *a):
        self._cleanup()
        self.finished.emit()

    def _cleanup(self):
        if self._file and os.path.exists(self._file):
            try:
                os.remove(self._file)
            except OSError:
                pass
        self._file = None
