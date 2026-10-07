# Contributing to Glass Prompter

## Run from source

Requires Python 3.10+ on Windows, macOS or Linux.

```bash
git clone https://github.com/tokunboajayi/glass-prompter.git
cd glass-prompter
python -m pip install -r requirements.txt
python glass_prompter.pyw          # starts the app
python -m pytest -q tests          # 115 tests, runs headless on all three OSes
```

**Voice Follow from source** needs the offline speech model. The installers bundle it.

1. Download [`vosk-model-small-en-us-0.15.zip`](https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip), about 40 MB.
2. Unzip it into a `models` folder inside your data folder:
   - Windows: `%APPDATA%\GlassPrompter\models\`
   - macOS: `~/Library/Application Support/GlassPrompter/models/`
   - Linux: `~/.local/share/GlassPrompter/models/`

   Or point `GLASSPROMPTER_MODEL` at the unzipped folder.

**Read Aloud voices** can be downloaded from Settings › Read aloud.

Handy environment variables:

| Variable | Effect |
|---|---|
| `GLASSPROMPTER_HOME` | Use a different data folder (great for a clean test profile) |
| `GLASSPROMPTER_ALLOW_CAPTURE=1` | Don't hide windows from screen capture, so screenshots work |
| `GLASSPROMPTER_MODEL` | Path to a Vosk model folder |
| `GLASSPROMPTER_AI_KEY` | API key for the AI assistant, any provider (otherwise read from `ai.key` in the data folder) |

## Project layout

```
glass_prompter.pyw     entry point
glassprompter/
  app.py               controller: wiring, tray/menu bar, hotkeys, drop folder, backups, updates, single instance
  platform/            one API over the OS: windows.py (Win32/DWM), macos.py (PyObjC/Carbon), generic.py (Linux)
  engine.py            pure prompter logic (wrap, markers, pacing, voice glide, speech plan); no Qt
  tracking.py          fuzzy script aligner for Voice Follow
  voice.py             mic -> Vosk, low-latency loop, watchdog, latency stats
  tts.py               Read Aloud: Piper neural voices, sentence-ahead synthesis, word-level progress
  coach.py             rehearsal scoring
  scripts.py           SQLite library, import (.txt/.md/.docx), backup, Markdown export
  ai.py                AI assistant for any provider (Anthropic, Gemini, any OpenAI-compatible API), live model lists
  config.py            versioned, validated settings with atomic writes and migration
  updater.py           GitHub Releases check, SHA-256 verified download, silent install
  server/api.py        phone remote: REST /api/v1 + SSE, sessions, rate limiting, security headers
  server/static/       phone web app (strict CSP, no inline code)
  ui/assistant.py      desktop AI chat window (worker thread, screen capture, send to prompter)
  ui/                  prompter overlay, glass toolkit (menu, tooltips, dialogs), icons, design tokens
  fonts/               Inter (SIL OFL), bundled so type looks the same on every OS
tests/                 pytest
tools/                 shots.py (render every screen), marketing_images.py, website_images_ai.py, phone_shots.js, self-tests
docs/                  the website (GitHub Pages)
packaging/             PyInstaller spec, Inno Setup, build scripts, winget + Homebrew manifests
skills/                a guide for AI assistants writing scripts for the prompter
```

## Design system

One look on Windows, macOS, the phone app and the website ("Aurora Glass"):

- **Tokens** live in `glassprompter/ui/theme.py` (`T`): deep ink surfaces, aqua `#40E8D0` for active,
  violet `#8B6CFF` for sections, ember `#FFA64D` for cues. The website mirrors them as CSS variables.
- **Glass** is painted by `paint_glass()` in `ui/glass.py`. Use `GlassMenu`, `GlassTip`/`TipFilter` and
  `GlassDialog` instead of native Qt menus, tooltips and dialogs, so nothing looks out of place.
- **Keycaps:** always render shortcuts with `paint_keys()` (app) or `<kbd>` (web) so they match everywhere.
- **Icons** are vector, drawn in `ui/icons.py` on a 20 px grid at 1.6 px stroke. No emoji, no icon fonts.
- **Motion:** exits are faster than entrances (about 180 ms in, 120 ms out) and every animation respects
  *Reduce motion*.

To check your change visually, render every screen headless:

```bash
QT_QPA_PLATFORM=offscreen python tools/shots.py shots      # writes PNGs into ./shots
```

## Phone remote API (v1)

The app serves this on port 8765 on your local network.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/health` | public |
| POST | `/api/v1/session` | `{"pin": "123456"}` returns a token and an HttpOnly cookie |
| GET | `/api/v1/state` · `/api/v1/events` (SSE) | live prompter state, including voice latency |
| POST | `/api/v1/control` | `{"action": "play"}`. Other actions: `restart`, `faster`, `slower`, `back`, `ahead`, `bigger`, `smaller`, `hide`, `voice`, `ghost`, `ghost_less`, `ghost_more`, `read_aloud`, `next_section`, `prev_section` |
| GET/POST | `/api/v1/scripts` | list (`?q=` search) / create (`load: true` to show it) |
| GET/PUT/DELETE | `/api/v1/scripts/{id}` | read, update, delete |
| POST | `/api/v1/scripts/{id}/load` | show it on the prompter |
| POST | `/api/v1/upload?name=file.docx` | raw body, 8 MB max |
| GET | `/api/v1/features` | `{"screen": bool, "ai": bool, "ai_model": "..."}`. Never includes the API key |
| GET | `/api/v1/screen.jpg` | JPEG of the screen the prompter is on (max 1280 px wide; `?full=1` for full resolution). 403 when *Phone can view my screen* is off |
| POST | `/api/v1/ai/chat` | `{"messages": [{"role": "user", "content": "..."}], "screen": true}` returns `{"reply": "...", "saw_screen": bool}`. The computer adds the screenshot and script, then calls Claude with the key from Settings |

**Security:**

- The PIN is exchanged for a session token, and data endpoints never accept the PIN itself.
- 5 wrong PINs lock that device out for 5 minutes.
- The Host header is checked to block DNS rebinding.
- Writes are JSON-only, there's no CORS, and a strict CSP applies.
- Request sizes are limited.
- A new PIN signs out every phone.

## Audits

| Command | What it checks |
|---|---|
| `python glass_prompter.pyw --selftest` | Speech model, Voice Follow engine, natural voice, audio |
| `python glass_prompter.pyw --e2e` | The whole app, driven like a user and the phone would (about 2 minutes) |
| `python tools/phone_e2e.py` | The phone web app in a mobile browser (needs Node and Playwright) |

The Windows and Mac build scripts run `--selftest` and `--e2e` on the built app, so a broken build is never published.

## Pull requests

1. Keep the app working on all three OSes. Platform-specific code goes in `glassprompter/platform/`.
2. `python -m pytest -q tests` must pass. CI runs it on Windows, macOS and Linux.
3. For UI changes, attach before/after PNGs from `tools/shots.py`.
4. Add a line to `CHANGELOG.md` under the next version.
