## 2.6.1 - 2026-10-07
Small fixes to the AI assistant and Mac screenshots.

- **Switching AI provider just works.** Changing provider in Settings forgets the old provider's model, and a model
  name from one provider is never sent to another (for example a Claude model to Gemini).
- **Retired models don't break the assistant.** If a provider retires its default model, the app switches to that
  provider's newest model instead of showing an error. A model you typed yourself is never swapped silently.
- **Mac: clearer help when a screenshot comes back gray.** An app update can reset the Screen Recording permission;
  the app now says to switch Glass Prompter off and on in System Settings, then reopen it.
- **Fewer false alarms:** a mostly white slide is no longer mistaken for a blank capture.
A see-through teleprompter that sits right under your webcam, follows your voice word by word and stays off the screen share. Free for Windows and Mac.

**Easiest:** download from the website, which picks the right file for you: https://tokunboajayi.github.io/glass-prompter/

| Your computer | File | Or run |
|---|---|---|
| Windows 10 (2004+) / 11, 64-bit | `GlassPrompter-Setup-<version>.exe` | `winget install TokunboAjayi.GlassPrompter` |
| Mac with Apple silicon (M1 to M4), macOS 13+ | `GlassPrompter-<version>-macOS-arm64.dmg` | `brew install --cask tokunboajayi/tap/glass-prompter` |
| Intel Mac, macOS 13+ | `GlassPrompter-<version>-macOS-x86_64.dmg` | same Homebrew command |

- **Windows:** run the installer. No admin rights are needed. If *"Windows protected your PC"* appears, click **More info**, then **Run anyway**.
- **Mac:** open the .dmg and drag the app to Applications. The first time, right-click it and choose **Open**. On macOS 15+, go to System Settings › Privacy & Security and click **Open Anyway**.
- **Already installed?** The app updates itself. Look for **Update to …** in the tray or menu bar.

**What's new:** see the [changelog](https://github.com/tokunboajayi/glass-prompter/blob/main/CHANGELOG.md). **Full guide:** [README](https://github.com/tokunboajayi/glass-prompter#readme).

You can check each download against the `.sha256.txt` file next to it. The in-app updater does this check automatically.
