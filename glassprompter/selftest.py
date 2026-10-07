"""Built-in self-test for packaged builds:  GlassPrompter --selftest  (exit code 0 = Voice Follow + Read Aloud OK).

Runs without a window, a microphone or speakers, so CI can check every installer before it is published.
Each check runs in a child process, so a native crash (segfault/abort) is reported instead of killing the test.
"""
import json
import os
import subprocess
import sys
import time

CHECKS = ("speech_model", "voice_follow", "read_aloud_voice", "read_aloud_synth", "audio_devices", "audio_out")
REQUIRED = ("speech_model", "voice_follow", "read_aloud_voice", "read_aloud_synth")


def _one(name):
    from . import paths
    if name == "speech_model":
        d = paths.model_dir()
        if not d:
            raise RuntimeError("speech model folder not found")
        return d
    if name == "voice_follow":
        import vosk
        vosk.SetLogLevel(-1)
        model = vosk.Model(paths.model_dir())
        rec = vosk.KaldiRecognizer(model, 16000, json.dumps(["good morning everyone", "[unk]"]))
        rec.AcceptWaveform(b"\0\0" * 16000)               # one second of silence
        rec.FinalResult()
        return "recognizer ran (vosk %s)" % getattr(vosk, "__version__", "?")
    if name == "read_aloud_voice":
        from . import tts
        f = tts.voice_file(tts.DEFAULT_VOICE)
        if not f:
            raise RuntimeError("bundled voice not found")
        return f
    if name == "read_aloud_synth":
        from . import tts
        t0 = time.time()
        voice = tts.load_voice(tts.voice_file(tts.DEFAULT_VOICE))
        audio = b"".join(c.audio_int16_bytes for c in voice.synthesize("Good morning everyone."))
        if len(audio) < 4000:
            raise RuntimeError("synthesis produced no audio")
        return "%d bytes in %.1fs" % (len(audio), time.time() - t0)
    if name == "audio_devices":
        import sounddevice as sd
        devs = sd.query_devices()
        ins = sum(1 for d in devs if d["max_input_channels"] > 0)
        outs = sum(1 for d in devs if d["max_output_channels"] > 0)
        return "%d input, %d output" % (ins, outs)
    if name == "audio_out":
        import sounddevice as sd
        with sd.RawOutputStream(samplerate=22050, channels=1, dtype="int16", latency="low") as out:
            out.write(b"\0" * (22050 // 5 * 2))             # 0.2 s of silence through the real output path
        return "played 0.2 s of silence"
    raise ValueError(name)


def child(name, result_path):
    """Entry point inside the child process: write one JSON result (GUI builds may have no stdout)."""
    try:
        res = {"ok": True, "detail": str(_one(name))}
    except Exception as e:                       # noqa: BLE001 - we want every failure reported
        res = {"ok": False, "detail": "%s: %s" % (type(e).__name__, e)}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(res, f)
    return 0 if res["ok"] else 1


def _command():
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "glass_prompter.pyw")
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, launcher]


def probe_one(name, timeout=180):
    """Run one check in a child process. 'crashed' is True only for a native crash (no result written)."""
    import tempfile
    rp = os.path.join(tempfile.gettempdir(), "gp_selftest_%s_%d.json" % (name, os.getpid()))
    try:
        p = subprocess.run(_command() + ["--selftest-child", name, rp], capture_output=True, text=True,
                           timeout=timeout, **_no_window())
    except subprocess.TimeoutExpired:
        return {"ok": False, "crashed": False, "detail": "timed out"}
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            res = json.load(f)
        os.remove(rp)
        res["crashed"] = False
        return res
    return {"ok": False, "crashed": True,
            "detail": "crashed (exit %s) %s" % (p.returncode, (p.stderr or "")[-400:].strip())}


def _no_window():
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}                # CREATE_NO_WINDOW
    return {}


def run(report=None):
    lines = []

    def out(text):
        lines.append(text)
        if sys.stdout is not None:
            try:
                print(text, flush=True)
            except Exception:
                pass

    failed = []
    for name in CHECKS:
        res = probe_one(name)
        mark = "PASS" if res["ok"] else ("FAIL" if name in REQUIRED else "WARN")
        out("%-17s %s  %s" % (name, mark, res["detail"]))
        if not res["ok"] and name in REQUIRED:
            failed.append(name)
    out("RESULT: %s" % ("OK" if not failed else "FAILED (" + ", ".join(failed) + ")"))
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if failed else 0
