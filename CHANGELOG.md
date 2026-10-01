# Changelog

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
- 53 automated tests (new: voice alignment and sections).

## 1.0.0 - 2026-10-01
First production release.

- Rebuilt as a modular package with 45 automated tests.
- Script library in SQLite, with search, autosave and import.
- Remote API v1:
  - The PIN is exchanged once for a session token.
  - Wrong PINs are rate limited, then locked out.
  - DNS-rebinding protection.
  - Strict CSP.
  - Live updates over SSE.
  - Phone access to the script library.
- New phone web app with tabs for Remote, Library and Write.
- Tray icon, settings, first-run welcome, about screen, single instance, start with Windows.
- System hotkeys via RegisterHotKey, with a fallback when another app owns a combination.
- Drop folder moved to `Documents\Glass Prompter`.
- The redraw loop only runs while something is moving, so it uses no CPU when idle.
- Crash logs, rotating logs, crash-safe settings, and migration from earlier versions.
- Per-user Windows installer (no admin rights) and a clean uninstall that keeps your data.
