"""Meeting copilot audio: your microphone ("You") and the computer's sound ("Them") -> offline live transcript.

Two capture threads, each with its own Vosk recognizer on a shared model:
  * microphone through sounddevice (same device as Voice Follow)
  * system audio (what the other people say on Zoom, Teams, Meet...) through a WASAPI loopback on Windows or a
    PulseAudio monitor on Linux, via the optional `soundcard` package. macOS has no loopback without a virtual audio
    device (e.g. BlackHole); there the copilot hears your microphone only, unless you pick such a device.

The recognizer runs with the full vocabulary (no script grammar). Nothing leaves the computer.
"""
import json
import logging
import queue
import threading
import time
import warnings

from PySide6.QtCore import QObject, Signal

from . import paths
from . import platform as native
from .meeting import ME, THEM

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

RATE = 16000
BLOCK_SEC = 0.1


def system_audio_supported():
    """Can we hear the computer's own sound (the other side of a call)?"""
    if native.OS == "macos":
        return False
    try:
        import soundcard  # noqa: F401
        return True
    except Exception:                                    # noqa: BLE001 - missing package or no audio server
        return False


def model_path(choice=""):
    models = paths.speech_models()
    if choice and choice in models:
        return models[choice]
    return paths.model_dir() or (next(iter(models.values())) if models else None)


class MeetingListener(QObject):
    segment = Signal(str, str)        # (who, finished phrase)
    partial = Signal(str, str)        # (who, words so far in the current phrase)
    status = Signal(str)              # "loading" | "listening" | "stopped"
    note = Signal(str)                # something the user should know, not fatal (e.g. no system audio)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()
        self._threads = []
        self._models = {}
        self._lock = threading.Lock()
        self.listening = False

    @staticmethod
    def available(choice=""):
        return vosk is not None and model_path(choice) is not None

    @staticmethod
    def why_unavailable(choice=""):
        if vosk is None:
            return "Speech recognition isn't part of this install."
        if model_path(choice) is None:
            return "No speech model found. See Settings › Voice Follow."
        return ""

    def _model(self, choice):
        path = model_path(choice)
        with self._lock:
            if path not in self._models:
                self._models[path] = vosk.Model(path)
            return self._models[path]

    def start(self, mic_device="", system_audio=True, model_choice=""):
        if self.listening:
            return
        if not self.available(model_choice):
            self.failed.emit(self.why_unavailable(model_choice))
            return
        self._stop.clear()
        self.listening = True
        self.status.emit("loading")

        def boot():
            try:
                model = self._model(model_choice)
            except Exception as e:                       # noqa: BLE001
                self.listening = False
                self.failed.emit("Couldn't load the speech model: %s" % e)
                self.status.emit("stopped")
                return
            if self._stop.is_set():
                return
            runners = []
            if sd is not None:
                runners.append((self._run_mic, (model, mic_device)))
            if system_audio:
                if system_audio_supported():
                    runners.append((self._run_system, (model,)))
                elif native.OS == "macos":
                    self.note.emit("macOS can't share the call's sound with apps, so only your microphone is "
                                   "transcribed. Use headphones off, or a loopback device like BlackHole.")
            if not runners:
                self.listening = False
                self.failed.emit("No audio input is available.")
                self.status.emit("stopped")
                return
            for fn, args in runners:
                t = threading.Thread(target=fn, args=args, name="meeting-" + fn.__name__, daemon=True)
                self._threads.append(t)
                t.start()
            self.status.emit("listening")
        threading.Thread(target=boot, name="meeting-boot", daemon=True).start()

    def stop(self):
        self._stop.set()
        self.listening = False
        self._threads = []
        self.status.emit("stopped")

    # ---------------------------------------------------------------- recognition
    def _feed(self, rec, who, data, last):
        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "").strip()
            if text:
                self.segment.emit(who, text)
            self.partial.emit(who, "")
            return ""
        text = json.loads(rec.PartialResult()).get("partial", "").strip()
        if text != last:
            self.partial.emit(who, text)
        return text

    def _flush(self, rec, who):
        try:
            text = json.loads(rec.FinalResult()).get("text", "").strip()
            if text:
                self.segment.emit(who, text)
        except Exception:                                # noqa: BLE001
            pass
        self.partial.emit(who, "")

    def _run_mic(self, model, device_name):
        from .voice import _device_index, pick_rate
        try:
            device = _device_index(device_name)
            rate = pick_rate(device)
            rec = vosk.KaldiRecognizer(model, rate)
            audio = queue.Queue(maxsize=400)

            def callback(indata, frames, t, st):
                try:
                    audio.put_nowait(bytes(indata))
                except queue.Full:
                    pass
            with sd.RawInputStream(samplerate=rate, blocksize=int(rate * BLOCK_SEC), dtype="int16", channels=1,
                                   device=device, callback=callback):
                log.info("Meeting copilot hearing the microphone (%d Hz)", rate)
                last = ""
                while not self._stop.is_set():
                    try:
                        data = audio.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    last = self._feed(rec, ME, data, last)
            self._flush(rec, ME)
        except Exception as e:                           # noqa: BLE001
            log.warning("Meeting copilot microphone stopped: %s", e)
            if not self._stop.is_set():
                self.note.emit("Microphone stopped: %s" % native.mic_error(str(e)))

    def _run_system(self, model):
        if native.OS == "windows":                       # soundcard talks COM; every thread must join it first
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")          # soundcard warns about discontinuities; harmless here
                import numpy as np
                import soundcard as sc
                speaker = sc.default_speaker()
                loop = sc.get_microphone(id=str(speaker.name), include_loopback=True)
                rec = vosk.KaldiRecognizer(model, RATE)
                frames = int(RATE * BLOCK_SEC)
                with loop.recorder(samplerate=RATE, channels=1, blocksize=frames) as r:
                    log.info("Meeting copilot hearing system audio from %s", speaker.name)
                    last = ""
                    while not self._stop.is_set():
                        block = r.record(numframes=frames)
                        if block is None or not len(block):
                            time.sleep(0.02)
                            continue
                        mono = block.mean(axis=1) if block.ndim > 1 else block
                        pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()
                        last = self._feed(rec, THEM, pcm, last)
                self._flush(rec, THEM)
        except Exception as e:                           # noqa: BLE001
            log.warning("Meeting copilot system audio stopped: %s", e)
            if not self._stop.is_set():
                self.note.emit("Couldn't hear the computer's sound (%s). Transcribing your microphone only." % e)
