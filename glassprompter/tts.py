"""Read Aloud: a natural, human-sounding neural voice reads your script and the prompter follows it word by word.

Natural voices use Piper (offline neural TTS, ~0.1x real time on a laptop CPU): sentences are synthesized one
ahead of playback, so speech starts in about half a second and never stutters. While audio plays we publish
which word is being spoken, so the reading band glides with the voice like karaoke instead of drifting.

If no natural voice is available the system voice is used (Windows SAPI, macOS `say`, espeak elsewhere).
"""
import logging
import os
import queue
import tempfile
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, QProcess, Signal

from . import engine, paths
from . import platform as native

log = logging.getLogger(__name__)

try:
    from piper import PiperVoice, SynthesisConfig
except Exception:                         # optional dependency
    PiperVoice = None
try:
    import sounddevice as sd
except Exception:
    sd = None

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/"
# id: (label, hugging-face path, natural words per minute at length_scale 1.0, bundled with the app)
VOICES = {
    "lessac": ("Lessac \u00b7 warm, US female", "en_US/lessac/medium/en_US-lessac-medium", 200, True),
    "ryan": ("Ryan \u00b7 clear, US male", "en_US/ryan/medium/en_US-ryan-medium", 228, False),
    "amy": ("Amy \u00b7 bright, US female", "en_US/amy/medium/en_US-amy-medium", 172, False),
    "alan": ("Alan \u00b7 calm, UK male", "en_GB/alan/medium/en_GB-alan-medium", 190, False),
}
DEFAULT_VOICE = "lessac"
SYSTEM = "system"


def speakable(text):
    """Strip prompter markers so the voice reads only what you'd say."""
    out = []
    for ln in engine.normalize(text).split("\n"):
        s = ln.strip()
        if not s or engine.is_marker(s):
            continue
        out.append(s)
    return "\n".join(out)


def voice_file(voice_id):
    """Path of an installed .onnx voice (bundled, downloaded or a dev copy), else None."""
    if voice_id not in VOICES:
        return None
    name = os.path.basename(VOICES[voice_id][1]) + ".onnx"
    for d in (os.path.join(paths.package_dir(), "voices"), paths.voices_dir(),
              os.path.join(paths.build_dir(), "voices")):
        f = os.path.join(d, name)
        if os.path.isfile(f) and os.path.isfile(f + ".json"):
            return f
    return None


def natural_available(voice_id=DEFAULT_VOICE):
    return PiperVoice is not None and sd is not None and voice_file(voice_id) is not None


def length_scale(voice_id, wpm):
    """Piper speed knob for a target pace. Clamped so the voice never sounds rushed or drawn out."""
    natural = VOICES.get(voice_id, VOICES[DEFAULT_VOICE])[2]
    return max(0.8, min(1.35, natural / max(60.0, float(wpm))))


def word_at(weights, frac):
    """Index of the word being spoken `frac` (0..1) of the way through a sentence."""
    total = float(sum(weights)) or 1.0
    t, acc = frac * total, 0.0
    for i, w in enumerate(weights):
        acc += w
        if t < acc:
            return i
    return len(weights) - 1


def download_voice(voice_id, progress=None):
    """Fetch a voice (~60 MB) into the user's data folder. Atomic: a partial download never counts."""
    path = VOICES[voice_id][1]
    dest = os.path.join(paths.voices_dir(), os.path.basename(path) + ".onnx")
    for ext, target in ((".onnx.json", dest + ".json"), (".onnx", dest)):
        tmp = target + ".part"
        with urllib.request.urlopen(HF + path + ext + "?download=true", timeout=30) as r, open(tmp, "wb") as f:
            size, got = int(r.headers.get("Content-Length") or 0), 0
            while True:
                block = r.read(1 << 16)
                if not block:
                    break
                f.write(block)
                got += len(block)
                if progress and size and ext == ".onnx":
                    progress(got / size)
        os.replace(tmp, target)
    return dest


class _NullOut:
    """Silent output that keeps real-time pacing (CI machines and computers with no sound device)."""

    def __init__(self, rate):
        self.rate, self.latency, self.t = rate, 0.0, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, data):
        time.sleep(len(data) / (self.rate * 2.0))


class _Resampled:
    """Plays 16-bit mono at `src` Hz on a device that only accepts its own rate (some USB/Bluetooth/pro devices)."""

    def __init__(self, stream, src, dst):
        import numpy as np
        self.np, self.stream, self.k, self.latency = np, stream, dst / float(src), stream.latency

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *a):
        return self.stream.__exit__(*a)

    def write(self, data):
        np = self.np
        x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        if not len(x):
            return
        n = max(1, int(round(len(x) * self.k)))
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
        self.stream.write(y.astype(np.int16).tobytes())


def open_output(rate):
    """Open the default speaker for 16-bit mono at `rate`, falling back to the device's own rate. Raises if none."""
    if os.environ.get("GLASSPROMPTER_NULL_AUDIO") == "1":
        return _NullOut(rate)
    if sd is None:
        raise RuntimeError("audio library missing")
    try:
        return sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", latency="low")
    except Exception as first:
        try:
            dev = sd.query_devices(kind="output")
            native_rate = int(dev["default_samplerate"])
        except Exception:
            raise RuntimeError("no speaker or headphones found (%s)" % first)
        log.info("Output rejected %d Hz (%s); using %d Hz", rate, first, native_rate)
        stream = sd.RawOutputStream(samplerate=native_rate, channels=1, dtype="int16", latency="low")
        return _Resampled(stream, rate, native_rate)


class Speaker(QObject):
    finished = Signal()
    progress = Signal(int)              # word index (word_map order) being spoken right now
    status = Signal(str)                # "preparing" | "speaking" | "system"
    failed = Signal(str)
    fellback = Signal()                 # the natural voice failed and the system voice took over
    _fallback = Signal(str)             # (thread -> main thread) text to read with the system voice

    def __init__(self):
        super().__init__()
        self.proc = None
        self._file = None
        self._stop = threading.Event()
        self._thread = None
        self._voices = {}
        self._lock = threading.Lock()
        self.natural = False
        self.safe = True                    # False if the natural voice crashed in the startup crash test
        self._wpm = 150
        self._said = -1                     # last word index actually spoken by the natural voice
        self._plan = []
        self._fallback.connect(self._take_over)

    @property
    def speaking(self):
        if self._thread is not None and self._thread.is_alive():
            return True
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def preload(self, voice_id):
        """Load the voice in the background so the first press of Read Aloud speaks almost instantly."""
        if voice_id != SYSTEM and self.safe and natural_available(voice_id):
            threading.Thread(target=self._voice, args=(voice_id,), daemon=True, name="tts-preload").start()

    def _voice(self, voice_id):
        with self._lock:
            if voice_id not in self._voices:
                self._voices[voice_id] = PiperVoice.load(voice_file(voice_id))
            return self._voices[voice_id]

    # ---------------------------------------------------------------- public
    def speak(self, lines, wpm=150, voice_id=DEFAULT_VOICE, start_word=0):
        """Read `lines` (engine.Line list) from `start_word`. Returns True if anything will be said."""
        self.stop()
        plan = engine.speech_plan(lines)
        if start_word > 0:
            plan = [it for it in plan if it[0] == "rest" or it[2] + len(it[3]) > start_word]
        if not any(it[0] == "say" for it in plan):
            return False
        self._wpm, self._plan, self._said = wpm, plan, -1
        if voice_id != SYSTEM and self.safe and natural_available(voice_id):
            self.natural = True
            self._stop = threading.Event()                  # each run gets its own stop flag
            self._thread = threading.Thread(target=self._run_natural, args=(plan, wpm, voice_id, self._stop),
                                            name="tts", daemon=True)
            self._thread.start()
            return True
        self.natural = False
        return self._speak_system(" ".join(it[1] for it in plan if it[0] == "say"), wpm)

    def stop(self):
        self._stop.set()                    # the playing thread notices within one 50 ms block and closes
        self._thread = None                 # its audio stream; never block the UI waiting for it
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(1000)
        self._cleanup()

    # ---------------------------------------------------------------- natural (Piper)
    def _run_natural(self, plan, wpm, voice_id, stop):
        try:
            self.status.emit("preparing")
            voice = self._voice(voice_id)
            cfg = SynthesisConfig(length_scale=length_scale(voice_id, wpm), noise_scale=0.6, noise_w_scale=0.75)
            rate = voice.config.sample_rate
            ready = queue.Queue(maxsize=3)

            def put(x):
                while not stop.is_set():
                    try:
                        return ready.put(x, timeout=0.2)
                    except queue.Full:
                        pass
                if x is None:                          # make sure the player loop can always exit
                    try:
                        ready.put_nowait(None)
                    except queue.Full:
                        pass

            def produce():                  # synthesize ahead of playback, one sentence at a time
                try:
                    for item in plan:
                        if stop.is_set():
                            break
                        if item[0] == "rest":
                            put(("rest", item[1]))
                            continue
                        _, text, first, weights = item
                        audio = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, syn_config=cfg))
                        put(("say", audio, first, weights))
                except Exception as e:      # hand synthesis errors to the player so they're never silent
                    put(("error", e))
                finally:
                    put(None)

            threading.Thread(target=produce, name="tts-synth", daemon=True).start()
            block = int(rate * 0.05) * 2                 # 50 ms of 16-bit mono
            with open_output(rate) as out:
                lag_bytes = float(out.latency or 0.0) * rate * 2
                self.status.emit("speaking")
                last = -1
                while not stop.is_set():
                    try:
                        item = ready.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    if item[0] == "error":
                        raise item[1]
                    if item[0] == "rest":
                        out.write(b"\0" * (int(rate * item[1]) * 2))
                        continue
                    _, audio, first, weights = item
                    total = float(max(1, len(audio)))
                    for pos in range(0, len(audio), block):
                        if stop.is_set():
                            break
                        out.write(audio[pos:pos + block])
                        heard = max(0.0, (pos + block - lag_bytes) / total)
                        w = first + word_at(weights, min(1.0, heard))
                        if w != last:
                            last = self._said = w
                            self.progress.emit(w)
                if not stop.is_set():
                    time.sleep(lag_bytes / (rate * 2) + 0.05)   # let the last syllable play out
        except Exception as ex:
            log.warning("Natural voice failed, switching to the system voice: %s", ex, exc_info=True)
            if not stop.is_set():
                rest = " ".join(it[1] for it in self._plan if it[0] == "say" and it[2] + len(it[3]) > self._said + 1)
                stop.set()                       # we hand over; don't emit finished
                self._fallback.emit(rest)
                return
        if not stop.is_set():
            self.finished.emit()

    def _take_over(self, text):
        self._thread = None
        self.natural = False
        if not text.strip():
            self.finished.emit()
            return
        self.fellback.emit()
        self._speak_system(text, self._wpm)

    # ---------------------------------------------------------------- system voice fallback
    def _speak_system(self, body, wpm):
        fd, self._file = tempfile.mkstemp(suffix=".txt", prefix="gp_tts_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        program, args = native.tts_command(self._file, wpm)
        self.proc = QProcess(self)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(lambda *_: self._done())
        self.status.emit("system")
        self.proc.start(program, args)
        return True

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
