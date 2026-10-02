# Changelog

## 2.4.2 - 2026-10-02
Fixes from people installing it on their own computers, plus an end-to-end audit that every build must pass.

- **No more duplicate copies.** Clicking the app several times while it was starting, or the installer and you
  opening it at the same moment, could leave 2 copies running. This was reproduced on 2.4.0: 4 launches at once
  gave 2 copies. A lock file now decides which copy runs; the same test gives 1 copy every time.
- **More see-through / more solid always works.**
  - Before, those buttons only changed a stored level, which had no visible effect until Ghost mode was on.
  - Now adjusting the level switches Ghost mode on, so you see the change straight away.
  - The phone's Ghost button shows whether Ghost mode is on and its level.
- **Read Aloud is more reliable.**
  - If the natural voice can't play on a computer, the system voice takes over from the same spot instead of
    stopping silently.
  - A natural-voice error that used to end reading early without a message now triggers that switch.
  - Audio devices that refuse the voice's sample rate are handled by converting the audio to the device's rate.
  - Stopping is now instant. Before, the window could freeze for up to 1.5 s.
- **End-to-end audit, run by every Windows and Mac build** (`GlassPrompter --e2e`):
  - It checks single-instance with 4 simultaneous launches, phone pairing and security, the script library and
    upload, and every remote control.
  - It also checks Ghost mode and both see-through directions, natural Read Aloud following word by word,
    Voice Follow on/off, and that there were no crashes or errors.
- **Phone remote UI test** (`tools/phone_e2e.py`): 33 checks in a mobile browser.
- The phone's live view now updates while Read Aloud or Voice Follow is running, not only while scrolling.
- The phone's "Start a new one" button is now a full 44 px touch target.

## 2.4.1 - 2026-10-02
Mac fixes, from the first real MacBook test.

- **Voice Follow works on Mac.** The speech engine (`libvosk.dyld`) was missing from the Mac app. The build tool
  only collected `.dylib` files, so it skipped this one.
- **Built-in self-test:** `GlassPrompter --selftest` checks the speech model, the Voice Follow engine, the natural
  voice and audio. Every Windows and Mac build now runs it, and the release fails if any part is missing.
- **Crash guard:** the first time a new version starts, it tests Voice Follow, the natural voice and audio output
  in separate background processes.
  - If one of them crashes on that computer, only that feature is switched off. The app stays open.
  - Read Aloud falls back to the system voice, and the crash is written to the log.
- **Moving and resizing on Mac:** the prompter and dialogs can now be dragged and resized on macOS. The system
  window-drag call does nothing for this kind of floating panel there, so the app now moves the window itself.

## 2.4.0 - 2026-10-02
Seamless UI release: one glass design language across the app and the website.

- **New ⋯ menu:** a painted glass menu replaces the OS menu, which drew square corners and a grey box on Windows.
  - Text size and ghost see-through are inline steppers, so you don't have to reopen the menu.
  - Mirror text and screen-share privacy are switches that show their live state.
  - Every item shows its keyboard shortcut as keycaps. Arrow keys, Enter and Esc all work.
- **Glass tooltips:** hovering a control shows its name and its key, styled like the app. This applies to every
  short tooltip in every dialog.
- **Shortcut sheet (F1), redesigned:**
  - Labels on the left and keys on the right, in two aligned columns.
  - The global modifier ("hold Ctrl Alt", or ⌃⌥ on a Mac) appears once instead of on every row.
  - The script syntax shows as coloured chips.
- **Status row** shows real keycaps (Space, F1) instead of plain text.
- **Control bar:** no stray focus ring on the play button.
- **Website:**
  - A sticky glass navigation bar.
  - An install panel with Windows/macOS tabs and one-click Copy. The right tab is picked for your OS.
  - A new Shortcuts section with a Windows/Mac keys switch.
  - Keycaps that match the app.

## 2.3.0 - 2026-10-02
Distribution release.

- **In-app updates:** once a day Glass Prompter checks GitHub for a new version. You can turn this off in
  Settings, and nothing about you is sent.
  - When a new version exists, an **Update to x.y.z** item appears in the tray or menu bar.
  - The update downloads with progress and is verified against GitHub's published SHA-256 before it installs.
  - On Windows it installs silently and reopens the app. On macOS it opens the new disk image.
  - You can also choose **Check for updates** in the tray menu or About, and **Skip this version**.
- **Website:** a download page on GitHub Pages (`docs/`). It detects Windows or Mac and links the right installer
  from the latest release.
- **Package managers:** `packaging/distribution.py` generates winget manifests and a Homebrew cask for any
  release.
- The installer now shows publisher, support and update links in Windows' Apps list.

## 2.2.0 - 2026-10-01
- **Adjustable ghost transparency:** ghost mode (clicks pass through) now lets you choose how see-through the
  prompter is, from 15% to 100%:
  - Adjust it with **Ctrl+Alt+[ / ]** (Control+Option on Mac). This works even while clicks pass through.
  - The phone remote has **More see-through** and **More solid** buttons, and Settings has a **Ghost level** slider.
  - The frosted backdrop switches off in ghost mode, so the prompter is truly see-through.
  - Text gets a soft dark outline, and a local shadow sits only behind the reading lines, so the script stays
    legible over any app.
  - Spoken words dim by colour, not transparency.
- The overflow menu has a ghost mode item, and the shortcut sheet lists the ghost keys.
- **Phone remote:** emoji and Unicode glyphs are replaced with a consistent stroke SVG icon set.
- **Motion:** the control bar fades out faster than it fades in.
- 73 automated tests.

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
