"""Voice Follow audio engine: microphone -> offline Vosk recognizer -> heard words.

Built for low latency and for never freezing mid-take (the #1 complaint about voice-scrolling prompters):
  * 16 kHz capture when the device allows it (no resampling work), 40 ms blocks (was 100 ms)
  * if the recognizer ever falls behind, queued audio is merged and fed in one go so it catches up
    instead of drifting seconds behind the speaker
  * a watchdog reopens the microphone if audio stops arriving (Bluetooth hiccup, device switch, sleep)
  * measured processing latency is published so the UI can show it

Everything runs on background threads and talks to the UI only through Qt signals. Nothing leaves the computer.
"""
import array
import json
import logging
import queue
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import paths
from . import platform as native
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

BLOCK_SEC = 0.04
PREFERRED_RATE = 16000
STALL_SEC = 2.5
MAX_RECONNECTS = 4


_SKIP = ("Sound Mapper", "Primary Sound Capture")


def _full_name(name, devs):
    """Windows MME truncates names to 31 characters; show the full name another audio API reports."""
    longer = [d["name"] for d in devs if d["name"].startswith(name.rstrip())]
    return max(longer, key=len) if longer else name


def list_microphones():
    """Real input devices on the default audio API (no MME/DirectSound/WASAPI duplicates), default first."""
    if sd is None:
        return []
    try:
        default = sd.query_devices(kind="input")
        api = default.get("hostapi", 0)
        devs = sd.query_devices()
    except Exception:
        return []
    names = []
    for d in devs:
        if d.get("max_input_channels", 0) <= 0 or d.get("hostapi", api) != api:
            continue
        if any(k in d["name"] for k in _SKIP):
            continue
        full = _full_name(d["name"], devs)
        if full not in names:
            names.append(full)
    first = _full_name(default["name"], devs)
    if first in names:
        names.remove(first)
        names.insert(0, first)
    return names


def _device_index(name):
    """Index of the saved microphone on the default audio API; None (system default) if it's unplugged."""
    if not name or sd is None:
        return None
    try:
        api = sd.query_devices(kind="input").get("hostapi", 0)
        devs = list(enumerate(sd.query_devices()))
        inputs = [(i, d) for i, d in devs if d.get("max_input_channels", 0) > 0]
        for i, d in inputs:
            if d.get("hostapi") == api and (d["name"] == name or name.startswith(d["name"].rstrip())):
                return i
        for i, d in inputs:
            if d["name"] == name:
                return i
    except Exception:
        pass
    return None


def pick_rate(device):
    """16 kHz if the device takes it (what the model wants), otherwise its native rate."""
    try:
        sd.check_input_settings(device=device, samplerate=PREFERRED_RATE, channels=1, dtype="int16")
        return PREFERRED_RATE
    except Exception:
        info = sd.query_devices(device) if device is not None else sd.query_devices(kind="input")
        return int(info["default_samplerate"]) or PREFERRED_RATE


class VoiceEngine(QObject):
    heard = Signal(list)          # most recent recognized words (normalized)
    utterance = Signal(list)      # a finished phrase (for the Rehearsal Coach)
    level = Signal(float)         # 0..1 microphone level
    status = Signal(str)          # "loading" | "listening" | "reconnecting" | "stopped"
    failed = Signal(str)          # human-readable error
    stats = Signal(dict)          # {"latency_ms": int, "rate": int, "device": str}

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.listening = False
        self.device_name = ""
        self.latency_ms = 0

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

    def preload(self):
        """Load the model in the background at startup so the first Space press starts instantly."""
        if self.available() and self._model is None:
            threading.Thread(target=self._load_model, args=(False,), name="voice-preload", daemon=True).start()

    def start(self, vocabulary, device_name=""):
        if self.listening:
            return
        if not self.available():
            self.failed.emit(self.why_unavailable())
            return
        self._stop.clear()
        self.listening = True
        self.device_name = device_name or ""
        vocab = sorted(set(vocabulary))
        self._thread = threading.Thread(target=self._run, args=(vocab,), name="voice", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.listening = False

    def _load_model(self, announce=True):
        with self._model_lock:
            if self._model is None:
                if announce:
                    self.status.emit("loading")
                self._model = vosk.Model(paths.model_dir())
            return self._model

    def _recognizer(self, model, rate, vocab):
        # Restricting the recognizer to the script's own words makes it far more accurate.
        from .coach import FILLERS
        vocab = sorted(set(vocab) | FILLERS | {"you", "know", "i", "mean", "sort", "kind", "of"})
        grammar = json.dumps(vocab + ["[unk]"]) if vocab else None
        rec = vosk.KaldiRecognizer(model, rate, grammar) if grammar else vosk.KaldiRecognizer(model, rate)
        return rec, len(vocab)

    def _run(self, vocab):
        reconnects = 0
        try:
            model = self._load_model()
            while not self._stop.is_set():
                outcome = self._listen_once(model, vocab)
                if outcome == "stopped":
                    break
                reconnects += 1
                if reconnects > MAX_RECONNECTS:
                    raise RuntimeError("The microphone keeps dropping out. Check its connection.")
                self.status.emit("reconnecting")
                log.warning("Microphone stalled; reopening (attempt %d)", reconnects)
                time.sleep(0.4)
        except Exception as ex:
            log.warning("Voice Follow stopped: %s", ex)
            self.failed.emit(native.mic_error(str(ex)))
        finally:
            self.listening = False
            self.level.emit(0.0)
            self.status.emit("stopped")

    def _listen_once(self, model, vocab):
        audio = queue.Queue(maxsize=200)
        device = _device_index(self.device_name)
        rate = pick_rate(device)
        rec, nwords = self._recognizer(model, rate, vocab)
        rec.SetWords(False)

        def callback(indata, frames, t, st):
            try:
                audio.put_nowait((time.perf_counter(), bytes(indata)))
            except queue.Full:
                pass

        with sd.RawInputStream(samplerate=rate, blocksize=int(rate * BLOCK_SEC), dtype="int16", channels=1,
                               device=device, latency="low", callback=callback) as stream:
            name = sd.query_devices(stream.device)["name"] if stream.device is not None else "default"
            self.status.emit("listening")
            log.info("Voice Follow listening on %s (%d Hz, %d ms blocks, %d words)", name, rate,
                     int(BLOCK_SEC * 1000), nwords)
            last, last_audio, lat = None, time.perf_counter(), []
            while not self._stop.is_set():
                try:
                    t0, data = audio.get(timeout=0.25)
                except queue.Empty:
                    if time.perf_counter() - last_audio > STALL_SEC:
                        return "stalled"
                    continue
                last_audio = time.perf_counter()
                # catch up: if we fell behind, merge everything queued into one feed
                while True:
                    try:
                        _, more = audio.get_nowait()
                        data += more
                    except queue.Empty:
                        break
                samples = array.array("h", data[-int(rate * BLOCK_SEC) * 2:])
                if samples:
                    self.level.emit(min(1.0, max(abs(min(samples)), abs(max(samples))) / 12000.0))
                if rec.AcceptWaveform(data):
                    words = norm_words(json.loads(rec.Result()).get("text", "").replace("[unk]", ""))
                    if words:
                        self.utterance.emit(words)
                else:
                    words = norm_words(json.loads(rec.PartialResult()).get("partial", "").replace("[unk]", ""))
                if words and words != last:
                    last = words
                    self.heard.emit(words)
                lat.append((time.perf_counter() - t0) * 1000 + BLOCK_SEC * 500)   # processing + half a block
                if len(lat) >= 25:
                    self.latency_ms = int(sorted(lat)[len(lat) // 2])
                    self.stats.emit({"latency_ms": self.latency_ms, "rate": rate, "device": name})
                    lat.clear()
        return "stopped"
