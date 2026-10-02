# Glass Prompter

A see-through teleprompter that sits right under your webcam on **Windows and macOS**, follows your voice word by word, and coaches you after every run. Your eyes stay on the camera, and your script stays off the screen share.

**Download:** [tokunboajayi.github.io/glass-prompter](https://tokunboajayi.github.io/glass-prompter/) (detects your OS), or [Releases](../../releases/latest).

| | Installer | Command line |
|---|---|---|
| Windows 10/11 | `GlassPrompter-Setup-x.y.z.exe` (per-user, no admin) | `winget install TokunboAjayi.GlassPrompter` |
| Mac, Apple silicon (macOS 13+) | `GlassPrompter-x.y.z-macOS-arm64.dmg` | `brew install --cask tokunboajayi/tap/glass-prompter` |
| Mac, Intel (macOS 13+) | `GlassPrompter-x.y.z-macOS-x86_64.dmg` | same as above |

Updates arrive inside the app. Once a day it checks GitHub for a new version and verifies the download's SHA-256 before installing. You can turn this off in Settings.

## Why it's different

| Common complaint about other prompters | What Glass Prompter does |
|---|---|
| Voice scroll **lags seconds behind** or **jumps paragraphs** on a mishear | 16 kHz capture in 40 ms blocks, catch-up when behind, a grammar limited to your script's words, and multi-word evidence before any jump. The text glides on a critically damped spring instead of snapping line to line. Live latency is shown in ms. |
| Voice tracking **freezes mid-take** | A watchdog reopens the microphone if audio stops (Bluetooth hiccup, device switch) and you keep your place. |
| **Mac-only** (notch apps) or **Windows-first** | Same app, same look, same phone remote on both. |
| "Invisible on screen share" claims that **aren't true on macOS 15+** | An honest badge. Green only when the OS really hides it. On macOS 15+ it says *share a window, not your screen*, because Apple's ScreenCaptureKit ignores window privacy flags. |
| Scripts **lost after an update** | SQLite library, a daily automatic backup (last 7 kept), and one-click export of everything to Markdown. |
| **Bluetooth / external mics** not picked up | A microphone picker. A device that's unplugged falls back to the default instead of failing. |
| No feedback on delivery | A Rehearsal Coach report after each run: score, pace, fillers, pauses, skipped lines, and your trend. |

## Features

- **Aurora Glass UI:** deep-ink frosted glass (Windows 11 acrylic, macOS vibrancy) with a living aurora rim that shows state. It's calm when idle, flows while you read and pulses with your voice. Vector icons, frameless dialogs, one design system on both OSes and the phone.
- **Voice Follow:** offline (Vosk) and tuned for low latency. Spoken words dim so your eye lands on the next one. Shows live wpm and latency.
- **Rehearsal Coach + live pace light**, plus **Read Aloud** in a natural neural voice (Piper, offline) that the prompter follows word by word.
- **Hidden from screen share** where the OS allows it. It re-checks every 1.5 s and the badge always shows the real state.
- **Ghost mode** (click-through), **mirror mode**, **sections** (`# Heading`), `[PAUSE]` and `[CUE]` markers, a 3-2-1 countdown, and pacing in words per minute.
- **Phone remote** over Wi-Fi: pair with a QR code, PIN-protected, with live state over SSE. Manage and upload scripts from the phone.
- **Drop folder** in `Documents/Glass Prompter`: works with OneDrive or iCloud Drive.
- **One design system everywhere:** glass menus with inline switches and steppers, glass tooltips that show each action's keys, a grouped shortcut sheet (F1), and the same keycaps on the website.
- **Global shortcuts:** Ctrl+Alt (Windows) or Control+Option (macOS) plus Space/Up/Down/Left/Right/R/H/E/V/G/PgUp/PgDn. On macOS these use Carbon hotkeys, so no Accessibility permission is needed.
- **On macOS** the prompter floats over full-screen apps on every Space and never hides when Zoom takes focus.

## Architecture

```
glassprompter/
  app.py            controller: wiring, tray/menu bar, hotkeys, drop folder, backups, single instance
  platform/         one API over the OS: windows.py (Win32/DWM), macos.py (PyObjC/Carbon), generic.py
  engine.py         pure prompter logic (wrap, markers, pacing, voice glide) - no Qt
  tracking.py       fuzzy script aligner for Voice Follow
  voice.py          mic -> Vosk, low-latency loop, watchdog, latency stats
  coach.py          rehearsal scoring
  scripts.py        SQLite library, import, backup, Markdown export (thread-safe)
  config.py         versioned, validated settings with atomic writes + migration
  server/api.py     REST /api/v1 + SSE, sessions, rate limiting, security headers
  server/static/    phone web app (strict CSP, no inline code)
  ui/               prompter overlay, glass toolkit, vector icons, dialogs, design tokens
tests/              pytest (runs on Windows, macOS and Linux in CI)
packaging/          PyInstaller spec (Win + Mac), Inno Setup, build.ps1, build_mac.sh
.github/workflows/  CI on all three OSes; tagged releases build the .exe and both .dmg files
```

## Remote API (v1)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/health` | public |
| POST | `/api/v1/session` | `{"pin": "123456"}` returns a token and an HttpOnly cookie |
| GET | `/api/v1/state` · `/api/v1/events` (SSE) | live prompter state, including voice latency |
| POST | `/api/v1/control` | `{"action": "play"}` plus restart, faster, slower, back, ahead, bigger, smaller, hide, voice, ghost, read_aloud, next_section, prev_section |
| GET/POST | `/api/v1/scripts` | list (`?q=` search) / create (`load: true` to show it) |
| GET/PUT/DELETE | `/api/v1/scripts/{id}` | read, update, delete |
| POST | `/api/v1/scripts/{id}/load` | show it on the prompter |
| POST | `/api/v1/upload?name=file.docx` | raw body, 8 MB max |

**Security:**

- The PIN is exchanged for a session token and is never accepted on data endpoints.
- 5 wrong PINs locks that device out for 5 minutes.
- The Host header is checked to block DNS rebinding.
- Writes are JSON-only, there's no CORS, and a strict CSP applies.
- Request size limits are enforced.
- A new PIN signs out every phone.

## Develop

```bash
python -m pip install -r requirements.txt
python glass_prompter.pyw                        # run from source
python -m pytest -q tests                        # 77 tests
QT_QPA_PLATFORM=offscreen python tools/shots.py shots   # render every screen to PNG
# Windows build:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# macOS build:    bash packaging/build_mac.sh
```

Pushing a tag `vX.Y.Z` builds the Windows installer and both Mac disk images in GitHub Actions and attaches them to the release.
Then run `python packaging/distribution.py` to generate the winget manifests and Homebrew cask for that release.
The website lives in `docs/` and is served by GitHub Pages. Rebuild its images with `tools/shots.py` and `tools/marketing_images.py`.

## Data and privacy

Scripts, settings, backups and logs stay on your computer:

- Windows: `%APPDATA%\GlassPrompter`
- macOS: `~/Library/Application Support/GlassPrompter`

Audio is processed on-device and never sent anywhere. The only internet request is the optional daily update check to `api.github.com`.

## Known limits

- **Unsigned builds:**
  - Windows SmartScreen: click *More info → Run anyway*.
  - macOS: the first time, right-click the app and choose **Open**. On macOS 15+, go to System Settings → Privacy & Security and click **Open Anyway**.
  - Code signing removes these warnings: Azure Artifact Signing for Windows, an Apple Developer ID ($99/yr) for macOS.
- **macOS 15+ screen sharing:** share a window or app, not the entire screen. Apple gives apps no way to hide from full-screen capture.
- **Phone remote** needs the same Wi-Fi. Allow the firewall prompt the first time.
