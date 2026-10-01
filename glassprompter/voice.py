"""Voice Follow audio engine: microphone -> offline Vosk recognizer -> heard words.

Everything runs on background threads and talks to the UI only through Qt signals
(queued across threads). Nothing ever leaves the computer.
"""
import array
import json
import logging
import os
import queue
import threading

from PySide6.QtCore import QObject, Signal

from . import paths
from .tracking import norm_words

log = logging.getLogger(__name__)

try:
    import vosk
    vosk.SetLogLevel(-1)
except Exception:                     # optional dependency
    vosk = None
try:
    import sounddevice as sd
except Exception:
    sd = None


class VoiceEngine(QObject):
    heard = Signal(list)          # most recent recognized words (normalized)
    level = Signal(float)         # 0..1 microphone level, ~10x per second
    status = Signal(str)          # "loading" | "listening" | "stopped"
    failed = Signal(str)          # human-readable error

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.listening = False

    @staticmethod
    def available():
        return vosk is not None and sd is not None and paths.model_dir() is not None

    @staticmethod
    def why_unavailable():
        if vosk is None or sd is None:
            return "Voice Follow components are missing from this install."
        if paths.model_dir() is None:
            return "The speech model is missing from this install."
        return ""

    def start(self, vocabulary):
        if self.listening:
            return
        if not self.available():
            self.failed.emit(self.why_unavailable())
            return
        self._stop.clear()
        self.listening = True
        vocab = sorted(set(vocabulary))
        self._thread = threading.Thread(target=self._run, args=(vocab,), name="voice", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.listening = False

    def _load_model(self):
        with self._model_lock:
            if self._model is None:
                self.status.emit("loading")
                self._model = vosk.Model(paths.model_dir())
            return self._model

    def _run(self, vocab):
        audio = queue.Queue(maxsize=50)
        try:
            model = self._load_model()
            dev = sd.query_devices(kind="input")
            rate = int(dev["default_samplerate"]) or 16000
            # Restricting the recognizer to the script's own words makes it far more accurate.
            grammar = json.dumps(vocab + ["[unk]"]) if vocab else None
            rec = vosk.KaldiRecognizer(model, rate, grammar) if grammar else vosk.KaldiRecognizer(model, rate)

            def callback(indata, frames, t, st):
                try:
                    audio.put_nowait(bytes(indata))
                except queue.Full:
                    pass

            with sd.RawInputStream(samplerate=rate, blocksize=int(rate * 0.1), dtype="int16", channels=1,
                                   callback=callback):
                self.status.emit("listening")
                log.info("Voice Follow listening (%d Hz, %d words)", rate, len(vocab))
                last = None
                while not self._stop.is_set():
                    try:
                        data = audio.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    samples = array.array("h", data)
                    if samples:
                        peak = max(abs(min(samples)), abs(max(samples)))
                        self.level.emit(min(1.0, peak / 12000.0))
                    if rec.AcceptWaveform(data):
                        words = norm_words(json.loads(rec.Result()).get("text", "").replace("[unk]", ""))
                    else:
                        words = norm_words(json.loads(rec.PartialResult()).get("partial", "").replace("[unk]", ""))
                    if words and words != last:
                        last = words
                        self.heard.emit(words)
        except Exception as ex:
            msg = str(ex)
            if "Error querying device" in msg or "Invalid device" in msg or "-9996" in msg:
                msg = "No microphone found. Plug one in or check Windows sound settings."
            elif "-9999" in msg or "Unanticipated host error" in msg:
                msg = ("Windows blocked the microphone. Allow it in Settings > Privacy & security > Microphone "
                       "> Let desktop apps access your microphone.")
            log.warning("Voice Follow stopped: %s", ex)
            self.failed.emit(msg)
        finally:
            self.listening = False
            self.level.emit(0.0)
            self.status.emit("stopped")
