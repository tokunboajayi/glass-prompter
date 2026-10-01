import pathlib
root = pathlib.Path(__file__).resolve().parent.parent
cl = root / "CHANGELOG.md"
t = cl.read_text(encoding="utf-8-sig")
entry = """# Changelog

## 1.1.0 - 2026-10-01
The "best version possible" release, shaped by research on GhostPrompter, Speakflow, PromptSmart, ShareSpeak and
the Mac notch prompters (Notchie, Moody, CueNotch, Textream).

- **Voice Follow:** the script scrolls as you speak. It runs offline (Vosk, no audio leaves the PC) and only listens
  for your script's own words, which improves accuracy. Spoken words fade so your eye lands on the next one, it shows
  your live words per minute, and you get an end-of-read summary.
- **macOS-style glass UI:**
  - Real frosted blur on Windows 11 (falls back gracefully on older Windows).
  - Traffic-light window buttons.
  - Frameless glass dialogs.
  - iOS-style switches.
  - Translucent cards and inputs.
- **Ghost mode:** clicks pass through the prompter to the app behind it (Ctrl+Alt+G, the yellow light or the tray).
- **Sections:** `# Heading` lines become amber section markers. Jump with PgUp/PgDn, Ctrl+Alt+PgUp/PgDn or the
  phone. Markdown imports keep their headings.
- **Mirror mode** for beam-splitter teleprompter glass.
- **Phone remote:**
  - Glassmorphism redesign.
  - Voice Follow and Ghost toggles.
  - Section jumps.
  - Live words-per-minute readout.
- 61 automated tests (new: voice alignment and sections).

"""
if "## 1.1.0" not in t:
    t = entry + t.split("\n", 2)[2] if t.startswith("# Changelog") else entry + t
cl.write_text(t, encoding="utf-8", newline="")

rd = root / "README.md"
r = rd.read_text(encoding="utf-8-sig")
r = r.replace("**Install:** run `dist/GlassPrompter-Setup-1.0.0.exe`.", "**Install:** download the latest installer from Releases.")
old = "## Features\n\n"
new = """## Features

- **Voice Follow:** the script scrolls as you speak. It runs 100% offline and only listens for your script's own words, so it's accurate. Spoken words fade so your eye lands on the next one, it shows your live words per minute, and you get a summary at the end.
- **macOS-style glass:** real frosted blur on Windows 11, traffic-light window buttons, frameless glass dialogs and iOS-style switches.
- **Ghost mode:** clicks pass through the prompter to the app behind it.
- **Sections:** `# Heading` lines become jump points, handy for interviews and Q&A.
- **Mirror mode:** for teleprompter glass.
"""
if "Voice Follow" not in r:
    r = r.replace(old, new, 1)
r = r.replace("python -m pytest --basetemp=.pytest_tmp tests # 45 tests", "python -m pytest --basetemp=.pytest_tmp tests # 61 tests")
r = r.replace("python -m pip install PySide6-Essentials qrcode pytest pyinstaller", "python -m pip install -r requirements.txt")
rd.write_text(r, encoding="utf-8", newline="")

rn = root / "packaging" / "RELEASE_NOTES.md"
n = rn.read_text(encoding="utf-8-sig")
n = n.replace("GlassPrompter-Setup-1.0.0.exe", "GlassPrompter-Setup-{VERSION}.exe")
n = n.replace("## Highlights\n", """## New in 1.1
- **Voice Follow:** the script scrolls as you speak. It's 100% offline and spoken words fade as you go.
- **macOS-style glass UI:** real frosted blur, traffic lights, and iOS-style switches.
- **Ghost mode:** clicks pass through to the app behind the prompter.
- **Sections:** `# Heading` lines become jump points.
- **Mirror mode** and a glass redesign of the phone app.

## Highlights
""") if "## New in 1.1" not in n else n
rn.write_text(n, encoding="utf-8", newline="")
print("docs updated")
