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


class Speaker(QObject):
    finished = Signal()
    progress = Signal(int)              # word index (word_map order) being spoken right now
    status = Signal(str)                # "preparing" | "speaking" | "system"
    failed = Signal(str)

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
        if voice_id != SYSTEM and self.safe and natural_available(voice_id):
            self.natural = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_natural, args=(plan, wpm, voice_id),
                                            name="tts", daemon=True)
            self._thread.start()
            return True
        self.natural = False
        return self._speak_system(" ".join(it[1] for it in plan if it[0] == "say"), wpm)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(1000)
        self._cleanup()

    # ---------------------------------------------------------------- natural (Piper)
    def _run_natural(self, plan, wpm, voice_id):
        try:
            self.status.emit("preparing")
            voice = self._voice(voice_id)
            cfg = SynthesisConfig(length_scale=length_scale(voice_id, wpm), noise_scale=0.6, noise_w_scale=0.75)
            rate = voice.config.sample_rate
            ready = queue.Queue(maxsize=3)

            def put(x):
                while not self._stop.is_set():
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
                        if self._stop.is_set():
                            break
                        if item[0] == "rest":
                            put(("rest", item[1]))
                            continue
                        _, text, first, weights = item
                        audio = b"".join(c.audio_int16_bytes for c in voice.synthesize(text, syn_config=cfg))
                        put(("say", audio, first, weights))
                finally:
                    put(None)

            threading.Thread(target=produce, name="tts-synth", daemon=True).start()
            block = int(rate * 0.05) * 2                 # 50 ms of 16-bit mono
            with sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16", latency="low") as out:
                lag_bytes = float(out.latency or 0.0) * rate * 2
                self.status.emit("speaking")
                last = -1
                while not self._stop.is_set():
                    try:
                        item = ready.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    if item[0] == "rest":
                        out.write(b"\0" * (int(rate * item[1]) * 2))
                        continue
                    _, audio, first, weights = item
                    total = float(max(1, len(audio)))
                    for pos in range(0, len(audio), block):
                        if self._stop.is_set():
                            break
                        out.write(audio[pos:pos + block])
                        heard = max(0.0, (pos + block - lag_bytes) / total)
                        w = first + word_at(weights, min(1.0, heard))
                        if w != last:
                            last = w
                            self.progress.emit(w)
                if not self._stop.is_set():
                    time.sleep(lag_bytes / (rate * 2) + 0.05)   # let the last syllable play out
        except Exception as ex:
            log.warning("Natural voice failed: %s", ex)
            self.failed.emit("The natural voice couldn't play (%s)." % ex)
        finally:
            if not self._stop.is_set():
                self.finished.emit()

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
