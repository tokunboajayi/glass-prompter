# Glass Prompter

A see-through teleprompter that sits right under your webcam, so you can read your script and keep eye contact on calls, demos and videos. It is hidden from screen sharing and recordings.

**Install:** run `dist/GlassPrompter-Setup-1.0.0.exe`. It installs per user (no admin rights), adds Start menu and desktop shortcuts, and lives in the tray.

## Features

- **Glass overlay:** frameless, always on top, see-through panel with crisp text. The reading line is highlighted and the edges fade out.
- **Hidden from screen share:** uses Windows display affinity. It re-checks with Windows every 1.5 seconds and re-applies the setting if anything reset it. A badge shows the real state.
- **Words-per-minute pacing:** the speed holds at any text size or window width. A 3-2-1 countdown runs before scrolling starts. `[PAUSE]` and `[CUE]` markers are supported.
- **Script library:** SQLite storage with search, autosave, and import of .txt/.md/.docx files.
- **Phone remote:** works over Wi-Fi with a QR code to pair. Live state updates over Server-Sent Events. You can manage the library and upload files from the phone.
- **Drop folder:** `Documents\Glass Prompter`, which works with OneDrive. Save a file there from any device and it loads automatically.
- **Global hotkeys:** Ctrl+Alt+Space/Up/Down/Left/Right/R/H/E. If another app has taken a shortcut, Glass Prompter falls back to listening for the keys directly.
- **Desktop app basics:** tray menu, settings, a first-run welcome, single instance, start with Windows, crash and rotating logs, and atomic settings writes with migration from older versions.

## Architecture

```
glassprompter/
  app.py          controller: wiring, tray, hotkeys, drop folder, single instance
  engine.py       pure prompter logic (wrap, markers, pacing) - no Qt
  scripts.py      SQLite library + .txt/.md/.docx import (thread-safe)
  config.py       versioned, validated settings with atomic writes + migration
  win32.py        display affinity, RegisterHotKey, autostart
  log.py          rotating logs, crash capture
  server/api.py   REST /api/v1 + SSE, sessions, rate limiting, security headers
  server/static/  phone web app (no inline code; strict CSP)
  ui/             prompter overlay, dialogs, design tokens, icon
tests/            pytest: engine, config, library, API security & realtime
packaging/        PyInstaller spec, Inno Setup script, build.ps1
```

The server runs on background threads and never touches the UI. It reaches the UI only through a Qt bridge that queues signals across threads.

## Remote API (v1)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/health` | public |
| POST | `/api/v1/session` | `{"pin": "123456"}` returns a token and an HttpOnly cookie |
| GET | `/api/v1/state` · `/api/v1/events` (SSE) | live prompter state |
| POST | `/api/v1/control` | `{"action": "play"/"restart"/"faster"/"slower"/"back"/"ahead"/"bigger"/"smaller"/"hide"}` |
| GET/POST | `/api/v1/scripts` | list (`?q=` search) / create (`load: true` to show it) |
| GET/PUT/DELETE | `/api/v1/scripts/{id}` | read, update, delete |
| POST | `/api/v1/scripts/{id}/load` | show it on the prompter |
| POST | `/api/v1/upload?name=file.docx` | raw body, 8 MB max |

**Security:**

- The PIN is exchanged once for a session token. The PIN is never accepted on data endpoints.
- 5 wrong PINs locks that device out for 5 minutes.
- The Host header is checked to block DNS rebinding.
- JSON-only writes, so ordinary web forms can't post to the API.
- No CORS, so other websites can't call it from a browser.
- Strict CSP and security headers.
- Request size limits.
- Generating a new PIN signs out every phone.

## Develop

```powershell
python -m pip install PySide6-Essentials qrcode pytest pyinstaller
python glass_prompter.pyw                     # run from source
python -m pytest --basetemp=.pytest_tmp tests # 45 tests
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # test -> bundle -> installer
python tools\smoke.py .smoke --visible        # UI smoke test with screenshots
```

## Data and privacy

Scripts and settings stay on the PC in `%APPDATA%\GlassPrompter` (`library.db`, `settings.json`, `logs\`). Uninstalling keeps them. Nothing is sent to the internet.

## Known limits

- The installer is not code-signed yet, so Windows SmartScreen shows "Windows protected your PC". Click *More info → Run anyway*. Signing (about $10/month via Azure Artifact Signing) or a Microsoft Store listing removes this.
- Windows only (Windows 10 2004 or later for screen-share hiding).
- The phone remote needs the same Wi-Fi. If Windows marks the network Public, allow the firewall prompt or switch the network to Private.
