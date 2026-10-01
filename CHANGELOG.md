# Changelog

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
