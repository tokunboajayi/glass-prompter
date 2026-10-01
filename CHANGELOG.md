# Changelog

## 2.1.0 - 2026-10-01
Human voice and a refinement pass on the whole interface.

- **Natural Read Aloud:** an offline neural voice (Piper) replaces the robotic system voice:
  - It starts speaking in about half a second.
  - The prompter follows the exact word being spoken, karaoke-style, instead of scrolling at a fixed speed.
  - Pace follows your words-per-minute setting.
  - `[PAUSE]` lines and new sections get natural pauses, and `[CUES]` are never read out.
  - Read Aloud starts from the line you're on.
  - Lessac (warm US female) ships with the app. Ryan, Amy and Alan download in Settings (about 60 MB each).
  - **Play sample** lets you hear a voice before you choose it.
  - The system voice remains as a fallback.
- **Refined UI:**
  - **Typography:** Inter is bundled, so text looks the same on Windows and macOS.
  - **Status:** one quiet status capsule replaces the row of badges.
  - **Reading band:** a soft band of light replaces the gradient box, with slim accent ticks marking the line.
  - **Script markers:** sections render as editorial headings, and cues and `[PAUSE]` as small chips.
  - **Panel edge:** a calmer glass edge, where accent color appears only when something is running.
  - **Control bar:** grouped into four clusters plus an overflow menu, with a white primary Play button.
  - **Shortcuts:** the shortcut sheet shows real keycaps.
  - **Settings:** rebuilt as grouped cards, with a switch on the right of each row.
  - **Dialogs:** headers no longer repeat the title, and primary buttons are solid white throughout. The phone app matches.
- 71 automated tests.

## 2.0.0 - 2026-10-01
Cross-platform release. Built from research into where competing prompters fail: voice-scroll lag and jumps,
freezes mid-take, Mac-only notch apps, false "invisible" claims on macOS 15+, and lost scripts.

- **macOS support** alongside Windows, with one codebase and one look. New `glassprompter/platform` layer:
  - **Windows:** display affinity, DWM acrylic, RegisterHotKey with a polling fallback, Run-key autostart, SAPI voice.
  - **macOS:** NSWindow sharing type, vibrancy, Carbon global hotkeys (no Accessibility permission),
    floats over full-screen apps on all Spaces, LaunchAgent autostart, the `say` voice, and a menu-bar icon.
- **Aurora Glass UI** replaces the macOS-style chrome:
  - No more traffic lights.
  - A living aurora rim that shows state.
  - Gradient reading band and progress bar.
  - A vector icon set drawn in code.
  - New app icon.
  - Branded dialog headers with a single close button.
  - A countdown ring.
  - The phone app is restyled to match.
- **Faster, steadier Voice Follow:**
  - 16 kHz capture in 40 ms blocks (was 100 ms).
  - Catch-up when the recognizer falls behind.
  - The model preloads at startup.
  - A continuous glide on a critically damped spring replaces line-by-line jumps.
  - A watchdog reopens a stalled microphone.
  - Live latency readout.
  - A microphone picker.
- **Honest screen-share badge:** green only when the OS really hides the prompter. On macOS 15+ it says
  "Share a window, not your screen".
- **Never lose a script:** an automatic daily library backup (last 7 kept) and one-click export to Markdown.
- Fixed: file titles from Windows paths on macOS/Linux.
- **CI:**
  - Tests run on Windows, macOS and Linux.
  - Tagged releases build the Windows installer plus Apple silicon and Intel disk images.
- 67 automated tests.

## 1.2.0 - 2026-10-01
Audio release.

- **Rehearsal Coach:** practice with Voice Follow and get a report card when you finish:
  - A 0-100 score.
  - Your pace against the 130-165 wpm presenting range.
  - Filler words ("um", "uh", "like", "you know" and more), counted only when they're not part of your script.
  - Long pauses and skipped lines.
  - One focused tip, plus your score trend over your last 8 runs.
- **Live pace light** while you speak ("Pace good", "Slow down" or "Pick it up"), with a live filler counter.
- **Read Aloud:** Windows' built-in voice reads your script at your words-per-minute setting while the prompter
  scrolls along, so you can learn the rhythm. Use L, the speaker button, the tray or the phone.
- The library stores rehearsal history (database schema v2, migrated automatically).
- 58 automated tests.

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
