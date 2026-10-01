"""Voice Follow self-test without a microphone: Windows text-to-speech reads a script into a WAV,
the recognizer transcribes it with the script grammar, and the aligner must reach the last word.
Usage: python tools/voice_selftest.py"""
import json, os, subprocess, sys, tempfile, wave
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from glassprompter import engine, paths
from glassprompter.tracking import Aligner, norm_words
import vosk

SCRIPT = ("Good morning everyone. Thank you for joining today. I want to walk you through our quarterly "
          "results and the plan for next year. Revenue grew eighteen percent and our customers are happier "
          "than ever.")
wav = os.path.join(paths.data_dir(), "selftest.wav")
ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      "$s.Rate = 1; $s.SetOutputToWaveFile('%s'); $s.Speak('%s'); $s.Dispose()" % (wav, SCRIPT.replace("'", "''")))
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, creationflags=0x08000000)

vosk.SetLogLevel(-1)
lines = engine.wrap(SCRIPT, 40, len)
words, word_line, _ = engine.word_map(lines)
w = wave.open(wav, "rb")
rec = vosk.KaldiRecognizer(vosk.Model(paths.model_dir()), w.getframerate(), json.dumps(sorted(set(words)) + ["[unk]"]))
al = Aligner(words)
heard_all = []
while True:
    data = w.readframes(int(w.getframerate() * 0.1))
    if not data:
        break
    if rec.AcceptWaveform(data):
        h = norm_words(json.loads(rec.Result())["text"])
        heard_all += h
    else:
        h = norm_words(json.loads(rec.PartialResult())["partial"])
    if h:
        al.update(h)
heard_all += norm_words(json.loads(rec.FinalResult())["text"])
w.close()
print("recognized:", " ".join(heard_all))
print("aligner reached word %d of %d (%s), line %d of %d" % (al.cursor + 1, len(words), words[al.cursor],
                                                          word_line[al.cursor], max(word_line)))
os.remove(wav)
print("PASS" if al.cursor >= len(words) - 2 else "FAIL")
